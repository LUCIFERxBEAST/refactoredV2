"""
patch_parser.py — Compute the base→candidate patch for the Minimal Patch Guard.

Two base sources are supported, controlled by ``base_ref``:

  * a git ref (default "HEAD")  -> the patch is the working tree vs that ref
  * a directory path            -> the patch is candidate vs that base folder
                                   (deterministic, git-free; used heavily in tests)

Changed lines are derived with the stdlib ``difflib.SequenceMatcher`` so the
project gains no new dependency.  Python changed-symbol extraction uses the
stdlib ``ast``; JavaScript/TypeScript uses tree-sitter (as the rest of the
codebase already does).
"""

from __future__ import annotations

import ast
import difflib
import os
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import ChangedSymbol, CHANGE_ADDED, CHANGE_MODIFIED, CHANGE_REMOVED

# Directories never considered part of a patch (consistent with dependency_graph).
_SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "dist", "build", ".idea", ".vscode", ".mypy", ".tox",
}

_MAX_FILE_BYTES = 1_500_000


def _read_text_utf8(path: str) -> Optional[str]:
    """Read a file as UTF-8 text, or None for directories/binary/oversized files."""
    try:
        if not os.path.isfile(path):
            return None
        size = os.path.getsize(path)
        if size > _MAX_FILE_BYTES:
            return None
        with open(path, "rb") as fh:
            raw = fh.read()
        if b"\x00" in raw:
            return None  # binary
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return None


def _iter_files(root: str) -> List[str]:
    """List repo-relative, forward-slash file paths under root (skip dirs above)."""
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith(".")
        ]
        for name in filenames:
            if name.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            found.append(rel)
    return sorted(found)


def collect_dir(root: str) -> Dict[str, str]:
    """Collect every text file under root: relpath -> content (UTF-8)."""
    out: Dict[str, str] = {}
    for rel in _iter_files(root):
        text = _read_text_utf8(os.path.join(root, rel))
        if text is not None:
            out[rel] = text
    return out


