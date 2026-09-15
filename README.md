# Refactor Guard

**Samsung PRISM Hackathon — Agentic Code Intelligence**

An autonomous safety layer for code refactoring and AI-generated modifications: it doesn't just apply code transformations, it maps transitive blast radius before touching disk, snapshots the repository, verifies changes against real-world test suites, self-heals with AI root-cause diagnostics, and — unlike standard refactoring utilities — catches an AI agent's candidate patch cheating its own tests or expanding scope before it ever reaches production.

Built to operate seamlessly across two modalities:
1. **Interactive CLI**: For developers refactoring code, inspecting history, and verifying diffs directly from their terminal.
2. **Model Context Protocol (MCP) Server**: Directly invokable by AI coding assistants (Claude Code, Cursor, Cline, Windsurf, Antigravity, Claude Desktop) — embedding safety verification directly inside the agent's edit loop rather than as an afterthought run after the damage is done.

> 📚 **Detailed Documentation Manuals**:
> - [Documentation Index](doc/README.md)
> - [System Architecture & Pipeline](doc/ARCHITECTURE.md)
> - [CLI Reference Manual](doc/CLI_REFERENCE.md)
> - [Minimal Patch Guard (MPG) Deep Dive](doc/MINIMAL_PATCH_GUARD.md)
> - [MCP Agentic Integration Guide](doc/MCP_INTEGRATION_GUIDE.md)
> - [Snapshot Engine & Audit Ledger](doc/SNAPSHOT_AND_LEDGER.md)

---

## Why This is Agentic, Not Just a Refactor Tool

| Dimension | Conventional Refactor Tools | Refactor Guard |
|---|---|---|
| **Pre-Change Visibility** | Blind text find-and-replace; hopes tests still pass | Builds a Tree-sitter AST dependency graph + `networkx` blast radius, flags dynamic-risk string usages, and surfaces repeat-offender files before touching disk |
| **Failure Recovery** | Leaves the working directory broken with dirty diffs | Zero-copy Git throwaway snapshot with Windows read-only resilience; automatically rolls back cleanly on test failure |
| **Fault Resolution** | Aborts with error traces on test failure | Queries Google Gemini for automated root-cause diagnosis, verifies suggestions with anti-hardcode guards, and executes bounded self-healing |
| **Patch Trust Model** | Assumes candidate patches or agent edits are benign | **Minimal Patch Guard (MPG)**: Analyzes diffs against baseline to detect hardcoded values, bypassed tests, weakened assertions, and scope creep |
| **Generalization & Probes** | Relies solely on existing static test cases | Executes metamorphic & edge-case probes against changed pure functions in isolated subprocesses to confirm fixes generalize |
| **Institutional Memory** | Each invocation runs stateless from scratch | Persistent audit ledger (`.refactor-guard/ledger.jsonl`) records all outcomes, highlighting repeat-offender dynamic files from past rollbacks |
| **Agentic Loop Integration** | Human-only terminal commands after edits are made | 16 native FastMCP tools and safety prompts callable by AI coding agents mid-task, ensuring the safety gate lives inside the agent's inner loop |

---

## Core Capabilities

