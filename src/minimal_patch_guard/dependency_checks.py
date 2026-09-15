"""
dependency_checks.py — Dependency-path scope rules (Phase 3).

When candidate verification reports new failures, files that changed but live
outside the blast-radius cone of the failing symbol are suspicious: a minimal
patch should not touch files that cannot influence the test that just broke.
"""

from __future__ import annotations

from typing import Dict, List

from ._ts_subprocess import blast_radius_files_batch
from . import models
from .patch_parser import Patch, is_test_file


def run_dependency_checks(patch: Patch,
                          changed_symbols: List[models.ChangedSymbol],
                          verification: models.VerificationResult,
                          findings_out: List[models.Finding]) -> Dict:
    """Return dependency_metrics and append related findings."""
    failed_lines = " ".join(verification.candidate_failures)
    if not verification.tested or not failed_lines:
        return {
            "failing_symbols": [],
            "affected_files": [],
            "files_outside_cone": [],
            "cone_size": 0,
            "note": "no candidate failure output to cross-reference",
        }

    failing_symbols: List[str] = []
    affected_files: List[str] = []
    outside: List[str] = []

    # Collect matching failure symbols first, then query blast radius for all
    # of them in one batched subprocess instead of one child per symbol.
    import re
    failing_tokens: List[str] = []
    symbol_by_token: Dict[str, models.ChangedSymbol] = {}
    for sym in changed_symbols:
        token = sym.name.rsplit(".", 1)[-1]
        if sym.kind not in ("function", "method", "class"):
            continue
        # Only consider symbols that show up in the failure output.
        if not re.search(r"\b" + re.escape(token) + r"\b", failed_lines):
            continue
        if token not in failing_tokens:
            failing_tokens.append(token)
            symbol_by_token[token] = sym

    cone_by_token = blast_radius_files_batch(patch.repo_root, failing_tokens)
    for token in failing_tokens:
        sym = symbol_by_token[token]
        failing_symbols.append(sym.name)
        cone = set(cone_by_token.get(token, []))
        affected_files.extend(sorted(cone))
        for rel in patch.changed_files:
            if is_test_file(rel) or rel in cone:
                continue
            if any(s.file == rel for s in changed_symbols):
                continue  # definition site is allowed
            outside.append(rel)
            findings_out.append(models.Finding(
                rule_id="MPG-904",
                title="File changed outside the failing dependency path",
                severity=models.SEVERITY_LOW,
                classification=models.CLASS_SCOPE_EXPANSION,
                description=(f"'{rel}' changed even though '{sym.name}' is the "
                             "symbol failing verification; a minimal patch would "
                             "not need to touch it."),
                evidence=f"failing symbol: {sym.name}", file=rel,
            ))

    return {
        "failing_symbols": sorted(set(failing_symbols)),
        "affected_files": sorted(set(affected_files)),
        "files_outside_cone": sorted(set(outside)),
        "cone_size": len(set(affected_files)),
        "note": f"{len(set(failing_symbols))} failing symbol(s) cross-referenced"
                if failing_symbols else "no failing symbols matched changed code",
    }