def _run_git(repo_root: str, args: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    """Run a git command with --no-pager and captured output (Windows-safe)."""
    try:
        proc = subprocess.run(
            ["git", "-C", repo_root, "--no-pager"] + args,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", "git executable not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"git timed out after {timeout}s"


def _git_changed_paths(repo_root: str, ref: str) -> Tuple[int, List[str], List[str]]:
    """Return (returncode, changed_paths, deleted_paths)."""
    code, out, _err = _run_git(repo_root, ["diff", "--name-status", ref, "--"])
    if code != 0:
        return code, [], []
    changed: List[str] = []
    deleted: List[str] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        path = parts[-1].replace("\\", "/")
        if status == "D":
            deleted.append(path)
        elif status.startswith("R"):
            changed.append(parts[-1].replace("\\", "/"))
        else:
            changed.append(path)
    code2, out2, _ = _run_git(
        repo_root, ["ls-files", "--others", "--exclude-standard"]
    )
    if code2 == 0:
        for p in out2.splitlines():
            p = p.replace("\\", "/")
            if p not in changed and p not in deleted:
                changed.append(p)
    return 0, changed, deleted


def _git_base_content(repo_root: str, ref: str, rel: str) -> Optional[str]:
    """Read `ref:relpath` from git as text, or None when absent."""
    code, out, _ = _run_git(repo_root, ["show", f"{ref}:{rel}"])
    if code != 0:
        return None
    return out
def diff_stats(base_text: Optional[str], cand_text: Optional[str]) -> Tuple[int, int, set]:
    """
    Returns (added_lines, removed_lines, candidate_changed_line_numbers).
    Candidate line numbers are 1-based and only cover 'insert/delete/replace'
    opcodes from SequenceMatcher (equal context is excluded).
    """
    base_text = base_text or ""
    cand_text = cand_text or ""
    base_lines = base_text.splitlines()
    cand_lines = cand_text.splitlines()

    added = 0
    removed = 0
    changed_lines: set = set()
    sm = difflib.SequenceMatcher(a=base_lines, b=cand_lines)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("insert", "replace"):
            added += j2 - j1
        if tag in ("delete", "replace"):
            removed += i2 - i1
        for line_no in range(j1 + 1, j2 + 1):
            changed_lines.add(line_no)
    return added, removed, changed_lines


@dataclass
class Patch:
    """The computed diff between base and candidate trees."""
    repo_root: str
    base_ref: str
    mode: str = "unknown"          # "git" | "dir" | "unknown"
    base_files: Dict[str, str] = field(default_factory=dict)
    cand_files: Dict[str, str] = field(default_factory=dict)
    changed_files: List[str] = field(default_factory=list)
    deleted_files: List[str] = field(default_factory=list)
    added: int = 0                 # total added lines
    removed: int = 0               # total removed lines
    file_stats: Dict[str, Tuple[int, int, set]] = field(default_factory=dict)

    @property
    def net_lines(self) -> int:
        return self.added + self.removed


def compute_patch(repo_root: str, base_ref: str) -> Patch:
    """
    Diff the candidate working tree against base_ref (git ref or directory).
    Raises FileNotFoundError when repo_root is missing and ValueError when a
    git base_ref cannot be resolved.
    """
    repo_root = os.path.abspath(repo_root)
    if not os.path.isdir(repo_root):
        raise FileNotFoundError(f"repo root does not exist: {repo_root}")

    patch = Patch(repo_root=repo_root, base_ref=base_ref)

    # ---- directory mode -------------------------------------------------
    if os.path.isdir(base_ref):
        patch.mode = "dir"
        base_root = os.path.abspath(base_ref)
        patch.base_files = collect_dir(base_root)
        patch.cand_files = collect_dir(repo_root)
        all_files = sorted(set(patch.base_files) | set(patch.cand_files))
        for rel in all_files:
            base_text = patch.base_files.get(rel)
            cand_text = patch.cand_files.get(rel)
            if base_text == cand_text:
                continue
            patch.changed_files.append(rel)
            if base_text is not None and cand_text is None:
                patch.deleted_files.append(rel)
        return patch

    # ---- git mode --------------------------------------------------------
    code, _, _err = _run_git(repo_root, ["rev-parse", "--verify", f"{base_ref}^{{commit}}"])
    if code != 0:
        raise ValueError(
            f"base_ref {base_ref!r} is neither an existing directory nor a "
            f"resolvable git ref ({_err.strip()})"
        )
    patch.mode = "git"
    code, changed, deleted = _git_changed_paths(repo_root, base_ref)
    if code != 0:
        raise ValueError("could not list changed files against base_ref")
    patch.cand_files = collect_dir(repo_root)
    for rel in sorted(set(changed) | set(deleted)):
        base_text = _git_base_content(repo_root, base_ref, rel)
        cand_text = patch.cand_files.get(rel)
        if cand_text is None and os.path.isfile(os.path.join(repo_root, rel)):
            cand_text = _read_text_utf8(os.path.join(repo_root, rel))
        patch.base_files[rel] = base_text or ""
        if cand_text is not None:
            patch.cand_files[rel] = cand_text
        if base_text == cand_text:
            continue
        patch.changed_files.append(rel)
        if cand_text is None:
            patch.deleted_files.append(rel)
    return patch


# --------------------------------------------------------------------------
# Changed-symbol extraction (Python via ast, JS/TS via tree-sitter)
# --------------------------------------------------------------------------

def _python_symbols(source: str) -> Dict[str, Tuple[str, object]]:
    """name -> (kind, ast node) for top-level defs, classes/methods, constants."""
    out: Dict[str, Tuple[str, object]] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = ("function", node)
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[f"{node.name}.{sub.name}"] = ("method", sub)
            out[node.name] = ("class", node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = ("constant", node)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                out[node.target.id] = ("annotated_constant", node)
    return out


def _python_changed_symbols(base_text: str, cand_text: str, rel: str) -> List[ChangedSymbol]:
    base_syms = _python_symbols(base_text)
    cand_syms = _python_symbols(cand_text)
    out: List[ChangedSymbol] = []
    for name in sorted(set(base_syms) | set(cand_syms)):
        old = base_syms.get(name)
        new = cand_syms.get(name)
        if old is None:
            status, kind = CHANGE_ADDED, new[0]
            old_excerpt = ""
            new_excerpt = _excerpt(cand_text, new[1])
        elif new is None:
            status, kind = CHANGE_REMOVED, old[0]
            old_excerpt = _excerpt(base_text, old[1])
            new_excerpt = ""
        else:
            if ast.dump(old[1]) == ast.dump(new[1]):
                continue  # unchanged
            status, kind = CHANGE_MODIFIED, old[0]
            old_excerpt = _excerpt(base_text, old[1])
            new_excerpt = _excerpt(cand_text, new[1])
        old_params, new_params = _params_of(old), _params_of(new)
        out.append(ChangedSymbol(
            name=name, kind=kind, file=rel, status=status,
            old_excerpt=old_excerpt[:400], new_excerpt=new_excerpt[:400],
            old_params=old_params, new_params=new_params,
        ))
    return out


def _params_of(info) -> List[str]:
    if info is None:
        return []
    kind, node = info
    if kind not in ("function", "method"):
        return []
    args = node.args
    names = []
    for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
        names.append(a.arg)
    if args.vararg:
        names.append("*" + args.vararg.arg)
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return names


def _excerpt(source: str, node) -> str:
    try:
        seg = ast.get_source_segment(source, node)
    except (TypeError, ValueError):
        seg = None
    if seg is None:
        lines = source.splitlines()
        lo = max(0, getattr(node, "lineno", 1) - 1)
        hi = min(len(lines), getattr(node, "end_lineno", lo + 1) or (lo + 1))
        seg = "\n".join(lines[lo:hi])
    return "\n".join([ln.rstrip() for ln in seg.splitlines()[:12]])


def _js_top_level_bodies(source: str) -> Dict[str, str]:
    """name -> decoded source text of top-level function/class declarations."""
    out: Dict[str, str] = {}
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_javascript
    except ImportError:
        return out
    try:
        parser = Parser(Language(tree_sitter_javascript.language()))
        tree = parser.parse(source.encode("utf-8", errors="replace"))
    except Exception:
        return out
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in ("function_declaration", "generator_function_declaration",
                         "class_declaration"):
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                out[name_node.text.decode("utf-8", errors="replace")] = (
                    node.text.decode("utf-8", errors="replace"))
            continue
        stack.extend(node.named_children)
    return out


def _js_changed_symbols(base_text: str, cand_text: str, rel: str) -> List[ChangedSymbol]:
    base = _js_top_level_bodies(base_text)
    cand = _js_top_level_bodies(cand_text)
    out: List[ChangedSymbol] = []
    for name in sorted(set(base) | set(cand)):
        old = base.get(name)
        new = cand.get(name)
        if old is None:
            out.append(ChangedSymbol(name=name, kind="function", file=rel,
                                     status=CHANGE_ADDED, new_excerpt=new[:400]))
        elif new is None:
            out.append(ChangedSymbol(name=name, kind="function", file=rel,
                                     status=CHANGE_REMOVED, old_excerpt=old[:400]))
        elif old != new:
            out.append(ChangedSymbol(name=name, kind="function", file=rel,
                                     status=CHANGE_MODIFIED,
                                     old_excerpt=old[:400], new_excerpt=new[:400]))
    return out


def changed_symbols_for_file(rel: str, base_text: Optional[str],
                             cand_text: Optional[str]) -> List[ChangedSymbol]:
    """Changed top-level symbols between two versions of a single file."""
    base_text = base_text or ""
    cand_text = cand_text or ""
    ext = os.path.splitext(rel)[1].lower()
    if ext == ".py":
        return _python_changed_symbols(base_text, cand_text, rel)
    if ext in (".js", ".ts"):
        return _js_changed_symbols(base_text, cand_text, rel)
    return []


def extract_changed_symbols(patch: Patch) -> List[ChangedSymbol]:
    """All changed symbols across every changed file of the patch."""
    out: List[ChangedSymbol] = []
    for rel in patch.changed_files:
        out.extend(changed_symbols_for_file(
            rel, patch.base_files.get(rel), patch.cand_files.get(rel)))
    return out


def is_test_file(rel: str) -> bool:
    """Heuristic test-file detection shared by scope/test-integrity checks."""
    name = os.path.basename(rel).lower()
    parts = rel.replace("\\", "/").split("/")
    return (
        name.endswith("_test.py")
        or name.startswith("test_")
        or ".test." in name
        or "test" in parts[:-1]
    )