- **Guarded Multi-Language Refactoring (`rename`, `extract-function`, `move-symbol`)**: Multi-language Tree-sitter AST parsing across Python, JavaScript, and TypeScript, binary-mode byte span replacements, and automated MAP → WARN → SNAPSHOT → ACT → VERIFY lifecycle.
- **Transitive Blast-Radius & Dynamic Warning**: `networkx` call graphs map dependencies, flagging un-rewritable runtime references (e.g., `getattr()`, dictionary bracket access) and historical repeat offenders before making changes.
- **Scalable Dual-Strategy Snapshots**: Fast, zero-copy Git throwaway refs (`refs/refactor-guard/*`) using isolated index files, with full Windows read-only git object resilience (`0o444`) and directory-copy fallback.
- **Self-Healing with AI Guardrails**: Automated Gemini AI failure diagnosis with anti-hardcode heuristic detection and single bounded retry before rolling back.
- **Minimal Patch Guard (`review-patch`)**: Automated patch quality gate that checks candidate diffs for hardcoding, test tampering, deleted assertions, logic bypasses, and scope explosion. Evaluates generalization via metamorphic probes. → [Full MPG Documentation](doc/MINIMAL_PATCH_GUARD.md)
- **Persistent Refactor Ledger (`history`)**: Append-only audit trail (`.refactor-guard/ledger.jsonl`) tracking every operation, parameter, timestamp, and rollback, with CLI querying and pre-flight advisory warnings.
- **Model Context Protocol (MCP) Server**: Complete suite of 16 FastMCP tools allowing coding assistants (Claude Desktop, Cursor, Cline, Windsurf, Antigravity) to safely refactor and verify patches autonomously.

---

## How it works (5 steps)

Every refactoring operation runs through an automated safety harness orchestrated by `src/main.py`:

| Step | Name | What happens |
|---|---|---|
| 1 | **MAP** | Scans the repo for references with Tree-sitter, split into _static_ (calls, imports, definitions, member access) and _dynamic-risk_ (name in a string). Computes transitive blast radius via `networkx`. Surfaces prior successful refactor runs (if any). |
| 2 | **WARN** | Prints dynamic-risk files **before anything changes** so you know what cannot be safely auto-rewritten. Surfaces advisory prior failure history and tags repeat-offender dynamic-risk files. |
| 3 | **SNAPSHOT** | Zero-copy Git throwaway ref snapshot (`refs/refactor-guard/*`) using an isolated index, or directory copy fallback excluding large directories (`node_modules`, `venv`, etc.). Fully resilient to Windows read-only Git objects. |
| 4 | **ACT** | Applies the edit (Tree-sitter AST byte-range span rename in binary mode, preserving comments, docstrings, and string literals without offset drift; AST block extraction; symbol move with cross-module import rewrites). |
| 5 | **VERIFY** | Runs the target repo's test suite. If tests pass → keep change + log success to ledger. If tests fail → optional Gemini AI root-cause diagnosis + bounded retry → still failing → **auto-rollback** from snapshot and log failure to ledger. |

---

## Supported Languages & Operations

Refactor Guard enforces language support per operation. While symbol renaming operates across multi-language codebases using Tree-sitter AST spans, AST-heavy transformations (`extract-function` and `move-symbol`) target Python with strict fail-fast validation (exit code 2).

| Operation | Python (`.py`) | JavaScript (`.js`) | TypeScript (`.ts`) | Details |
|---|:---:|:---:|:---:|---|
| **`rename`** | ✅ Supported | ✅ Supported | ✅ Supported | Multi-language AST byte-range span replacement and bracket-access detection via Tree-sitter |
| **`extract-function`** | ✅ Supported | ❌ Excluded | ❌ Excluded | Python AST variable flow analysis (free vars → params, used assigns → returns); exits code 2 on others |
| **`move-symbol`** | ✅ Supported | ❌ Excluded | ❌ Excluded | Python AST module analysis, cross-file import rewrites, and target file creation; exits code 2 on others |
| **`review-patch`** | ✅ Full MPG | ✅ Static + Scope | ✅ Static + Scope | 11-phase Minimal Patch Guard review, test integrity, and metamorphic pure function probes |

### Grammar & AST Details for `rename`:

| Extension | Grammar | Static node types | Dynamic-risk node types |
|---|---|---|---|
| `.py` | tree-sitter-python | `identifier` | `string_content` |
| `.js` | tree-sitter-javascript | `identifier`, `property_identifier`, `shorthand_property_identifier` | `string_fragment` |
| `.ts` | tree-sitter-javascript | same as `.js` | `string_fragment` |

For example, `getattr(mathutils, "compute_total")` (Python) and `mathutils["computeTotal"](items)` (JavaScript) are both flagged as **dynamic-risk**: the name is embedded in a string literal and a plain find-and-replace could never safely update it without runtime evaluation.

