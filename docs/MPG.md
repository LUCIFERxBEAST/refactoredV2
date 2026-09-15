# Minimal Patch Guard (MPG) — Documentation

> `src/minimal_patch_guard/` · CLI: `review-patch` · MCP: `refactor_guard_review_patch`

MPG reviews **any patch** — yours or another AI agent's — against a baseline and
answers one question that ordinary test runs can't: *"is this patch actually a
real fix, or is it cheating its own tests?"*

A test suite passes when `test_add()` gives `add(2,3)` back `5`. MPG is what
catches that `add()` was rewritten as `if a == 2 and b == 3: return 5` — a
hardcoded special case that makes the tests green but fixes nothing in general.

---

## 1. What it detects

| Signal | Meaning | Classes |
|---|---|---|
| **Hardcoded outputs** | Function now returns a constant / special-cases exact test inputs | `suspicious_constant_replacement`, `test_specific_hardcoding`, `special_case_branch` |
| **Input dependency removed** | Parameters or lookups that used to drive the result are gone | `input_dependency_removed` |
| **Test weakening** | Test deleted, skipped/xfailed, assertion removed or commented out, expected value changed | `test_weakening` |
| **Exception suppression** | `try/except` that swallows the failure the code should handle | `exception_suppression` |
| **Logic bypass** | Returns early without doing the advertised work | `logic_bypass` |
| **Disabled checks** | `if 0:`, commented-out asserts in source | `disabled_check` |
| **Scope creep** | Files/lines changed beyond the declared operation, unrelated files, tests changed alongside a rename | `unrelated_change`, `scope_expansion` |

Every signal becomes a **finding**. Findings feed a scoring model, and the score
maps onto a guard decision.

---

## 2. Decisions

| Decision | Meaning |
|---|---|
| `accept` | No risky patch characteristics detected |
| `warn` | Minor signals; safe to proceed but worth a look |
| `require_approval` | Borderline or high-impact — a human must approve |
| `reject` | Critical/hard signals or score below the reject threshold |

Decisions map to CLI **exit codes**: `0` = accept/warn, `1` = require approval,
`2` = reject / usage error. Risk levels (`minimal`, `moderate`, `significant`,
`risky`) and the 0–100 score are reported alongside.

---

## 3. Pipeline

```text
base ❯────┐
---

## 4. Findings reference (rule IDs)

| Rule | Title | Severity | Classification |
|---|---|---|---|
| `MPG-001` | Constant replacement / output-only result | varies | `suspicious_constant_replacement` |
| `MPG-002` | Input dependency removed | high | `input_dependency_removed` |
| `MPG-003` | Special-case / test-specific hardcoding branch | high | `special_case_branch` / `test_specific_hardcoding` |
| `MPG-004` | Unrelated change present · scope expansion · test changed during rename | medium/low | `unrelated_change` / `scope_expansion` |
| `MPG-005` | Deleted test · skipped/xfail · assertion removed/fewer/commented-out · expected value changed | high/medium | `test_weakening` |
| `MPG-006` | Exception suppression (`try/except` swallow) | medium | `exception_suppression` |
| `MPG-007` | Logic bypass / skipped implementation | high | `logic_bypass` |
| `MPG-008` | Disabled checks (`if 0:`, commented-out asserts) | medium | `disabled_check` |
| `MPG-900` | JS/TS symbol change — manual review advised | low | `unknown` |
| `MPG-904` | File changed outside the failing dependency path | low | `unrelated_change` |

> All rules are **heuristic**. They produce findings that feed the score and
> decision — not hard guarantees. A `legitimate_constant` classification exists
> so genuinely constant values are not over-flagged.

---

## 5. Scoring model

Score is **not** a single blended "quality number" — it is derived from
independent metric buckets (`size_metrics`, `scope_metrics`, `control_flow_metrics`,
`behavior_metrics`, `input_dependency_metrics`, `complexity_metrics`,
`regression_metrics`, `coverage_metrics`, `verification_completeness_metrics`).

Default weights (policy `weights`):

| Weight | Value | Applies to |
|---|---|---|
| `swap` | 0.37 | behavior swap / output-only |
| `scope` | 0.20 | scope expansion |
| `output_only` | 0.15 | output-only changes |
| `risk` | 0.12 | severity-weighted risk |
| `rewards` | 0.11 | desired changes, clean verification |
| `penalty_cap` | 0.05 | caps per-symbol penalties |

Default decision thresholds (policy `decisions`):

| Threshold | Value |
|---|---|
| `require_approval_threshold` | 45 |
| `warn_threshold` | 20 |
| `swap_reject_threshold` | 35 |
| `critical_force_reject` | true |
          ▼
    compute_patch ──> diff base vs candidate (git ref or base folder)
          │
          ▼
    changed symbols + per-file line stats
---

## 6. CLI reference

```bash
python -m src.main review-patch \
  --repo-root /path/to/repo \
  --base-ref HEAD \                        # git ref, or a folder with the base snapshot
  --test-cmd "pytest -q" \                 # run against BOTH baseline and candidate
  --max-files-changed 10 \                 # cap before scope-expansion flag
  --max-lines-changed 200 \
  --operation rename \                     # rename | extract-function | move-symbol
  --run-generalization \                   # force generalization probes
  --skip-generalization \                  # never auto-trigger them
  --strict-minimality \                    # any unrelated/expanded change -> reject
  --require-approval \                     # force 'require approval' where borderline
  --output-format json                     # text (default) or json
