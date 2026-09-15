# Refactor Guard

**Samsung PRISM Hackathon — Agentic Code Intelligence**

An autonomous safety layer for code refactoring: it doesn't just make a
change, it maps the blast radius before acting, snapshots the repo, verifies
the change against the real test suite, self-heals on failure, and — unlike
a plain refactor tool — it can also **catch an AI agent's patch cheating its
own tests** before it ever gets merged.

Built to be called two ways: as a **CLI**, or as an **MCP server** any
AI coding agent (Claude Code, Cursor, Cline, Claude Desktop) can invoke
directly — so the safety check lives *inside* the agent's edit loop, not
as an afterthought a human runs later.

---

## Why this is agentic, not just a refactor tool

| Most refactor tools | Refactor Guard |
|---|---|
| Rename and hope the tests still pass | Maps blast radius + flags dynamic-risk references **before** touching anything |
| Leave the repo broken if you were wrong | Snapshots first, auto-rolls back on test failure |
| Give up when verification fails | Gets an AI root-cause diagnosis and retries once, autonomously |
| Trust that a patch is what it claims to be | **Minimal Patch Guard**: detects hardcoded outputs, special-cased test inputs, weakened/deleted tests, and scope creep in *any* patch — including ones written by another AI agent |
| Human-only, CLI-only | Exposed as MCP tools — any AI IDE agent can call it mid-task |

## Core capabilities

1. **Guarded refactoring** (`rename`, `extract-function`, `move-symbol`) —
   Tree-sitter-parsed across Python/JS/TS, with a full
   MAP → WARN → SNAPSHOT → ACT → VERIFY pipeline and automatic rollback.
2. **Blast-radius analysis** — a networkx call graph computed *before* any
   change, so impact is known ahead of time, not discovered after.
3. **Self-heal** — on a failed verification, an LLM (Gemini) diagnoses the
   root cause and the pipeline retries exactly once before rolling back.