- **AST Byte-Range Span Replacement**: Files are parsed via Tree-sitter, read and rewritten in binary mode (`rb`/`wb`), replacing only verified AST static identifier byte offsets. Comments, docstrings, string literals, and surrounding UTF-8/emojis are preserved byte-for-byte.
- **Span Validation & Fallback**: Target spans are asserted against `old_symbol` bytes before replacement. If Tree-sitter encounters a syntax error (`root_node.has_error`), it logs a warning and falls back to word-boundary regex for that file only.

---

## Snapshot & Rollback Architecture

Refactor Guard provides a scalable dual-strategy backup system in `src/snapshot.py`:

1. **Git Repositories (Fast Zero-Copy Snapshot)**:
   - **Isolated Index**: All staging and tree operations strictly use a separate temporary index file via `GIT_INDEX_FILE`. The developer's real `.git/index` is **never modified**.
   - **Seeded Index (Subdirectory Isolation)**: When `repo_root` is a subdirectory within a git repository, the temporary index is pre-populated via `git read-tree HEAD` before staging `repo_root`. This ensures files outside `repo_root` are preserved byte-for-byte.
   - **Pathspec-Scoped Restore**: Rollback is strictly restricted to `repo_root` via `git checkout-index -f -z --stdin`, and newly created untracked files are cleaned up without touching files outside `repo_root`.
   - **Zero-Commit Repositories**: Freshly `git init`'d repositories with no commits yet are detected via `git rev-parse --verify HEAD`; parent flag (`-p HEAD`) and `read-tree` are omitted gracefully.
   - **Gitignored Source File Fallback**: If `repo_root` contains gitignored `.py`, `.js`, or `.ts` source files that git would not track, Refactor Guard automatically falls back to a directory copy snapshot so uncommitted code is never lost.
   - **Windows Read-Only Resilience**: Loose git object files in `.git/objects/` are stored with read-only permissions (`0o444`). Refactor Guard implements `_force_remove_tree` and `_force_remove_file` with `stat.S_IWRITE` clearing and exponential-backoff retries to avoid `PermissionError` (WinError 5) during restore or cleanup.

2. **Non-Git Repositories (Directory Copy Fallback)**:
   - Uses `shutil.copytree` to back up files into a temporary directory.
   - Automatically excludes large, non-source directories (`node_modules`, `venv`, `.venv`, `env`, `__pycache__`, `.pytest_cache`, `.mypy_cache`) to minimize snapshot overhead and disk bloat.

3. **Pipeline Transparency**:
   - The dual-strategy snapshot mechanism is completely transparent. Public signatures (`create_snapshot`, `restore_snapshot`, `cleanup_snapshot`) remain identical regardless of whether Git or directory copy is selected.

---

## Minimal Patch Guard (MPG) (`review-patch`)

The **Minimal Patch Guard** is an automated review pipeline that detects over-fit, lazy, or dangerous patches produced by AI coding agents or human contributors before they are merged.

### What MPG Detects:
- **Hard-coded outputs & test-specific branches** (`MPG-003`): `if input == "exact_test_case": return expected`.
- **Test weakening & deletion** (`MPG-005`): Tests marked `skip`/`xfail`, removed assertions, deleted test functions, or assertions commented out.
- **Removed input dependencies** (`MPG-004`): Functions no longer using their arguments, returning dummy constants.
- **Exception suppression & logic bypass** (`MPG-002`, `MPG-006`): Blind `try/except: pass` blocks, early returns bypassing core logic.
- **Scope expansion & unrelated changes** (`MPG-001`, `MPG-008`): Modifying files or symbols unrelated to the declared operation.
- **Regression verification**: Compares baseline vs candidate test matrices (distinguishing new failures from pre-existing ones).
- **Metamorphic & differential probes**: Evaluates changed pure functions against canonical edge cases in an isolated subprocess.

