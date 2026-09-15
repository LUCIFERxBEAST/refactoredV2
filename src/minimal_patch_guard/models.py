"""
models.py — Data model for the Minimal Patch Guard (MPG).

Defines every structure the review pipeline produces and consumes:
  - ChangedSymbol        a top-level symbol whose definition changed
  - Finding              one rule result (MPG-001 .. MPG-008 and friends)
  - VerificationResult   baseline vs candidate test/compile comparison
  - GeneralizationResult output of the safe generalization probes
  - MetricGroup          one named, independent metric bucket
  - PatchReview          the final review returned to CLI / MCP / tests
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------
# Enumerations (kept as plain strings so JSON output stays clean)
# --------------------------------------------------------------------------

# Severity of a single finding.  High/critical findings force a decision.
SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"
SEVERITY_INFO = "info"

# Classifications of risky patch behaviour (Phase 2 lexicon).
CLASS_LEGITIMATE_CONSTANT = "legitimate_constant"
CLASS_SUSPICIOUS_CONSTANT = "suspicious_constant_replacement"
CLASS_TEST_SPECIFIC_HARDCODING = "test_specific_hardcoding"
CLASS_INPUT_DEPENDENCY_REMOVED = "input_dependency_removed"
CLASS_SPECIAL_CASE_BRANCH = "special_case_branch"
CLASS_TEST_WEAKENING = "test_weakening"
CLASS_EXCEPTION_SUPPRESSION = "exception_suppression"
CLASS_UNRELATED_CHANGE = "unrelated_change"
CLASS_SCOPE_EXPANSION = "scope_expansion"
CLASS_LOGIC_BYPASS = "logic_bypass"
CLASS_DISABLED_CHECK = "disabled_check"
CLASS_UNKNOWN = "unknown"

# Decisions the guard can recommend.
DECISION_ACCEPT = "accept"
DECISION_WARN = "warn"
DECISION_REQUIRE_APPROVAL = "require_approval"
DECISION_REJECT = "reject"

# Overall risk levels mapped from the 0-100 score.
RISK_MINIMAL = "minimal"
RISK_MODERATE = "moderate"
RISK_SIGNIFICANT = "significant"
RISK_RISKY = "risky"

# Patch scope classification.
SCOPE_SYMBOL_SPECIFIC = "symbol-specific"
SCOPE_SMALL_FUNCTION = "small-function"
SCOPE_SINGLE_BEHAVIOR = "single-behavior"
SCOPE_DEPENDENCY_ONLY = "dependency-only"
SCOPE_BROAD = "broad"
SCOPE_UNKNOWN = "unknown"

# Verification stage statuses.
VERIFY_NOT_RUN = "not_run"
VERIFY_PASSED = "passed"
VERIFY_FAILED = "failed"
VERIFY_BLOCKED = "blocked"
VERIFY_TIMEOUT = "timeout"
VERIFY_NOT_MEASURED = "not_measured"

# Generalization result statuses.
GEN_NOT_RUN = "not_run"
GEN_PASSED = "passed"
GEN_VARIATION = "uncovered_variation"
GEN_FAILED = "failed"

# Change status of a symbol.
CHANGE_ADDED = "added"
CHANGE_MODIFIED = "modified"
CHANGE_REMOVED = "removed"


# --------------------------------------------------------------------------
# Structures
# --------------------------------------------------------------------------

@dataclass
class ChangedSymbol:
    """A top-level name whose definition changed between base and candidate."""
    name: str
    kind: str                      # function / class / method / constant / import / other
    file: str                      # repo-relative path
    status: str                    # added / modified / removed
    old_excerpt: str = ""
    new_excerpt: str = ""
    old_params: List[str] = field(default_factory=list)
    new_params: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Finding:
    """One rule result.  severity is one of the SEVERITY_* constants."""
    rule_id: str
    title: str
    severity: str
    classification: str
    description: str
    evidence: str = ""
    file: str = ""
    symbol: str = ""
    recommended_action: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
@dataclass
class VerificationRun:
    """A single verification action (parse/compile/targeted/full)."""
    stage: str
    status: str
    detail: str = ""
    returncode: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationResult:
    """Baseline vs candidate observation matrix (Phase 6)."""
    baseline: List[VerificationRun] = field(default_factory=list)
    candidate: List[VerificationRun] = field(default_factory=list)
    baseline_failures: List[str] = field(default_factory=list)
    candidate_failures: List[str] = field(default_factory=list)
    new_failures: List[str] = field(default_factory=list)
    resolved_failures: List[str] = field(default_factory=list)
    still_failing: List[str] = field(default_factory=list)
    tested: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GeneralizationResult:
    """Phase 7 safe-generalization result (edge / metamorphic / differential)."""
    status: str = GEN_NOT_RUN
    run_reason: str = ""
    intended_symbols: List[str] = field(default_factory=list)
    candidates_found: int = 0
    attempted_cases: int = 0
    added_cases: int = 0
    acceptable: bool = False
    holdout_passed: bool = False
    details: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MetricGroup:
    """One named bucket of independent metrics (never merged into a single number)."""
    name: str
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "metrics": self.metrics}


@dataclass
class PatchReview:
    """The complete review returned to the CLI, MCP tools and tests."""
    repo_root: str
    base_ref: str
    scope: str = SCOPE_UNKNOWN
    changed_files: List[str] = field(default_factory=list)
    changed_symbols: List[ChangedSymbol] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    metric_groups: List[MetricGroup] = field(default_factory=list)
    verification: VerificationResult = field(default_factory=VerificationResult)
    generalization: GeneralizationResult = field(default_factory=GeneralizationResult)
    score: int = 0
    risk_level: str = RISK_MINIMAL
    decision: str = DECISION_ACCEPT
    summary: str = ""
    suggested_prompt: str = ""
    policy: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repo_root": self.repo_root,
            "base_ref": self.base_ref,
            "scope": self.scope,
            "changed_files": self.changed_files,
            "changed_symbols": [s.to_dict() for s in self.changed_symbols],
            "findings": [f.to_dict() for f in self.findings],
            "metric_groups": [g.to_dict() for g in self.metric_groups],
            "verification": self.verification.to_dict(),
            "generalization": self.generalization.to_dict(),
            "score": self.score,
            "risk_level": self.risk_level,
            "decision": self.decision,
            "summary": self.summary,
            "suggested_prompt": self.suggested_prompt,
            "policy": self.policy,
        }


@dataclass
class ReviewOptions:
    """Flags accepted by the CLI / MCP tools.  None means 'use policy default'."""
    repo_root: str
    base_ref: str = "HEAD"
    test_cmd: Optional[str] = None
    strict_minimality: Optional[bool] = None
    max_files_changed: Optional[int] = None
    max_lines_changed: Optional[int] = None
    require_approval: Optional[bool] = None
    run_generalization: Optional[bool] = None
    skip_generalization: Optional[bool] = None
    operation: Optional[str] = None
    output_format: str = "text"