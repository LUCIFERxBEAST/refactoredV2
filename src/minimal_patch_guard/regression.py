"""
regression.py — Verification matrix for the Minimal Patch Guard (Phase 6).

Runs parse + compile + targeted + full-test stages against BOTH the base tree
and the candidate tree, then compares the failure sets:

  new_failures    present in candidate only   -> real regression evidence
  resolved        present in base only
  still_failing   present in both

The baseline tree is materialized into a temp folder (git archive for ref
bases, direct copy for directory bases) so verification never mutates the
working tree.
"""

from __future__ import annotations

import ast
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile
from typing import Dict, List, Optional, Tuple

from . import models
from .patch_parser import Patch, is_test_file

_RE_FAILED = re.compile(r"^FAILED\s+(.+?)\s*$", re.MULTILINE)
_RE_ERROR_LINE = re.compile(r"^\s*E\s+(.+)$", re.MULTILINE)
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _clean(text: str) -> str:
    return _ANSI.sub("", text or "")


def extract_failures(output: str) -> List[str]:
    """Deterministic list of failing test ids / error lines from a test run."""
    out = _clean(output)
    ids = _RE_FAILED.findall(out)
    if ids:
        return sorted(set(x.strip() for x in ids))[:50]
    error_lines = _RE_ERROR_LINE.findall(out)
    if error_lines:
        return sorted(set(x.strip() for x in error_lines))[:50]
    return []


# --------------------------------------------------------------------------
# Baseline tree materialization
# --------------------------------------------------------------------------

