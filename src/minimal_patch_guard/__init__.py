"""
minimal_patch_guard — Minimal Patch Guard for Refactor-Guard.

A self-contained review subsystem that detects risky patch characteristics
(hard-coded outputs, test weakening, unrelated changes) and integrates static
analysis with a verification matrix.  CLI integration lives in src/main.py
(`review-patch`); MCP integration in src/mcp_server.py.

Usage::

    from src.minimal_patch_guard import review_patch
    review = review_patch(repo_root="...", base_ref="HEAD",
                          test_cmd="pytest -q", run_generalization=True)
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from . import models, policy as _policy_mod
from .patch_parser import compute_patch, diff_stats, extract_changed_symbols
from . import (behavior_checks, dependency_checks, metamorphic, regression,
               reporter, scope_checks, static_checks, test_integrity, scoring)

VERSION = "1.0.0"

__all__ = ["review_patch", "VERSION", "models"]


def review_patch(*, repo_root: str, base_ref: str = "HEAD",
                 test_cmd: Optional[str] = None,
                 strict_minimality: Optional[bool] = None,
                 max_files_changed: Optional[int] = None,
                 max_lines_changed: Optional[int] = None,
                 require_approval: Optional[bool] = None,
                 run_generalization: Optional[bool] = None,
                 skip_generalization: Optional[bool] = None,
                 operation: Optional[str] = None,
                 output_format: str = "text",
                 policy: Optional[Dict[str, Any]] = None) -> models.PatchReview:
    """Run the full MPG review pipeline for the working tree at repo_root.

    base_ref may be a git ref (default "HEAD") or a directory containing the
    base snapshot (deterministic and git-free).
    """
    policy = policy or _policy_mod.load_policy(repo_root)
    opts = models.ReviewOptions(
        repo_root=repo_root, base_ref=base_ref, test_cmd=test_cmd,
        strict_minimality=strict_minimality,
        max_files_changed=max_files_changed,
        max_lines_changed=max_lines_changed,
        require_approval=require_approval,
        run_generalization=run_generalization,
        skip_generalization=skip_generalization,
        operation=operation, output_format=output_format,
    )
    opts = _policy_mod.resolve_options(policy, opts)

    patch = compute_patch(repo_root, base_ref)
    if not patch.changed_files:
        review = _empty_review(patch, opts, policy)
        review.summary = "No changes detected between base and candidate."
        review.suggested_prompt = reporter.build_suggested_prompt(review)
        return review

    # Per-file line stats fill patch.added / patch.removed / file_stats.
    for rel in patch.changed_files:
        added, removed, cand_lines = diff_stats(
            patch.base_files.get(rel), patch.cand_files.get(rel))
        patch.file_stats[rel] = (added, removed, cand_lines)
        patch.added += added
        patch.removed += removed

    changed_symbols = extract_changed_symbols(patch)

    # ---- Phase 2 static checks -------------------------------------------
    allowed_vars = set(policy.get("_conditionally_allowed_vars", []))
    findings = static_checks.run_static_checks(patch, changed_symbols, allowed_vars)

    # ---- Phase 3 scope & dependency ---------------------------------------
    scope, scope_findings, scope_metrics = scope_checks.analyze_scope(
        patch, changed_symbols,
        max_files=int(opts.max_files_changed or 10),
        max_lines=int(opts.max_lines_changed or 200),
        operation=opts.operation)
    findings.extend(scope_findings)

    behavior_groups = behavior_checks.analyze_behavior(patch, changed_symbols)

    # ---- Phase 5 test integrity --------------------------------------------
    findings.extend(test_integrity.run_test_integrity(patch))

    # ---- Phase 6 verification ----------------------------------------------
    verification = regression.run_verification(
        patch, opts.test_cmd or "",
        max_timeout=int(policy.get("max_runtime_seconds", 120)),
        stage_limit=policy.get("_verification_stage"))

    dep_metrics = dependency_checks.run_dependency_checks(
        patch, changed_symbols, verification, findings)

    # ---- Phase 7 generalization ---------------------------------------------
    has_hardcoding = any(
        f.classification in (models.CLASS_SUSPICIOUS_CONSTANT,
                             models.CLASS_TEST_SPECIFIC_HARDCODING,
                             models.CLASS_SPECIAL_CASE_BRANCH)
        for f in findings)
    want_gen = bool(opts.run_generalization) or has_hardcoding
    if opts.skip_generalization and not opts.run_generalization:
        want_gen = False  # explicit skip wins over auto-trigger
    if want_gen:
        gen = metamorphic.run_generalization(
            patch, changed_symbols,
            run_reason=("auto (hardcoding signal detected)" if has_hardcoding
                        else "requested"),
            max_timeout=int(policy.get("max_runtime_seconds", 120)))
    else:
        gen = models.GeneralizationResult(
            status=models.GEN_NOT_RUN,
            run_reason="not requested (set run_generalization=True to probe)")

    # ---- metrics assembly ---------------------------------------------------
    metrics = {
        "size_metrics": _size_metrics(patch),
        "scope_metrics": scope_metrics,
        **behavior_groups,
        "dependency_metrics": dep_metrics,
        "regression_metrics": _regression_metrics(verification),
        "coverage_metrics": _coverage_metrics(gen),
        "verification_completeness_metrics":
            _verification_completeness_metrics(verification, gen),
    }
    review = models.PatchReview(
        repo_root=os.path.abspath(repo_root), base_ref=str(base_ref),
        scope=scope, changed_files=list(patch.changed_files),
        changed_symbols=changed_symbols, findings=findings,
        metric_groups=[models.MetricGroup(name=k, metrics=v)
                       for k, v in metrics.items()],
        verification=verification, generalization=gen,
        policy=policy,
    )

    # ---- Phase 9 scoring & decision ----------------------------------------
    score_info = scoring.compute_score(
        review, opts, policy,
        generalization_acceptable=gen.acceptable
        if gen.status != models.GEN_NOT_RUN else None)
    review.score = score_info["score"]
    review.risk_level = score_info["risk_level"]
    review.decision = score_info["decision"]

    # ---- Phase 11 output -----------------------------------------------------
    review.summary = reporter.build_summary(review)
    review.suggested_prompt = reporter.build_suggested_prompt(review)
    return review


# --------------------------------------------------------------------------
# Metrics helpers
# --------------------------------------------------------------------------

def _size_metrics(patch) -> Dict[str, Any]:
    per_file = {
        rel: [patch.file_stats[rel][0], patch.file_stats[rel][1]]
        for rel in patch.changed_files if rel in patch.file_stats
    }
    return {
        "files_changed": len(patch.changed_files),
        "added_lines": patch.added,
        "removed_lines": patch.removed,
        "total_lines_changed": patch.net_lines,
        "per_file": per_file,
    }


def _regression_metrics(verification: models.VerificationResult) -> Dict[str, Any]:
    return {
        "baseline_status": verification.baseline[-1].status
        if verification.baseline else models.VERIFY_NOT_RUN,
        "candidate_status": verification.candidate[-1].status
        if verification.candidate else models.VERIFY_NOT_RUN,
        "new_failures_count": len(verification.new_failures),
        "resolved_failures_count": len(verification.resolved_failures),
        "still_failing_count": len(verification.still_failing),
        "total_failures": (len(verification.new_failures)
                           + len(verification.resolved_failures)
                           + len(verification.still_failing)),
    }


def _coverage_metrics(gen: models.GeneralizationResult) -> Dict[str, Any]:
    return {
        "measured": gen.status != models.GEN_NOT_RUN,
        "statement": None, "branch": None, "function": None,
        "metamorphic_cases": gen.attempted_cases,
        "note": "statement/branch/function coverage not instrumented",
    }


def _verification_completeness_metrics(verification: models.VerificationResult,
                                       gen: models.GeneralizationResult) -> Dict[str, Any]:
    def stage_status(runs, name):
        for run in runs:
            if run.stage == name:
                return run.status
        return models.VERIFY_NOT_RUN

    runs = list(verification.baseline) + list(verification.candidate)
    return {
        "parse": stage_status(runs, "parse+compile"),
        "compile": stage_status(runs, "parse+compile"),
        "type_check": models.VERIFY_NOT_MEASURED,
        "lint": models.VERIFY_NOT_MEASURED,
        "targeted_tests": stage_status(verification.candidate, "targeted"),
        "full_tests": stage_status(runs, "full"),
        "metamorphic_differential": gen.status,
        "holdout": "passed" if gen.holdout_passed else models.VERIFY_NOT_MEASURED,
    }


def _empty_review(patch, opts, policy) -> models.PatchReview:
    metrics = {
        "size_metrics": {"files_changed": 0, "added_lines": 0,
                         "removed_lines": 0, "total_lines_changed": 0, "per_file": {}},
        "scope_metrics": {"files_changed": 0, "files_related": 0,
                          "files_unrelated": 0, "files_changed_ratio": 1.0,
                          "lines_changed": 0, "lines_added": 0, "lines_removed": 0,
                          "largest_file_change": 0},
        "control_flow_metrics": {}, "behavior_metrics": {},
        "input_dependency_metrics": {}, "complexity_metrics": {},
        "regression_metrics": {"baseline_status": models.VERIFY_NOT_RUN,
                               "candidate_status": models.VERIFY_NOT_RUN,
                               "new_failures_count": 0,
                               "resolved_failures_count": 0,
                               "still_failing_count": 0, "total_failures": 0},
        "coverage_metrics": {"measured": False, "statement": None, "branch": None,
                             "function": None, "metamorphic_cases": 0},
        "verification_completeness_metrics": {
            "parse": models.VERIFY_NOT_RUN, "compile": models.VERIFY_NOT_RUN,
            "type_check": models.VERIFY_NOT_MEASURED, "lint": models.VERIFY_NOT_MEASURED,
            "targeted_tests": models.VERIFY_NOT_RUN, "full_tests": models.VERIFY_NOT_RUN,
            "metamorphic_differential": models.GEN_NOT_RUN,
            "holdout": models.VERIFY_NOT_MEASURED},
    }
    return models.PatchReview(
        repo_root=os.path.abspath(patch.repo_root), base_ref=str(patch.base_ref),
        scope=models.SCOPE_UNKNOWN, changed_files=[],
        changed_symbols=[], findings=[],
        metric_groups=[models.MetricGroup(name=k, metrics=v)
                       for k, v in metrics.items()],
        score=100, risk_level=models.RISK_MINIMAL,
        decision=models.DECISION_ACCEPT, policy=policy,
    )