### Patch Review CLI Options:
```bash
# Review current working tree against git HEAD with test verification
python -m src.main review-patch --repo-root /path/to/project

# Fast pre-commit check (skipping test suite execution)
python -m src.main review-patch --repo-root /path/to/project --test-cmd ""

# Review against a specific git ref or base directory (without git)
python -m src.main review-patch --repo-root /path/to/project --base-ref HEAD~1
python -m src.main review-patch --repo-root /path/to/cand --base-ref /path/to/base

# Enforce strict scope minimality and maximum file/line caps
python -m src.main review-patch --repo-root /path/to/project \
  --strict-minimality --max-files-changed 5 --max-lines-changed 100

# Run generalization probes across changed pure functions
python -m src.main review-patch --repo-root /path/to/project --run-generalization

# Output structured JSON for automated pipelines & agents
python -m src.main review-patch --repo-root /path/to/project --output-format json
```

### Exit Codes:
- `0`: Patch **Accepted** or **Warning** (clean or minor advisory findings).
- `1`: **Requires Approval** (risky findings detected or new regressions found).
- `2`: **Rejected** (critical findings, test weakening, or usage error).

---

## Refactor Ledger & History (`.refactor-guard/ledger.jsonl`)

Refactor Guard maintains a persistent audit trail of every completed refactor operation in `<repo_root>/.refactor-guard/ledger.jsonl`:

- **Storage & Isolation**: Stored as newline-delimited JSON (JSONL). The `.refactor-guard/` directory is automatically gitignored and excluded from snapshots.
- **Fail-Soft Persistence**: Writes occur strictly after rollback/cleanup completes. Any ledger I/O errors are caught fail-soft and never disrupt or alter the refactor's exit code.
- **Pre-Flight Advisory Surfacing (STEP 1 & STEP 2)**:
  - **STEP 1 (MAP)**: Surfaces prior successful operations concisely (`Note: this symbol was previously renamed successfully on <date>.`).
  - **STEP 2 (WARN)**: If prior rolled-back attempts exist for the same operation and symbol, prints a formatted `PRIOR HISTORY` block with previous failure counts, dates, and implicated dynamic-risk files.
  - **Repeat Offender Highlighting**: Any currently flagged dynamic-risk file that contributed to a prior rollback is tagged as a `(REPEAT OFFENDER — implicated in prior rollback)`.
  - **Advisory Only**: Prior history warnings never abort, block, prompt, or alter execution flow or exit codes.

### Inspect History via CLI (`history`):
```bash
# View all refactor history for a repository
python -m src.main history --repo-root /path/to/project

# Filter history for a specific symbol
python -m src.main history --repo-root /path/to/project --symbol compute_total

# Show only the last 5 records
python -m src.main history --repo-root /path/to/project --limit 5

# Output records as raw JSON for programmatic tools
python -m src.main history --repo-root /path/to/project --json
```

---

## Setup & Installation

```bash
cd refactor-guard

# (Recommended) create a virtual environment
python -m venv venv
source venv/bin/activate   # Linux/Mac
venv\Scripts\activate      # Windows

# Install dependencies (pytest + tree-sitter + grammars + FastMCP)
pip install -r requirements.txt

# Node.js is only needed for the JavaScript sample/demo
node --version             # >= 20 recommended
```

### Environment Variables (Optional Self-Heal AI)

Refactor Guard can optionally provide AI-driven root-cause diagnoses for test failures using Google Gemini before executing an auto-rollback:

```bash
# Optional: API key for Gemini AI failure diagnosis
export GEMINI_API_KEY="your-gemini-api-key"

# Optional: Gemini model override (defaults to gemini-3.6-flash if unset)
export GEMINI_MODEL="gemini-3.6-flash"
```