4. **Minimal Patch Guard** (`review-patch`) — reviews *any* patch (yours or
   an agent's) against a baseline: flags hardcoded/special-cased outputs,
   test-specific hacks, deleted or weakened tests, and unrelated scope
   expansion. Scores the patch, decides accept/warn/require-approval/reject,
   and can run generalization probes (edge/metamorphic/differential testing)
   on changed pure functions to confirm the fix actually generalizes.
   → [Full MPG documentation](docs/MPG.md)
5. **MCP server** — every capability above is callable by an AI coding agent
   directly, not just from a terminal.

---

## How it works (5 steps)

| Step | Name      | What happens                                                                |
|------|-----------|-----------------------------------------------------------------------------|
| 1    | **MAP**   | Scans the repo for references with Tree-sitter, split into _static_ (calls, |
|      |           | imports, definitions, member access) and _dynamic-risk_ (name in a string).  |
| 2    | **WARN**  | Prints dynamic-risk files **before anything changes** so you know what can't |
|      |           | be auto-rewritten.                                                           |
| 3    | **SNAPSHOT** | Copies the entire repo to a temporary backup folder.                      |
| 4    | **ACT**   | Applies the operation (word-boundary rename / block extraction / symbol     |
|      |           | move with import rewriting).                                                 |
| 5    | **VERIFY** | Runs the target repo's test suite. If tests pass → keep. If they fail →   |
|      |           | **auto-rollback** from the snapshot and print a diagnosis pointing at the    |
|      |           | dynamic-risk file.                                                           |

### Supported languages

| Extension | Grammar                | Static node types                                        | Dynamic-risk |
|-----------|------------------------|----------------------------------------------------------|--------------|
| `.py`     | tree-sitter-python     | `identifier`                                             | `string_content` |
| `.js`     | tree-sitter-javascript | `identifier`, `property_identifier`, `shorthand_property_identifier` | `string_fragment` |
| `.ts`     | tree-sitter-javascript | same as `.js`                                            | `string_fragment` |

For example, `getattr(mathutils, "compute_total")` (Python) and
`mathutils["computeTotal"](items)` (JavaScript) are both flagged as
dynamic-risk: the name is embedded in a string literal and a plain
find-and-replace could never update it.

---

## Setup

```bash
cd refactor-guard

# (Recommended) create a virtual environment
python -m venv venv
source venv/bin/activate   # Linux/Mac
venv\Scripts\activate      # Windows

# Install dependencies (pytest + tree-sitter + grammars)
pip install -r requirements.txt

# Node.js is only needed for the JavaScript sample/demo
node --version             # >= 20 recommended
```

---

## Usage

### Rename a symbol (any supported language)

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
- **parameters** = free variables used but not defined in the block
  (excluding builtins and module-level names);
- **return values** = variables assigned in the block that the enclosing
  function still uses afterwards (returned as a tuple).

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

This removes the definition from the source, creates/extends the target file
with an import of whatever module-level names the moved code depended on, and
rewrites every static reference (`from pkg.mathutils import build_report` →
new module; `mathutils.build_report(...)` → bare `build_report(...)` + import).

### Dry-Run Simulation (`--dry-run`)

Add `--dry-run` to any subcommand (`rename`, `extract-function`, `move-symbol`) to:
- Run **STEP 1: MAP** (static references, blast radius, AST parameter flow)
- Run **STEP 2: WARN** (flag dynamic string risks and side effects)
- Skip **SNAPSHOT**, **ACT**, and **VERIFY** (no files edited, no tests run)
- Print a clear dry-run summary of all changes that would have been applied.

---

## Demos: run the included sample repos

`python demo_run.py` runs all five scenarios on fresh copies and prints a
summary. Individually:

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

Static files are renamed, but `pkg/dynamic_caller.py` calls
`getattr(mathutils, "compute_total")` — left untouched. Tests fail with
`AttributeError`, the repo is auto-rolled back, and the diagnosis points at
`pkg/dynamic_caller.py`.

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

`pkg/dynamic_call.js` calls `mathutils["computeTotal"](items)` from inside a
string literal: the static uses are renamed, the dynamic one is not, Node tests
fail with `TypeError: mathutils.computeTotal is not a function`, the repo is
rolled back, and the diagnosis points at `pkg/dynamic_call.js`.

---

## Run the unit tests

```bash
python -m pytest tests/test_refactor_guard.py -v
```

Coverage includes multi-language scanning (Python/JS/TS), rename,
extract-function, move-symbol, snapshot rollback, and failure diagnosis for
both pytest output (`NameError` / `AttributeError` / `ImportError`) and Node
output (`TypeError` / `ReferenceError`).

---

## MCP server (agentic IDE integration)

Refactor Guard exposes its safe refactoring pipeline as **Model Context Protocol (MCP) tools** for AI coding assistants (Claude Desktop, Cursor, Cline, etc.).

### How to run

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Start the MCP server (over stdio):

```bash
python -m src.mcp_server
```

### MCP IDE registration

For Claude Desktop, Cursor, or Cline, add the server to your MCP configuration:

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

Once registered, the AI assistant has access to the following tools:

- `refactor_guard_rename(repo_root, symbol, to, test_cmd, dry_run=False)` — Safely rename a symbol across the project with blast radius analysis, dynamic warning checks, automated test verification, and snapshot rollback.
- `refactor_guard_extract_function(repo_root, rel_file, start_line, end_line, name, test_cmd, dry_run=False)` — Extract a Python code block into a new function with automatic parameter and return inference.
- `refactor_guard_move_symbol(repo_root, symbol, source, target, test_cmd, dry_run=False)` — Move a top-level symbol to another module with automatic import rewriting across all project files.
- `refactor_rename`, `refactor_extract_function`, `refactor_move_symbol` (backward-compatible aliases).

---

## Minimal Patch Guard

The **Minimal Patch Guard (MPG)** is a standalone review pipeline that checks any patch — yours or
an AI agent's — against a baseline.  It catches over-fit patches: hardcoded outputs, test-specific
branches, removed input dependencies, weakened tests, exception suppression, logic bypass, scope
creep, and more.

### CLI usage

```bash
python -m src.main review-patch \
  --repo-root /path/to/your/project \
  --base-ref HEAD \
  --test-cmd "pytest -q" \
  --run-generalization
```

Key flags:

| Flag | Purpose |
|---|---|
| `--repo-root` | Path to the target repo (required) |
| `--base-ref` | Git ref or base-folder directory to diff against (default: `HEAD`) |
| `--test-cmd` | Verification command; use `""` to skip |
| `--strict-minimality` | Reject any patch with unrelated / expanded changes |
| `--require-approval` | Force `require approval` instead of `accept` where borderline |
| `--run-generalization` | Run safe generalization probes (edge / metamorphic / differential) |
| `--skip-generalization` | Never auto-trigger generalization even when hardcoding is found |
| `--output-format` | `text` (default) or `json` |

Run `python -m src.main review-patch --help` for the full list.

### Worked example: hardcoded test output

A developer patches `add()` to special-case the test's input instead of fixing the real logic:

```python
# Before (committed baseline)
def add(a, b):
    return a + b

# After (the patch under review)
def add(a, b):
    if a == 2 and b == 3:
        return 5
    return a + b
```

Running `review-patch` against this change produces:

```
  SCORE      : 75/100  (risky)  -> REQUIRE_APPROVAL

  FINDINGS
    [low ] MPG-003 — Special-case branch added on a literal input
        pkg/hardcoded.py::add
        New branch in 'add' special-cases the literal a Eq 2.
        Only justified if it fixes a real bug.
        evidence: a Eq 2 (new condition)
    [low ] MPG-003 — Special-case branch added on a literal input
        pkg/hardcoded.py::add
        New branch in 'add' special-cases the literal b Eq 3.
        Only justified if it fixes a real bug.
        evidence: b Eq 3 (new condition)

  VERIFICATION
    not run (no test command supplied)

  GENERALIZATION
    not_run (not requested (set run_generalization=True to probe))

  SUMMARY
    Patched 1 file(s) with 2 finding(s); MPG score 75/100 (risky).
    Strongest signal: special_case_branch.
```

The patch is flagged because it hardcodes the exact inputs the test uses (`a == 2`, `b == 3`)
rather than implementing the general `a + b` logic.

### MPG-specific MCP tools

When using an AI coding assistant, these four MPG tools are available alongside the
standard refactor tools:

| Tool | What it does |
|---|---|
| `refactor_guard_review_patch` | Run the full Minimal Patch Guard review on a candidate diff and return structured JSON (detections, score, decision, generalization probes). |
| `refactor_guard_check_minimality` | Focus the review on patch minimality/scope: detects unrelated changed files, scope-expansion violations, and footprint violations.  No test suite is run. |
| `refactor_guard_check_generalization` | Run generalization probes (edge / metamorphic / differential) on changed pure Python functions and return the results as JSON. |
| `refactor_guard_compare_runs` | Compare baseline vs candidate verification runs: materializes the base tree, runs parse + compile + targeted + full tests on both, and reports which failures are new, resolved, or still failing. |

For the full MPG documentation (scoring model, rule IDs, policy configuration, recipes),
see [`docs/MPG.md`](docs/MPG.md).

---

## Project structure

```
refactor-guard/
├── src/
│   ├── __init__.py
│   ├── dependency_graph.py   # MAP — Tree-sitter multi-language scanning
│   ├── refactor_ops.py       # ACT — word-boundary-safe rename
│   ├── extract_function.py   # ACT — extract lines into a new function
│   ├── move_symbol.py        # ACT — move a definition + rewrite references
│   ├── snapshot.py           # SNAPSHOT / ROLLBACK via shutil + tempfile
│   ├── test_runner.py        # VERIFY — subprocess + failure-parsing diagnosis
│   └── main.py               # CLI entrypoint (3 commands, 5-step pipeline)
├── tests/
│   ├── test_refactor_guard.py
│   ├── sample_repo/          # Python fixture (reporter + dynamic-caller)
│   │   ├── conftest.py
│   │   ├── pkg/
│   │   │   ├── __init__.py
│   │   │   ├── mathutils.py
│   │   │   ├── reporter.py
│   │   │   └── dynamic_caller.py
│   │   └── tests/
│   │       ├── test_reporter.py
│   │       └── test_dynamic.py
│   └── sample_repo_js/       # JavaScript fixture (Node test runner)
│       ├── package.json
│       ├── pkg/
│       │   ├── mathutils.js
│       │   ├── reporter.js
│       │   └── dynamic_call.js
│       └── tests/
│           ├── test_reporter.test.js
│           └── test_dynamic.test.js
├── demo_run.py               # runs all 5 demo scenarios
├── requirements.txt
├── .gitignore
├── LICENSE                   # MIT License
└── README.md
```

---

## License

MIT License — see [LICENSE](LICENSE) for full text.