def build_baseline_tree(patch: Patch) -> str:
    """Temp folder holding the base state of the repo (never the working tree)."""
    tmp = tempfile.mkdtemp(prefix="mpg_baseline_")
    if patch.mode == "dir":
        tree = os.path.join(tmp, "tree")
        shutil.copytree(patch.base_ref, tree)
        return tree

    # git mode: use `git archive` so the base tree is faithful to the ref.
    import io
    try:
        proc = subprocess.run(
            ["git", "-C", patch.repo_root, "--no-pager", "archive",
             "--format=zip", patch.base_ref],
            capture_output=True, timeout=60,
        )
        if proc.returncode == 0:
            tree = os.path.join(tmp, "tree")
            os.makedirs(tree, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(proc.stdout)) as zf:
                zf.extractall(tree)
            return tree
    except Exception:
        pass
    # Fallback: copy candidate tree and rewrite changed files with base content.
    tree = os.path.join(tmp, "tree")
    shutil.copytree(patch.repo_root, tree)
    for rel, text in patch.base_files.items():
        if text and rel not in patch.cand_files:
            target = os.path.join(tree, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(text)
    return tree


# --------------------------------------------------------------------------
# Stage runners
# --------------------------------------------------------------------------

def _parse_stage(files: Dict[str, str],
                 runs: List[models.VerificationRun], label: str) -> None:
    errors: List[str] = []
    for rel, text in files.items():
        if not rel.endswith(".py"):
            continue
        try:
            ast.parse(text)
            compile(text, rel, "exec")
        except SyntaxError as exc:
            errors.append(f"{rel}:{exc.lineno}: {exc.msg}")
        except Exception as exc:
            errors.append(f"{rel}: {exc}")
    if errors:
        runs.append(models.VerificationRun(
            stage="parse+compile", status=models.VERIFY_FAILED,
            detail=(f"{label}: {errors[0]}"
                    + (f" (+{len(errors) - 1} more)"
                       if len(errors) > 1 else "")),
        ))
    else:
        runs.append(models.VerificationRun(
            stage="parse+compile", status=models.VERIFY_PASSED,
            detail=f"{label}: all changed Python files parse & compile",
        ))


def _run_command(root: str, cmd: List[str], timeout: int) -> Tuple[str, str, int]:
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        return ("passed" if proc.returncode == 0 else "failed",
                proc.stdout + proc.stderr, proc.returncode)
    except FileNotFoundError:
        return "blocked", f"command not found: {cmd}", 127
    except subprocess.TimeoutExpired:
        return "timeout", f"command timed out after {timeout}s", 124


def _targeted_files(root: str, patch: Patch) -> List[str]:
    """Test files under root that reference any changed symbol (pytest focus)."""
    from .patch_parser import extract_changed_symbols
    from .scope_checks import _name_tokens
    changed_syms = extract_changed_symbols(patch)
    focus: List[str] = []
    for rel in patch.changed_files:
        if not is_test_file(rel) or not rel.endswith(".py"):
            continue
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for sym in changed_syms:
            if any(token in text for token in _name_tokens(sym)):
                focus.append(rel)
                break
    return sorted(set(focus))
# --------------------------------------------------------------------------
# Main entry
# --------------------------------------------------------------------------

def run_verification(patch: Patch, test_cmd: str, max_timeout: int = 120,
                     stage_limit: Optional[str] = None) -> models.VerificationResult:
    """Build the baseline/candidate verification matrix."""
    result = models.VerificationResult()
    if not test_cmd:
        result.baseline.append(models.VerificationRun(
            stage="full", status=models.VERIFY_NOT_RUN,
            detail="no test command supplied"))
        result.candidate.append(models.VerificationRun(
            stage="full", status=models.VERIFY_NOT_RUN,
            detail="no test command supplied"))
        return result

    # ---- parse + compile (in-process, both trees) -------------------------
    if stage_limit is None or stage_limit in ("parse", "compile", "full"):
        _parse_stage(patch.base_files, result.baseline, "base")
        _parse_stage(patch.cand_files, result.candidate, "candidate")

    run_full = (stage_limit is None or stage_limit in ("full", "targeted"))
    if run_full:
        base_tree = None
        try:
            base_tree = build_baseline_tree(patch)
        except Exception as exc:
            result.baseline.append(models.VerificationRun(
                stage="full", status=models.VERIFY_BLOCKED,
                detail=f"could not materialize baseline tree: {exc}"))
            result.baseline_failures = []
        else:
            status, out, rc = _run_command(base_tree, _command_list(test_cmd),
                                           max_timeout)
            result.baseline.append(models.VerificationRun(
                stage="full", status=status, detail=out[-1200:], returncode=rc))
            result.baseline_failures = extract_failures(out)

        status, out, rc = _run_command(patch.repo_root, _command_list(test_cmd),
                                       max_timeout)
        result.candidate.append(models.VerificationRun(
            stage="full", status=status, detail=out[-1200:], returncode=rc))
        result.candidate_failures = extract_failures(out)
        result.tested = True

        # ---- targeted (candidate only) --------------------------------------
        focus = _targeted_files(patch.repo_root, patch)
        if focus:
            tcmd = [sys.executable, "-m", "pytest"] + focus + ["-q"]
            status, out, rc = _run_command(patch.repo_root, tcmd, max_timeout)
            result.candidate.append(models.VerificationRun(
                stage="targeted", status=status,
                detail=f"focused on: {', '.join(focus)} :: " + out[-600:],
                returncode=rc))
        else:
            result.candidate.append(models.VerificationRun(
                stage="targeted", status=models.VERIFY_NOT_RUN,
                detail="no focused test files found referencing changed symbols"))

        # Only clean the baseline tree in git mode (dir mode reuses the user's
        # base folder; copytree targets are always temp so still safe to remove).
        if base_tree is not None and base_tree.startswith(tempfile.gettempdir()):
            shutil.rmtree(base_tree, ignore_errors=True)

    # ---- failure comparison ------------------------------------------------
    base_set = set(result.baseline_failures)
    cand_set = set(result.candidate_failures)
    result.new_failures = sorted(cand_set - base_set)
    result.resolved_failures = sorted(base_set - cand_set)
    result.still_failing = sorted(base_set & cand_set)
    return result


def _command_list(test_cmd: str) -> List[str]:
    parts = shlex.split(test_cmd)
    if parts and parts[0] == "pytest":
        return [sys.executable, "-m", "pytest"] + parts[1:]
    return parts