- **Graceful Fallback**: If `GEMINI_API_KEY` is missing, or if the configured `GEMINI_MODEL` is unavailable or deprecated (404), Refactor Guard logs a clear warning, skips AI diagnosis and retry, and proceeds immediately to a safe rollback.
- **Anti-Hardcode Guard**: Responses are scanned for hardcoding patterns (e.g. `just return`, `hardcode`, `special case`), displaying a warning (`⚠ This suggested fix may be overly specific...`) when detected.
- **Bounded Retry**: Re-runs the test suite exactly once. If tests pass, change is kept; if tests still fail, auto-rollback is executed.

---

## Usage

### Rename a symbol (Python, JavaScript, TypeScript)

```bash
python -m src.main rename \
  --repo-root /path/to/your/project \
  --symbol old_function_name \
  --to new_function_name \
  --test-cmd "pytest -q"                        # Python
  # --test-cmd "node --test tests/*.test.js"    # JavaScript
  # --dry-run                                  # Optional: simulate without changes
```

### Extract a block into a new function (Python)

```bash
python -m src.main extract-function \
  --repo-root /path/to/project \
  --file pkg/mathutils.py \
  --start-line 30 --end-line 31 \
  --name _build_summary_and_count \
  --test-cmd "pytest -q" \
  # --dry-run                                  # Optional: simulate without changes
```

The tool derives the new function automatically:
- **parameters** = free variables used but not defined in the block (excluding builtins and module-level names);
- **return values** = variables assigned in the block that the enclosing function still uses afterwards (returned as a tuple).

So lines 30-31 of `describe_items` become:
```python
def _build_summary_and_count(items):
    summary = build_report(items)
    count = compute_total(items)
    return summary, count

def describe_items(items):
    summary, count = _build_summary_and_count(items)
    return f"{summary} | counted: {count}"
```

### Move a definition to another file (Python)

```bash
python -m src.main move-symbol \
  --repo-root /path/to/project \
  --symbol build_report \
  --source pkg/mathutils.py \
  --target pkg/reportbuilder.py \
  --test-cmd "pytest -q" \
  # --dry-run                                  # Optional: simulate without changes
```

This removes the definition from the source, creates/extends the target file with an import of whatever module-level names the moved code depended on, and rewrites every static reference (`from pkg.mathutils import build_report` → new module; `mathutils.build_report(...)` → bare `build_report(...)` + import).

### Dry-Run Simulation (`--dry-run`)

Add `--dry-run` to any refactoring subcommand (`rename`, `extract-function`, `move-symbol`) to:
- Run **STEP 1: MAP** (static references, blast radius, AST parameter flow)
- Run **STEP 2: WARN** (flag dynamic string risks, prior history, and side effects)
- Skip **SNAPSHOT**, **ACT**, and **VERIFY** (no files edited, no tests run, no ledger record appended)
- Print a clear dry-run summary of all changes that would have been applied.

---

## Demos: Run Included Scenarios

`python demo_run.py` runs all five scenarios on fresh copies and prints a summary. Individually:

### 1. Python rename — no dynamic risk (should succeed)
```bash
cp -r tests/sample_repo /tmp/demo1
python -m src.main rename \
  --repo-root /tmp/demo1 --symbol build_report --to generate_report \
  --test-cmd "pytest -q"
```

### 2. Python rename — dynamic risk (should fail, auto-rollback)
```bash
cp -r tests/sample_repo /tmp/demo2
python -m src.main rename \
  --repo-root /tmp/demo2 --symbol compute_total --to sum_items \
  --test-cmd "pytest -q"
```
Static files are renamed, but `pkg/dynamic_caller.py` calls `getattr(mathutils, "compute_total")` — left untouched. Tests fail with `AttributeError`, the repo is auto-rolled back, and the diagnosis points at `pkg/dynamic_caller.py`.

### 3. Extract-function (should succeed)
```bash
cp -r tests/sample_repo /tmp/demo3
python -m src.main extract-function \
  --repo-root /tmp/demo3 --file pkg/mathutils.py \
  --start-line 30 --end-line 31 --name _build_summary_and_count \
  --test-cmd "pytest -q"
```

