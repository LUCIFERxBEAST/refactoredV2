"""
reporter.py — Renders the PatchReview as text, JSON, summary and an actionable
'reviewer prompt' for the AI agent (Phase 11 output).
"""

from __future__ import annotations

import json
from typing import Dict, List

from . import models

_GLYPH = {
    models.SEVERITY_CRITICAL: "CRIT", models.SEVERITY_HIGH: "HIGH",
    models.SEVERITY_MEDIUM: "MED", models.SEVERITY_LOW: "low ",
    models.SEVERITY_INFO: "info",
}

_SEVERITY_RANK = {
    models.SEVERITY_CRITICAL: 0, models.SEVERITY_HIGH: 1,
    models.SEVERITY_MEDIUM: 2, models.SEVERITY_LOW: 3, models.SEVERITY_INFO: 4,
}


def _severity_color(severity: str) -> str:
    try:
        from colorama import Fore, Style  # noqa: F401 (Style kept for callers)
        return {
            models.SEVERITY_CRITICAL: Fore.RED,
            models.SEVERITY_HIGH: Fore.RED,
            models.SEVERITY_MEDIUM: Fore.YELLOW,
            models.SEVERITY_LOW: Fore.CYAN,
            models.SEVERITY_INFO: Fore.MAGENTA,
        }.get(severity, "")
    except Exception:
        return ""


def build_summary(review: models.PatchReview) -> str:
    n = len(review.findings)
    files = len(review.changed_files)
    strongest = _strongest_classification(review.findings)
    parts = [
        f"Patched {files} file(s) with {n} finding(s); MPG score "
        f"{review.score}/100 ({review.risk_level}).",
    ]
    if strongest:
        parts.append(f"Strongest signal: {strongest}.")
    if review.decision == models.DECISION_ACCEPT:
        parts.append("No risky patch characteristics detected.")
    if review.verification.tested:
        if review.verification.new_failures:
            parts.append(f"Verification found "
                         f"{len(review.verification.new_failures)} new failure(s).")
        else:
            parts.append("Verification confirmed no new failures.")
    return " ".join(parts)


def _strongest_classification(findings: List[models.Finding]) -> str:
    order = [
        models.CLASS_TEST_SPECIFIC_HARDCODING, models.CLASS_LOGIC_BYPASS,
        models.CLASS_SUSPICIOUS_CONSTANT, models.CLASS_INPUT_DEPENDENCY_REMOVED,
        models.CLASS_EXCEPTION_SUPPRESSION, models.CLASS_TEST_WEAKENING,
        models.CLASS_UNRELATED_CHANGE, models.CLASS_SCOPE_EXPANSION,
        models.CLASS_DISABLED_CHECK, models.CLASS_SPECIAL_CASE_BRANCH,
    ]
    seen = {f.classification for f in findings}
    for cls in order:
        if cls in seen:
            return cls
    return ""


def build_suggested_prompt(review: models.PatchReview) -> str:
    lines = [
        "An automated Minimal Patch Guard review of the current patch produced "
        "these instructions:",
        "",
        f"- Review block: REPO={review.repo_root}, BASE={review.base_ref}, "
        f"decision={review.decision}, score={review.score}/100.",
    ]
    if review.findings:
        lines.append("- Findings to resolve (highest severity first):")
        for f in sorted(review.findings,
                        key=lambda x: _SEVERITY_RANK.get(x.severity, 9)):
            lines.append(f"    * [{f.rule_id}] {f.title} ({f.file}"
                         + (f"::{f.symbol}" if f.symbol else "") + ")")
            lines.append(f"      {f.description}")
    else:
        lines.append("- No findings: keep the patch focused; no edits requested.")
    if review.verification.tested and review.verification.new_failures:
        lines.append("- Do NOT edit or delete tests to make the suite pass. "
                     f"Fix the {len(review.verification.new_failures)} new "
                     "failure(s) in application code instead, then re-run the "
                     "verification.")
    if review.generalization.status == models.GEN_VARIATION:
        lines.append("- The candidate changes behaviour on edge/holdout inputs; "
                     "add tests documenting the intended new behaviour and explain "
                     "the delta to the reviewer.")
    if review.changed_symbols:
        names = ", ".join(s.name for s in review.changed_symbols[:6])
        lines.append(f"- Focus only on the changed symbols: {names}.")
    switch = {
        models.DECISION_REJECT: "Ask the agent to rework the patch completely "
                                "before re-review.",
        models.DECISION_REQUIRE_APPROVAL: "Get a human on call to approve before "
                                          "this patch is merged.",
        models.DECISION_WARN: "Proceed with caution; resolve the low/medium "
                              "findings where cheap.",
        models.DECISION_ACCEPT: "Nothing blocks merge.",
    }
    lines.append("")
    lines.append("Recommended next step: " + switch.get(review.decision, ""))
    return "\n".join(lines)
