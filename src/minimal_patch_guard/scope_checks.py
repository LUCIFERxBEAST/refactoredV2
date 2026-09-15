"""
scope_checks.py — Minimality scope rules for the Minimal Patch Guard (Phase 3).

  MPG-004  unrelated change / scope expansion among the changed files
  operation footprints (rename / extract-function / move-symbol) when declared
  size limits (max_files_changed / max_lines_changed) from policy or CLI

Tree-sitter reference scanning runs in a subprocess: the installed binding can
segfault natively under some CPython builds.  When the subprocess fails we
degrade gracefully to text-mention matching.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from ._ts_subprocess import scan_repo_files_batch
from . import models
from .patch_parser import Patch, is_test_file

# symbol-name word-boundary matcher for Python identifiers / dotted method names.
_TOKEN_RE = re.compile(r"(?<![\w.])%s(?![\w\':])")


def _name_tokens(sym: models.ChangedSymbol) -> List[str]:
    tokens = [sym.name]
    if "." in sym.name:
        tokens.append(sym.name.rsplit(".", 1)[-1])
    return tokens


def _findings_for_scope(f, symbol, reason):
    return models.Finding(
        rule_id="MPG-004", title="Unrelated change present",
        severity=models.SEVERITY_MEDIUM, classification=models.CLASS_UNRELATED_CHANGE,
        description=(f"'{f}' changed without referencing any other symbol changed "
                     "by this patch; it looks unrelated to the refactor."),
        evidence=reason, file=f, symbol=symbol,
        recommended_action=(
            "Drop this file from the patch, or clearly justify why it must "
            "change as part of the refactor."),
    )


def _expansion(f, title, detail):
    return models.Finding(
        rule_id="MPG-004", title=title,
        severity=models.SEVERITY_MEDIUM, classification=models.CLASS_SCOPE_EXPANSION,
        description=detail, evidence=f"file={f}", file=f or "",
        recommended_action="Keep the patch minimal; split unrelated edits out.",
    )


def _mentions(text: str, token: str) -> bool:
    if token not in text:
        return False
    if token.isidentifier():
        pattern = _TOKEN_RE.pattern % re.escape(token)
        return bool(re.search(pattern, text))
    return token in text


# --------------------------------------------------------------------------
# Tree-sitter reference scan, isolated in a subprocess
# --------------------------------------------------------------------------

def _related_files(patch: Patch,
                   changed_symbols: List[models.ChangedSymbol]) -> Set[str]:
    """Files that are plausibly part of the same change as the symbols."""
    related: Set[str] = set()
    defined_in: Set[str] = set()
    for sym in changed_symbols:
        defined_in.add(sym.file)

    # Files defining a changed symbol are intrinsically related.
    related.update(defined_in)

    # Tree-sitter based reference scan for real usage reach (subprocess).
    # One batched subprocess call instead of one per changed symbol.
    try:
        eligible_tokens: List[str] = []
        for sym in changed_symbols:
            token = sym.name.rsplit(".", 1)[-1]
            if sym.kind in ("function", "method", "class") and len(token) >= 3:
                eligible_tokens.append(token)
        batch_results = scan_repo_files_batch(patch.repo_root, eligible_tokens)
        for static, dynamic in batch_results.values():
            related.update(static)
            related.update(dynamic)
    except Exception:
        pass  # degradation: fall back to text mention matching

    # Text-mention matching for every other changed file.
    for rel in patch.changed_files:
        if rel in related:
            continue
        text = patch.cand_files.get(rel) or patch.base_files.get(rel) or ""
        for sym in changed_symbols:
            if sym.file == rel:
                continue
            for token in _name_tokens(sym):
                if text and _mentions(text, token):
                    related.add(rel)
                    break
            if rel in related:
                break
    return related


def classify_scope(changed_files: List[str], related: Set[str],
                   symbols: List[models.ChangedSymbol]) -> str:
    if len(changed_files) <= 1:
        if len(symbols) <= 2:
            return models.SCOPE_SYMBOL_SPECIFIC
        return models.SCOPE_SMALL_FUNCTION
    if len(changed_files) <= 4:
        return models.SCOPE_SINGLE_BEHAVIOR
    unrelated = [f for f in changed_files if f not in related]
    if unrelated:
        return models.SCOPE_BROAD
    return models.SCOPE_DEPENDENCY_ONLY
def analyze_scope(patch: Patch, changed_symbols: List[models.ChangedSymbol],
                  max_files: int, max_lines: int,
                  operation: Optional[str]) -> Tuple[str, List[models.Finding], Dict]:
    """Returns (scope, findings, scope_metrics)."""
    findings: List[models.Finding] = []
    changed_files = patch.changed_files
    related = _related_files(patch, changed_symbols)

    # ---- MPG-004 unrelated changes ---------------------------------------
    for rel in sorted(changed_files):
        if rel in related:
            continue
        if is_test_file(rel):
            findings.append(models.Finding(
                rule_id="MPG-004", title="Changed test does not touch the patch symbols",
                severity=models.SEVERITY_LOW,
                classification=models.CLASS_UNRELATED_CHANGE,
                description=(f"Test file '{rel}' changed but it does not reference "
                             "any symbol changed by this patch."),
                file=rel,
                recommended_action="Verify the test change is intentional.",
            ))
            continue
        syms = [s.name for s in changed_symbols if s.file == rel]
        findings.append(_findings_for_scope(
            rel, syms[0] if syms else "",
            f"no reference to any changed symbol in {len(changed_symbols)} "
            f"changed symbol(s)",
        ))

    # ---- size thresholds ---------------------------------------------------
    if len(changed_files) > max_files:
        findings.append(_expansion(
            changed_files[0] if changed_files else "",
            "Scope expansion — too many files changed",
            f"patch touches {len(changed_files)} files (> {max_files})"))

    if patch.net_lines > max_lines:
        findings.append(models.Finding(
            rule_id="MPG-004", title="Scope expansion — patch larger than the threshold",
            severity=models.SEVERITY_MEDIUM,
            classification=models.CLASS_SCOPE_EXPANSION,
            description=(f"patch changes {patch.net_lines} lines (> {max_lines}); "
                         "large patches are harder to verify and usually mix "
                         "unrelated edits."),
            evidence=f"added={patch.added} removed={patch.removed}",
        ))

    # ---- operation footprints ----------------------------------------------
    findings.extend(_operation_footprint_findings(patch, operation, changed_symbols))

    scope = classify_scope(changed_files, related, changed_symbols)
    related_non_test = [f for f in changed_files if not is_test_file(f) and f in related]
    per_file_lines = sorted(
        ((patch.file_stats.get(f, (0, 0, set()))[0]
          + patch.file_stats.get(f, (0, 0, set()))[1]), f)
        for f in changed_files
    )
    scope_metrics = {
        "files_changed": len(changed_files),
        "files_related": len(related_non_test),
        "files_unrelated": len([f for f in changed_files if f not in related]),
        "files_changed_ratio": round(len(related_non_test) / len(changed_files), 2)
        if changed_files else 1.0,
        "lines_changed": patch.net_lines,
        "lines_added": patch.added,
        "lines_removed": patch.removed,
        "largest_file_change": per_file_lines[-1][0] if per_file_lines else 0,
    }
    return scope, findings, scope_metrics
# --------------------------------------------------------------------------
# Operation-aware footprints
# --------------------------------------------------------------------------

def _operation_footprint_findings(patch: Patch, operation: Optional[str],
                                  changed_symbols: List[models.ChangedSymbol]):
    if not operation:
        return []
    findings: List[models.Finding] = []
    non_test = [f for f in patch.changed_files if not is_test_file(f)]

    if operation == "rename":
        new_functions = [s for s in changed_symbols
                         if s.status == models.CHANGE_ADDED
                         and s.kind in ("function", "method", "class")]
        if new_functions:
            findings.append(_expansion(
                non_test[0] if non_test else "",
                "Scope expansion — new definitions during rename",
                f"{len(new_functions)} new top-level symbol(s) added under "
                f"--operation rename: {[s.name for s in new_functions][:5]}",
            ))
        test_changed = [f for f in patch.changed_files if is_test_file(f)]
        if test_changed:
            findings.append(models.Finding(
                rule_id="MPG-004", title="Test files changed during rename",
                severity=models.SEVERITY_LOW,
                classification=models.CLASS_SCOPE_EXPANSION,
                description=(f"A rename normally does not need test changes; "
                             f"{len(test_changed)} test file(s) changed."),
                file=", ".join(test_changed),
                recommended_action="Only touch tests that assert on the old name.",
            ))
    elif operation == "extract-function":
        if len(non_test) > 2:
            findings.append(_expansion(
                non_test[0], "Scope expansion — extraction touches too many files",
                f"extract-function expects 1-2 changed source files, got {len(non_test)}",
            ))
        test_changed = [f for f in patch.changed_files if is_test_file(f)]
        if test_changed:
            findings.append(_expansion(
                test_changed[0], "Scope expansion — tests changed during extraction",
                "extract-function is behaviour-preserving and should not require "
                "test edits.",
            ))
    elif operation == "move-symbol":
        additions = [s for s in changed_symbols if s.status == models.CHANGE_ADDED]
        removals = [s for s in changed_symbols if s.status == models.CHANGE_REMOVED]
        if (len(additions) + len(removals)) > 2:
            findings.append(_expansion(
                non_test[0] if non_test else "",
                "Scope expansion — more symbols moved than declared",
                f"move-symbol expects 1 symbol moved; saw "
                f"{len(additions)} added / {len(removals)} removed definitions",
            ))
    return findings