### 4. Move-symbol (should succeed)
```bash
cp -r tests/sample_repo /tmp/demo4
python -m src.main move-symbol \
  --repo-root /tmp/demo4 --symbol build_report \
  --source pkg/mathutils.py --target pkg/reportbuilder.py \
  --test-cmd "pytest -q"
```

### 5. JavaScript rename — dynamic risk (should fail, auto-rollback)
```bash
cp -r tests/sample_repo_js /tmp/demo5
python -m src.main rename \
  --repo-root /tmp/demo5 --symbol computeTotal --to sumItems \
  --test-cmd "node --test tests/*.test.js"
```
`pkg/dynamic_call.js` calls `mathutils["computeTotal"](items)` from inside a string literal: the static uses are renamed, the dynamic one is not, Node tests fail with `TypeError: mathutils.computeTotal is not a function`, the repo is rolled back, and the diagnosis points at `pkg/dynamic_call.js`.

---

## Run the Unit Tests

```bash
# Run all unit tests (147 tests passing)
python -m pytest tests/ -v
```

Coverage includes:
- Multi-language AST scanning (Python/JS/TS) & byte-range span replacements
- Extract-function parameter/return data-flow inference
- Move-symbol import graph rewrites
- Scalable dual-strategy snapshot rollback (Git index isolation & Windows read-only object resilience)
- Persistent audit ledger & history inspection
- Anti-hardcoding guards & model availability fallback
- Minimal Patch Guard 11-phase analysis, static rules, test integrity, and metamorphic probes
- FastMCP tool suite integration

---

## MCP Server (Agentic IDE Integration)

Refactor Guard exposes its safe refactoring pipeline and patch review gate as **Model Context Protocol (MCP) tools** for AI coding assistants (Claude Desktop, Cursor, Cline, Antigravity, Windsurf).

### How to Run
```bash
python -m src.mcp_server
```

### Client Configuration
Add the server to your client's MCP configuration (`claude_desktop_config.json`, `.cursor/mcp.json`, etc.):

```json
{
  "mcpServers": {
    "refactor-guard": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "env": {}
    }
  }
}
```

### Available Tools:

#### Core Refactoring Tools
- `refactor_guard_rename(repo_root, symbol, to, test_cmd, dry_run=False)` — Safely rename a symbol across the project with blast radius analysis, dynamic warning checks, automated test verification, and snapshot rollback.
- `refactor_guard_extract_function(repo_root, rel_file, start_line, end_line, name, test_cmd, dry_run=False)` — Extract a Python code block into a new function with automatic parameter and return inference.
- `refactor_guard_move_symbol(repo_root, symbol, source, target, test_cmd, dry_run=False)` — Move a top-level symbol to another module with automatic import rewriting across all project files.
- `refactor_guard_history(repo_root, symbol="", limit=0)` — Query and view the persistent refactoring history and rollback records.
- `refactor_rename`, `refactor_extract_function`, `refactor_move_symbol`, `refactor_history` (backward-compatible aliases).

#### Minimal Patch Guard (MPG) Tools
- `refactor_guard_review_patch(repo_root, base_ref="HEAD", test_cmd="pytest -q", ...)` — Complete multi-phase patch review returning structured JSON with risk score, decision, findings, and verification.
- `refactor_guard_check_minimality(repo_root, base_ref="HEAD", ...)` — Check scope expansion and unrelated modified files without running tests.
- `refactor_guard_check_generalization(repo_root, base_ref="HEAD", test_cmd="pytest -q")` — Probe pure functions against edge/metamorphic inputs and compare base vs candidate behaviour.
- `refactor_guard_compare_runs(repo_root, base_ref="HEAD", test_cmd="pytest -q")` — Run matrix verification comparing baseline vs candidate failures.
- `refactor_review_patch`, `refactor_check_minimality`, `refactor_check_generalization`, `refactor_compare_runs` (backward-compatible aliases).