```

| Flag | Default | Notes |
|---|---|---|
| `--repo-root PATH` | required | Repo to review |
| `--base-ref REF\|DIR` | `HEAD` | Diff baseline; folder = deterministic, git-free |
| `--test-cmd CMD` | policy default | `""` skips verification entirely |
| `--strict-minimality` | off | policy `strict_minimality_only` |
| `--max-files-changed N` | policy default | policy `max_files_changed` |
| `--max-lines-changed N` | policy default | policy `max_lines_changed` |
| `--require-approval` | off | policy `require_approval` |
| `--run-generalization` | off | policy `run_generalization` |
| `--skip-generalization` | off | policy `skip_generalization` |
| `--operation OP` | none | footprint check for the declared op |
| `--output-format text\|json` | `text` | human text or structured JSON |

Exit codes: `0` accept/warn · `1` require approval · `2` reject / usage error.

---

## 7. Python API

```python
from src.minimal_patch_guard import review_patch
from src.minimal_patch_guard import models, reporter

review = review_patch(
    repo_root="/path/to/repo",
    base_ref="HEAD",                # git ref OR base-snapshot directory
    test_cmd="pytest -q",           # "" skips verification
    strict_minimality=None,         # None = use policy default
    max_files_changed=None,
    max_lines_changed=None,
    require_approval=None,
    run_generalization=None,
    skip_generalization=None,
    operation=None,                 # "rename" | "extract-function" | "move-symbol"
    output_format="text",           # only affects CLI rendering; API gets PatchReview
    policy=None,                    # optional dict override
)
print(review.score, review.risk_level, review.decision)
for f in review.findings:
    print(f.rule_id, f.severity, f.classification, "—", f.title)
print(reporter.render_json(review))
```

### Public types (`models`)

| Type | Fields (abridged) |
|---|---|
| `PatchReview` | `repo_root`, `base_ref`, `scope`, `changed_files`, `changed_symbols`, `findings`, `metric_groups`, `verification`, `generalization`, `score`, `risk_level`, `decision`, `summary`, `suggested_prompt`, `policy` |
| `Finding` | `rule_id`, `title`, `severity`, `classification`, `description`, `evidence`, `file`, `symbol`, `recommended_action` |
| `ChangedSymbol` | `name`, `kind`, `file`, `status` (added/modified/removed), `old_excerpt`, `new_excerpt`, `old_params`, `new_params` |
| `VerificationResult` | `baseline`, `candidate`, `new_failures`, `resolved_failures`, `still_failing`, `tested` |
| `VerificationRun` | `stage` (parse+compile/targeted/full), `status`, `detail`, `returncode` |
| `GeneralizationResult` | `status`, `run_reason`, `intended_symbols`, `attempted_cases`, `added_cases`, `acceptable`, `holdout_passed`, `details` |
| `MetricGroup` | `name`, `metrics` |
| `ReviewOptions` | mirror of `review_patch()` flags; `None` = policy default |

Status/decision constants are plain strings (JSON-clean): `SEVERITY_*`,
`CLASS_*`, `DECISION_*`, `RISK_*`, `SCOPE_*`, `VERIFY_*`, `GEN_*`, `CHANGE_*`.

---

## 8. MCP tool

An agent (Claude Code, Cursor, Cline, Claude Desktop) calls
`refactor_guard_review_patch` and receives the full review as structured JSON:

```jsonc
{
  "repo_root": "/path/to/repo",
  "base_ref": "HEAD",
  "test_cmd": "pytest -q",
  "strict_minimality": false,
  "max_files_changed": 10,
  "max_lines_changed": 200,
  "require_approval": false,
  "run_generalization": false,
  "operation": "rename"
}
```

Response shape (abridged):

```json
{
  "score": 42,
  "risk_level": "significant",
  "decision": "require_approval",
  "changed_files": ["pkg/calc.py"],
  "changed_symbols": [{"name": "add", "kind": "function", "status": "modified"}],
  "findings": [{"rule_id": "MPG-003", "severity": "high",
                "classification": "test_specific_hardcoding", "title": "…",
                "evidence": "if a == 2 and b == 3: return 5"}],
  "verification": {"baseline": [], "candidate": [], "new_failures": [], "tested": false},
  "generalization": {"status": "not_run", "run_reason": "…"},
  "suggested_prompt": "An automated Minimal Patch Guard review …"
}
```

The `suggested_prompt` field is copy-paste instructions telling the agent exactly
what to fix, in what order — so the guard's result drops straight back into the
agent's edit loop.
          │
          ▼
 Phase 2  static checks        MPG-001/002/003/006/007/008  (AST + text heuristics)
 Phase 3  scope & dependency   MPG-004 (unrelated change, scope expansion, operation footprint)
 Phase 4  behavior metrics     control-flow / input-dependency / behavior buckets
 Phase 5  test integrity       MPG-005 (deleted/skipped/weakened tests)
 Phase 6  verification         baseline vs candidate: parse → compile → targeted → full
          └─ dependency checks MPG-904 (files changed outside the failing dependency path)
 Phase 7  generalization       edge/metamorphic/differential probes on changed pure functions
          │
          ▼
    score + decision ──> PatchReview ──> text render / JSON / suggested agent prompt
```