def render_text(review: models.PatchReview) -> str:
    from colorama import Fore, Style
    out: List[str] = []
    out.append("=" * 64)
    decision_color = {
        models.DECISION_ACCEPT: Fore.GREEN, models.DECISION_WARN: Fore.YELLOW,
        models.DECISION_REQUIRE_APPROVAL: Fore.MAGENTA,
        models.DECISION_REJECT: Fore.RED,
    }.get(review.decision, "")
    out.append("  MINIMAL PATCH GUARD — review")
    out.append("=" * 64)
    out.append(f"  repo       : {review.repo_root}")
    out.append(f"  base       : {review.base_ref}")
    out.append(f"  scope      : {review.scope}")
    scope_lines = 0
    for grp in review.metric_groups:
        if grp.name == "scope_metrics":
            m = grp.metrics
            scope_lines = int(m.get("lines_changed", 0))
            out.append(f"  changed    : {len(review.changed_files)} file(s), "
                       f"{scope_lines} lines")
            out.append(f"               related={m.get('files_related')} "
                       f"unrelated={m.get('files_unrelated')} "
                       f"lines+={m.get('lines_added')} lines-={m.get('lines_removed')}")
            break
    else:
        out.append(f"  changed    : {len(review.changed_files)} file(s)")
    out.append("")
    out.append(f"  SCORE      : {review.score}/100  ({review.risk_level})  -> "
               f"{decision_color}{review.decision.upper()}{Style.RESET_ALL}")
    out.append("")
    out.append("  FINDINGS")
    if not review.findings:
        out.append("    (none — clean patch)")
    else:
        for f in sorted(review.findings, key=lambda x: _SEVERITY_RANK.get(x.severity, 9)):
            loc = f.file + (f"::{f.symbol}" if f.symbol else "")
            out.append(f"    [{_GLYPH.get(f.severity, '?')}] {f.rule_id} — {f.title}")
            out.append(f"        {loc}")
            if f.description:
                out.append(f"        {f.description}")
            if f.evidence:
                ev = f.evidence.replace("\n", " ")
                out.append(f"        evidence: {ev[:240]}")
    out.append("")
    out.append("  VERIFICATION")
    verif = review.verification
    if verif.tested:
        for run in verif.baseline:
            out.append(f"    baseline    [{run.stage}] {run.status}")
        for run in verif.candidate:
            out.append(f"    candidate   [{run.stage}] {run.status}")
        if verif.new_failures:
            out.append(f"    new failures: {len(verif.new_failures)}")
            for fl in verif.new_failures[:10]:
                out.append(f"      - {fl}")
        if verif.resolved_failures:
            out.append(f"    resolved failures: {len(verif.resolved_failures)}")
    else:
        out.append("    not run (no test command supplied)")
    out.append("")
    out.append("  GENERALIZATION")
    gen = review.generalization
    if gen.status == models.GEN_NOT_RUN:
        out.append(f"    {gen.status} ({gen.run_reason})")
    else:
        out.append(f"    {gen.status} — acceptable={gen.acceptable} "
                   f"holdout_passed={gen.holdout_passed}")
        for dline in gen.details[:8]:
            out.append(f"      {dline}")
    out.append("")
    out.append("  SUMMARY")
    out.append("    " + review.summary)
    out.append("")
    out.append("  SUGGESTED PROMPT FOR THE AGENT")
    for line in review.suggested_prompt.splitlines():
        out.append("    " + line)
    out.append("")
    out.append("=" * 64)
    return "\n".join(out)


def render_json(review: models.PatchReview) -> str:
    return json.dumps(review.to_dict(), indent=2, default=str)