#### Agent Safety Prompt
- `strict_refactoring_guidelines` — Exposes strict instructions barring agents from introducing narrow workarounds or test-specific hardcoding.

---

## Project Structure

```
refactor-guard/
├── doc/                      # Comprehensive technical documentation manuals
│   ├── README.md             # Documentation index & role navigation
│   ├── ARCHITECTURE.md       # System architecture, pipeline, & data flow
│   ├── CLI_REFERENCE.md      # Command-line flags, options, & exit codes
│   ├── MINIMAL_PATCH_GUARD.md# MPG rules (001-008), scoring, & metamorphic engine
│   ├── MCP_INTEGRATION_GUIDE.md # MCP client setup, tool schemas, & prompts
│   └── SNAPSHOT_AND_LEDGER.md# Git isolated snapshots, Windows resilience, & ledger
├── src/
│   ├── __init__.py
│   ├── dependency_graph.py   # MAP — Tree-sitter multi-language scanning
│   ├── refactor_ops.py       # ACT — Tree-sitter AST byte-range span rename (regex fallback)
│   ├── extract_function.py   # ACT — extract lines into a new function
│   ├── move_symbol.py        # ACT — move a definition + rewrite references
│   ├── snapshot.py           # SNAPSHOT / ROLLBACK via Git throwaway ref or copytree fallback
│   ├── test_runner.py        # VERIFY — subprocess + failure-parsing diagnosis
│   ├── self_heal.py          # VERIFY — optional Gemini AI diagnosis and bounded retry
│   ├── ledger.py             # Persistent refactor history store (.refactor-guard/ledger.jsonl)
│   ├── minimal_patch_guard/  # Minimal Patch Guard (MPG) review pipeline
│   │   ├── __init__.py       # review_patch pipeline orchestrator
│   │   ├── _ts_subprocess.py # Isolated Tree-sitter worker with probe sentinel
│   │   ├── ast_utils.py      # AST analysis for dependencies and symbols
│   │   ├── behavior_checks.py# Exception suppression & bypass checks
│   │   ├── dependency_checks.py # Input dependency tracking
│   │   ├── metamorphic.py    # Metamorphic & edge-case generalization probes
│   │   ├── models.py         # Data models and finding schemas
│   │   ├── patch_parser.py   # Unified git diff parser and tree materializer
│   │   ├── policy.py         # Configurable threshold rules
│   │   ├── regression.py     # Matrix verification runner
│   │   ├── reporter.py       # Formatted text & JSON reporter
│   │   ├── scope_checks.py   # Scope and minimality analysis
│   │   ├── scoring.py        # Multi-factor score and decision engine
│   │   ├── static_checks.py  # Static heuristics for hardcoding & constants
│   │   └── test_integrity.py # Detection of deleted/weakened assertions
│   ├── mcp_server.py         # FastMCP server exposing refactor_guard_* and MPG tools
│   └── main.py               # CLI entrypoint (rename, extract-function, move-symbol, history, review-patch)
├── tests/
│   ├── test_refactor_guard.py# Core pipeline, AST, snapshot, and CLI tests
│   ├── test_ledger.py        # Persistent ledger, history CLI, and advisory warning tests
│   ├── test_minimal_patch_guard.py # Minimal Patch Guard review pipeline tests
│   ├── test_mcp_server.py    # MCP tool suite integration tests
│   ├── test_self_heal_guard.py # Anti-hardcoding and model availability guard tests
│   ├── sample_repo/          # Python fixture (reporter + dynamic-caller)
│   └── sample_repo_js/       # JavaScript fixture (Node test runner)
├── test_reports/             # MPG verification run reports
├── demo_run.py               # runs all 5 demo scenarios
├── requirements.txt
├── pytest.ini
├── LICENSE                   # MIT License
├── .gitignore
└── README.md
```

---

## License

This project is licensed under the [MIT License](LICENSE).

Developed for the **Samsung PRISM Hackathon — Agentic Code Intelligence**.