Phases 6–7 are the parts ordinary test runners never do:

- **Verification matrix (Phase 6)** — the target repo's tests are run against the
  **baseline** *and* the **candidate**. A patch that "fixes" a failing test by
  rewriting the test itself shows up as `new_failures` vs `resolved_failures` /
  `still_failing`. Test-command `""` skips verification.
- **Generalization probes (Phase 7)** — for changed **pure, typed functions**,
  MPG synthesizes edge cases, runs metamorphic-differential compares between the
  baseline and candidate, and checks the candidate's declared new cases plus a
  **holdout** set. A `5`-only fix fails the holdout; a general fix passes.

Generalization auto-triggers when a hardcoding signal exists (`suspicious_constant`,
`test_specific_hardcoding`, `special_case_branch`); pass `--run-generalization` to
force it, `--skip-generalization` to suppress the auto-trigger.
---

## 9. Policy configuration

Optional per-repo file `.refactor-guard/policy.toml` at the repo root (or CWD).
An optional `[minimal-patch-guard]` table is honoured; invalid/unreadable files
**degrade to safe defaults** instead of raising.

```toml
[minimal-patch-guard]
max_runtime_seconds = 120
test_cmd = "pytest -q"
strict_minimality_only = false
require_approval = true
run_generalization = false
skip_generalization = true
max_files_changed = 10
max_lines_changed = 200

[weights]
swap = 0.37
scope = 0.20
output_only = 0.15
risk = 0.12
rewards = 0.11
penalty_cap = 0.05

[decisions]
require_approval_threshold = 45
warn_threshold = 20
swap_reject_threshold = 35
critical_force_reject = true
```

### Environment variables (opt-in)

| Var | Effect |
|---|---|
| `MPG_TEST_CMD` | override the default verification command |
| `MPG_VERIFICATION_STAGE` | limit default verification: `parse` \| `compile` \| `full` |
| `MPG_GENERALIZATION_MODE` | force probes `on` / `off` |
| `MPG_STRICT_MINIMALITY_ONLY` | any unrelated/expansion change → reject |
| `MPG_CONDITIONALLY_ALLOWED_VARS` | comma-separated module constants allowed to drive behaviour |

---

## 10. Package layout

| File | Role |
|---|---|
| `__init__.py` | `review_patch()` pipeline orchestration (phases 2–7, metrics) |
| `models.py` | Data model + constants (`PatchReview`, `Finding`, …) |
| `policy.py` | `policy.toml` loading, env vars, `resolve_options()` defaults |
| `patch_parser.py` | `compute_patch()`, `diff_stats()`, `extract_changed_symbols()` |
| `static_checks.py` | MPG-001/002/003/006/007/008 (AST/text heuristics) |
| `scope_checks.py` | MPG-004 scope, size limits, operation footprints |
| `dependency_checks.py` | MPG-904 dependency-path scope (post-verification) |
| `behavior_checks.py` | Control-flow / input-dependency / behavior metrics |
| `test_integrity.py` | MPG-005 test weakening |
| `regression.py` | Phase 6 baseline-vs-candidate verification matrix |
| `metamorphic.py` | Phase 7 edge/metamorphic/differential generalization probes |
| `scoring.py` | Weights → 0–100 score → decision |
| `reporter.py` | text / JSON render + `suggested_prompt` for agents |
| `ast_utils.py` | Shared Python AST walking helpers |
| `_ts_subprocess.py` | Tree-sitter parse helper for JS/TS via node |

---

## 11. Recipes

### Review the current uncommitted change vs HEAD

```bash
cd /path/to/repo
python -m src.main review-patch --repo-root . --base-ref HEAD --test-cmd "pytest -q"
```

### Gate a merge / CI step

```bash
python -m src.main review-patch --repo-root . --test-cmd "pytest -q" \
  --run-generalization --strict-minimality --output-format json \
  || echo "MPG says: fix the patch before shipping"
```

### Provide a base snapshot instead of git (deterministic, git-free)

```bash
python -m src.main review-patch --repo-root /path/to/candidate \
  --base-ref /path/to/base_snapshot --test-cmd "pytest -q"
```

### Call from Python and let an agent react

```python
from src.minimal_patch_guard import review_patch
r = review_patch(repo_root=".", test_cmd="pytest -q", run_generalization=True)
if r.decision == "reject":
    print(r.suggested_prompt)   # agent-friendly fix instructions
```