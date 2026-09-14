# Refactor Guard

**Samsung PRISM Hackathon — Agentic Code Intelligence**

A refactoring safety harness that detects stale references across a codebase
before, during, and after a change — with automatic rollback when verification
fails. Supports **three operations** (`rename`, `extract-function`,
`move-symbol`) across **three syntaxes** (Python, JavaScript, TypeScript),
all parsed with **Tree-sitter**.

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
```

### Extract a block into a new function (Python)

```bash
python -m src.main extract-function \
  --repo-root /path/to/project \
  --file pkg/mathutils.py \
  --start-line 30 --end-line 31 \
  --name _build_summary_and_count \
  --test-cmd "pytest -q"
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
  --test-cmd "pytest -q"
```

This removes the definition from the source, creates/extends the target file
with an import of whatever module-level names the moved code depended on, and
rewrites every static reference (`from pkg.mathutils import build_report` →
new module; `mathutils.build_report(...)` → bare `build_report(...)` + import).

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
└── README.md
```

---

## License

Hackathon / educational use.
