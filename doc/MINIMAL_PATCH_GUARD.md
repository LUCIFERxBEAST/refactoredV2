# Minimal Patch Guard (MPG): Deep Dive

**Minimal Patch Guard (MPG)** is an automated static and dynamic patch inspection pipeline designed to prevent AI coding assistants (and developers) from submitting lazy, over-fit, or destructive code changes.

---

## The Problem MPG Solves

When an automated agent is instructed to fix a test or refactor a codebase, it may find short-cuts that technically make tests pass while damaging system correctness:
1. **Hardcoding Expected Outputs**: Adding `if input == "test_case": return 42`.
2. **Weakening Tests**: Commenting out assertions, deleting failing tests, or adding `@pytest.mark.skip`.
3. **Suppressing Exceptions**: Wrapping failing code in `try: ... except Exception: pass`.
4. **Scope Expansion**: Modifying unrelated files or changing styling across dozens of unrelated modules.
5. **Logic Bypass**: Returning early before core logic executes.

MPG detects these failure modes before code is merged.

---

## Rule Registry & Finding Classifications

| Rule ID | Classification | Severity | Description |
|---|---|---|---|
| **`MPG-001`** | `unrelated_change` | High / Medium | Files modified that have no AST call-graph connection to the changed symbols. |
| **`MPG-002`** | `logic_bypass` | High | Code paths shortened by >50% or unconditional early returns added before core computations. |
| **`MPG-003`** | `special_case_branch` | Medium / High | Branch conditions matching exact literal constants from test cases (`if val == "exact_literal"`). |
| **`MPG-004`** | `removed_input_dependency` | High | Function arguments are no longer used in the body, returning constant or hardcoded values. |
| **`MPG-005`** | `test_weakening` | High / Critical | Tests deleted, assertion counts reduced, assertions commented out, or `@skip`/`@xfail` markers added. |
| **`MPG-006`** | `exception_suppression` | Medium / High | Bare `except:` or `except Exception:` added with empty bodies (`pass`) or logging only. |
| **`MPG-007`** | `disabled_check` | High | Precondition checks, input validators, or assertions removed from application code. |
| **`MPG-008`** | `scope_expansion` | Medium / High | Exceeding configured limits on files changed (`--max-files-changed`) or lines modified (`--max-lines-changed`). |

---

## Review Pipeline Phases

The `review_patch` orchestrator runs up to 11 analysis phases:

```mermaid
flowchart TD
    P1["Phase 1: Diff & Spans Extraction"] --> P2["Phase 2: Static Heuristics (MPG-003, 004, 006, 007)"]
    P2 --> P3["Phase 3: Scope Analysis (MPG-001, 008)"]
    P3 --> P4["Phase 4: Behavioral Analysis (MPG-002)"]
    P4 --> P5["Phase 5: Test Integrity Verification (MPG-005)"]
    P5 --> P6["Phase 6: Matrix Verification (Baseline vs Candidate)"]
    P6 --> P7["Phase 7: Metamorphic & Differential Probes"]
    P7 --> P8["Phase 8: Metrics Synthesis"]
    P8 --> P9["Phase 9: Scoring & Risk Assessment"]
    P9 --> P10["Phase 10: Suggested Prompt Generation"]
    P10 --> P11["Phase 11: Text / JSON Report Delivery"]
```

### Metamorphic & Edge Probes (`src/minimal_patch_guard/metamorphic.py`)
- For pure, typed Python functions, MPG executes an isolated subprocess test harness across canonical edge inputs:
  - Numeric: `0`, `-1`, `1`, `MAX_INT`, `float("nan")`, `float("inf")`.
  - Collections: `[]`, `[None]`, deeply nested lists, empty dicts.
  - Strings: `""`, whitespace, Unicode strings, special symbols.
- Compares baseline outputs vs candidate outputs (differential fuzzing).
- Flags unexpected behavioral divergence as `uncovered_variation`.

### Verification Matrix (`src/minimal_patch_guard/regression.py`)
- Materializes both the baseline tree (`base_ref`) and the candidate tree into isolated environments.
- Executes tests in stages:
  1. `parse+compile`: Syntax check.
  2. `targeted`: Tests directly matching changed module names.
  3. `full`: Complete project test suite.
- Categorizes test results into:
  - `resolved_failures`: Tests that failed on base but pass on candidate.
  - `new_failures`: Regressions introduced by candidate.
  - `still_failing`: Pre-existing failures untouched by candidate.

---

## Scoring & Decisions

Patches receive an overall **Score** from `0` to `100` (100 = cleanest patch):

$$\text{Score} = 100 - \sum \text{Deductions}$$

### Deduction Weights
- **Critical Finding** (e.g. deleted tests): `-40 points`
- **High Finding** (e.g. hardcoded branch, test weakening): `-25 points`
- **Medium Finding** (e.g. scope expansion, exception swallowing): `-10 points`
- **Low / Info Finding**: `-2 to -5 points`
- **New Test Failures**: `-30 points each`

### Decision Thresholds
| Score | Risk Level | Decision | Meaning |
|---|---|---|---|
| **85 – 100** | `minimal` | **`accept`** | Patch is clean, minimal, and safe to merge. |
| **70 – 84** | `low` | **`warn`** | Minor advisory findings; acceptable under oversight. |
| **45 – 69** | `medium` | **`require_approval`** | Risky findings present; requires human sign-off. |
| **0 – 44** | `high` / `critical` | **`reject`** | Over-fit patch, regressions, or test weakening detected. |
