"""
policy.py — Loading and safe-degradation of the MPG policy (.refactor-guard/policy.toml).

Only the environment variables documented below are honoured.  Unknown keys and
a missing policy file degrade to safe defaults rather than raising.

Env vars (documented, opt-in controls):
  MPG_TEST_CMD               override the default verification test command
  MPG_VERIFICATION_STAGE     limit default verification: parse | compile | full
  MPG_GENERALIZATION_MODE    force on/off the safe-generalization probes
  MPG_STRICT_MINIMALITY_ONLY any unrelated/expansion change -> reject
  MPG_CONDITIONALLY_ALLOWED_VARS module-level constant names that may drive
                             conditionally-allowed behaviour (comma separated)
"""

from __future__ import annotations

import os
import tomllib
from typing import Any, Dict, Optional

from . import models

_POLICY_RELPATH = os.path.join(".refactor-guard", "policy.toml")

# Defaults mirror the specification's safe defaults.
_DEFAULT_POLICY: Dict[str, Any] = {
    "max_runtime_seconds": 120,
    "test_cmd": "pytest -q",
    "strict_minimality_only": False,
    "require_approval": True,
    "run_generalization": False,
    "skip_generalization": True,
    "max_files_changed": 10,
    "max_lines_changed": 200,
    "operation": None,
    "weights": {
        "swap": 0.37,
        "scope": 0.20,
        "output_only": 0.15,
        "risk": 0.12,
        "rewards": 0.11,
        "penalty_cap": 0.05,
    },
    "decisions": {
        "require_approval_threshold": 45,
        "warn_threshold": 20,
        "swap_reject_threshold": 35,
        "critical_force_reject": True,
    },
}

_ALLOWED_ENV_VARS = (
    "MPG_TEST_CMD",
    "MPG_VERIFICATION_STAGE",
    "MPG_GENERALIZATION_MODE",
    "MPG_STRICT_MINIMALITY_ONLY",
    "MPG_CONDITIONALLY_ALLOWED_VARS",
)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Merge override into base (nested dicts merged recursively)."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_policy(repo_root: Optional[str] = None) -> Dict[str, Any]:
    """Load .refactor-guard/policy.toml from repo_root (or CWD) over defaults."""
    policy = _deep_merge({}, _DEFAULT_POLICY)
    candidates = []
    if repo_root:
        candidates.append(os.path.join(repo_root, _POLICY_RELPATH))
    candidates.append(_POLICY_RELPATH)

    for path in candidates:
        if path and os.path.isfile(path):
            try:
                with open(path, "rb") as fh:
                    data = tomllib.load(fh)
            except Exception:
                continue  # unreadable/invalid policy -> safe defaults
            table = data.get("minimal-patch-guard", data)
            if isinstance(table, dict):
                _deep_merge(policy, table)
            break

    # Environment overrides (only the documented vars are read).
    env = os.environ
    if env.get("MPG_TEST_CMD", "").strip():
        policy["test_cmd"] = env["MPG_TEST_CMD"].strip()
    stage = env.get("MPG_VERIFICATION_STAGE", "").strip().lower()
    if stage in ("parse", "compile", "full"):
        policy["_verification_stage"] = stage
    gen_mode = env.get("MPG_GENERALIZATION_MODE", "").strip().lower()
    if gen_mode in ("on", "off"):
        policy["run_generalization"] = gen_mode == "on"
        policy["skip_generalization"] = gen_mode != "on"
    strict = env.get("MPG_STRICT_MINIMALITY_ONLY", "").strip().lower()
    if strict in ("1", "true", "yes", "on"):
        policy["strict_minimality_only"] = True

    allowed = env.get("MPG_CONDITIONALLY_ALLOWED_VARS", "").strip()
    policy["_conditionally_allowed_vars"] = [
        v.strip() for v in allowed.split(",") if v.strip()
    ]
    return policy


def resolve_options(policy: Dict[str, Any], opts: models.ReviewOptions) -> models.ReviewOptions:
    """Fill policy defaults into the subset of options the caller left as None."""
    if opts.test_cmd is None:
        opts.test_cmd = str(policy.get("test_cmd", "pytest -q"))
    # Note: an explicit "" test_cmd means "skip verification entirely".
    opts.strict_minimality = (
        opts.strict_minimality
        if opts.strict_minimality is not None
        else bool(policy.get("strict_minimality_only", False))
    )
    opts.max_files_changed = (
        opts.max_files_changed
        if opts.max_files_changed is not None
        else int(policy.get("max_files_changed", 10))
    )
    opts.max_lines_changed = (
        opts.max_lines_changed
        if opts.max_lines_changed is not None
        else int(policy.get("max_lines_changed", 200))
    )
    opts.require_approval = (
        opts.require_approval
        if opts.require_approval is not None
        else bool(policy.get("require_approval", True))
    )
    opts.run_generalization = (
        opts.run_generalization
        if opts.run_generalization is not None
        else bool(policy.get("run_generalization", False))
    )
    opts.skip_generalization = (
        opts.skip_generalization
        if opts.skip_generalization is not None
        else bool(policy.get("skip_generalization", True))
    )
    opts.operation = opts.operation or (policy.get("operation") or None)
    return opts