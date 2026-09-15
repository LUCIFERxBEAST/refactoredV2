"""
scoring.py — 0-100 scoring and decision for the Minimal Patch Guard (Phase 9).

Factor weights (from policy, defaulting to the specification's numbers):
  swap 37%   scope 20%   output-only 15%   risk 12%   rewards 11%
plus a capped penalty term (~5%) that can only subtract.

Outputs:
  score      0-100 integer
  risk_level minimal / moderate / significant / risky
  decision   accept / warn / require_approval / reject
"""

from __future__ import annotations

from typing import Dict, Optional

from . import models

# Classifications whose presence indicates an output-only / hardcoded swap.
SWAP_CLASSIFICATIONS = {
    models.CLASS_SUSPICIOUS_CONSTANT, models.CLASS_TEST_SPECIFIC_HARDCODING,
    models.CLASS_INPUT_DEPENDENCY_REMOVED, models.CLASS_SPECIAL_CASE_BRANCH,
    models.CLASS_EXCEPTION_SUPPRESSION, models.CLASS_LOGIC_BYPASS,
}
OUTPUT_ONLY_CLASSIFICATIONS = {
    models.CLASS_SUSPICIOUS_CONSTANT, models.CLASS_TEST_SPECIFIC_HARDCODING,
    models.CLASS_SPECIAL_CASE_BRANCH,
}

_SEVERITY_POINTS = {
    models.SEVERITY_CRITICAL: 15,
    models.SEVERITY_HIGH: 8,
    models.SEVERITY_MEDIUM: 5,
    models.SEVERITY_LOW: 2,
    models.SEVERITY_INFO: 0,
}


def _metric(review: models.PatchReview, group: str, name: str):
    for grp in review.metric_groups:
        if grp.name == group:
            return grp.metrics.get(name)
    return None
def compute_score(review: models.PatchReview, opts: models.ReviewOptions,
                  policy: Dict,
                  generalization_acceptable: Optional[bool] = None) -> Dict:
    findings = review.findings
    weights = policy.get("weights", {})
    w = {
        "swap": float(weights.get("swap", 0.37)),
        "scope": float(weights.get("scope", 0.20)),
        "output_only": float(weights.get("output_only", 0.15)),
        "risk": float(weights.get("risk", 0.12)),
        "rewards": float(weights.get("rewards", 0.11)),
    }
    decisions_cfg = policy.get("decisions", {})
    req_threshold = int(decisions_cfg.get("require_approval_threshold", 45))
    warn_threshold = int(decisions_cfg.get("warn_threshold", 20))
    swap_reject = int(decisions_cfg.get("swap_reject_threshold", 35))

    # ---- factor: swap / over-fitting ---------------------------------------
    swap_points = sum(_SEVERITY_POINTS.get(f.severity, 0)
                      for f in findings if f.classification in SWAP_CLASSIFICATIONS)
    swap_score = max(0, 100 - min(100, swap_points))

    # ---- factor: scope / minimality -----------------------------------------
    n_unrelated = int(_metric(review, "scope_metrics", "files_unrelated") or 0)
    n_expansion = sum(1 for f in findings
                      if f.classification == models.CLASS_SCOPE_EXPANSION)
    scope_score = max(0, 100 - 15 * n_unrelated - 10 * n_expansion)

    # ---- factor: output-only ------------------------------------------------
    n_output = sum(1 for f in findings
                   if f.classification in OUTPUT_ONLY_CLASSIFICATIONS)
    output_score = max(0, 100 - 5 * n_output - (40 if n_output else 0))

    # ---- factor: risk (overall severity mass) --------------------------------
    risk_points = sum(_SEVERITY_POINTS.get(f.severity, 0) for f in findings)
    risk_score = max(0, 100 - min(100, risk_points))

    # ---- factor: rewards -----------------------------------------------------
    rewards_raw = 0
    if not findings:
        rewards_raw += 20
    verif = review.verification
    if verif.tested:
        cand_last = verif.candidate[-1] if verif.candidate else None
        if not verif.new_failures and cand_last is not None \
                and cand_last.status != models.VERIFY_FAILED:
            rewards_raw += 15
    if generalization_acceptable:
        rewards_raw += 12
    if not any(f.severity in (models.SEVERITY_CRITICAL, models.SEVERITY_HIGH)
               for f in findings):
        rewards_raw += 5
    rewards = min(100, rewards_raw)

    # ---- penalty (capped, only subtracts) ------------------------------------
    penalty = 0
    if n_unrelated >= 2:
        penalty += 3
    if len(findings) > 5:
        penalty += 2
    penalty = min(penalty, 5)

    raw = (w["swap"] * swap_score + w["scope"] * scope_score
           + w["output_only"] * output_score + w["risk"] * risk_score
           + w["rewards"] * rewards) - penalty
    score = max(0, min(100, int(round(raw))))

    factors = {
        "swap_score": int(swap_score), "scope_score": int(scope_score),
        "output_only_score": int(output_score), "risk_score": int(risk_score),
        "rewards_raw": int(rewards), "penalty": int(penalty), "weights": w,
    }
    risk_level = _risk_level_of(score)
    decision = _decide(
        findings=findings, score=score, swap_score=swap_score,
        opts=opts, policy=policy, req_threshold=req_threshold,
        warn_threshold=warn_threshold, swap_reject=swap_reject,
        generalization_acceptable=generalization_acceptable, review=review,
    )
    return {"score": score, "risk_level": risk_level, "decision": decision,
            "factors": factors}


def _risk_level_of(score: int) -> str:
    if score < 20:
        return models.RISK_MINIMAL
    if score < 45:
        return models.RISK_MODERATE
    if score < 75:
        return models.RISK_SIGNIFICANT
    return models.RISK_RISKY


def _decide(findings, score, swap_score, opts, policy, req_threshold,
            warn_threshold, swap_reject, generalization_acceptable,
            review) -> str:
    criticals = [f for f in findings if f.severity == models.SEVERITY_CRITICAL]
    highs = [f for f in findings if f.severity == models.SEVERITY_HIGH]
    swaps = [f for f in findings if f.classification in SWAP_CLASSIFICATIONS]
    weakening = [f for f in findings
                 if f.classification == models.CLASS_TEST_WEAKENING]
    scope_issues = [f for f in findings
                    if f.classification in (models.CLASS_UNRELATED_CHANGE,
                                            models.CLASS_SCOPE_EXPANSION)]

    force_reject = bool(policy.get("decisions", {}).get("critical_force_reject", True))
    if force_reject and criticals:
        return models.DECISION_REJECT
    if opts.strict_minimality and scope_issues:
        return models.DECISION_REJECT
    if swap_score < swap_reject:
        return models.DECISION_REJECT

    new_failures = bool(review.verification.new_failures)
    if highs or swaps or weakening or new_failures \
            or generalization_acceptable is False \
            or score >= req_threshold:
        return models.DECISION_REQUIRE_APPROVAL

    if score >= warn_threshold:
        return models.DECISION_WARN
    return models.DECISION_ACCEPT