# Refactor Guard: CLI Reference Manual

The `refactor-guard` CLI (`python -m src.main`) provides commands for safe refactoring, history auditing, and patch review.

---

## Global Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | **Success**: Operation succeeded, tests passed, or patch was Accepted/Warned. |
| `1` | **Rollback / Review Flagged**: Refactor failed verification and was rolled back, or patch Requires Approval. |
| `2` | **Usage Error / Rejected**: Invalid arguments, unsupported file extension, or patch Rejected. |

---

## 1. `rename`

Rename a symbol across all static references in a repository with blast radius mapping, dynamic risk detection, and automatic rollback.

### Syntax
```bash
python -m src.main rename \
  --repo-root <path> \
  --symbol <old_name> \
  --to <new_name> \
  --test-cmd <command> \
  [--dry-run]
```

### Options
- `--repo-root` *(required, string)*: Path to the target repository.
- `--symbol` *(required, string)*: Existing symbol name to rename.
- `--to` *(required, string)*: Replacement symbol name.
- `--test-cmd` *(required, string)*: Shell command to run project tests (e.g. `"pytest -q"` or `"node --test"`).
- `--dry-run` *(optional, flag)*: Run MAP and WARN steps to preview changes without modifying files or running tests.

### Supported File Types
- Python (`.py`), JavaScript (`.js`), TypeScript (`.ts`).

### Example
```bash
python -m src.main rename \
  --repo-root /path/to/my_project \
  --symbol calculate_tax \
  --to compute_tax \
  --test-cmd "pytest tests/ -q"
```

---

## 2. `extract-function`

Extract a contiguous range of lines within a Python file into a new function, inferring parameters and return values via AST data-flow analysis.

### Syntax
```bash
python -m src.main extract-function \
  --repo-root <path> \
  --file <rel_path> \
  --start-line <int> \
  --end-line <int> \
  --name <new_function_name> \
  --test-cmd <command> \
  [--dry-run]
```

### Options
- `--repo-root` *(required, string)*: Path to the repository root.
- `--file` *(required, string)*: File path relative to repository root (must be `.py`).
- `--start-line` *(required, integer)*: 1-indexed starting line number of block (inclusive).
- `--end-line` *(required, integer)*: 1-indexed ending line number of block (inclusive).
- `--name` *(required, string)*: Name for the newly created function.
- `--test-cmd` *(required, string)*: Verification test command.
- `--dry-run` *(optional, flag)*: Preview extracted function signature and replacement call without editing disk.

### Example
```bash
python -m src.main extract-function \
  --repo-root /path/to/my_project \
  --file services/order.py \
  --start-line 45 \
  --end-line 62 \
  --name _apply_discounts \
  --test-cmd "pytest tests/test_orders.py -q"
```

---

## 3. `move-symbol`

Relocate a top-level function or class definition from one Python module to another, automatically updating imports across all project files.

### Syntax
```bash
python -m src.main move-symbol \
  --repo-root <path> \
  --symbol <symbol_name> \
  --source <source_rel_path> \
  --target <target_rel_path> \
  --test-cmd <command> \
  [--dry-run]
```

### Options
- `--repo-root` *(required, string)*: Path to the repository root.
- `--symbol` *(required, string)*: Name of the top-level definition to move.
- `--source` *(required, string)*: Current Python module file (relative to repo root).
- `--target` *(required, string)*: Target Python module file (created if non-existent).
- `--test-cmd` *(required, string)*: Verification test command.
- `--dry-run` *(optional, flag)*: Preview updated imports and file moves without altering disk.

### Example
```bash
python -m src.main move-symbol \
  --repo-root /path/to/my_project \
  --symbol FormatInvoice \
  --source utils/formatters.py \
  --target billing/invoices.py \
  --test-cmd "pytest -q"
```

---

## 4. `history`

Inspect the persistent refactoring ledger stored in `.refactor-guard/ledger.jsonl`.

### Syntax
```bash
python -m src.main history \
  --repo-root <path> \
  [--symbol <symbol_name>] \
  [--limit <int>] \
  [--json]
```

### Options
- `--repo-root` *(required, string)*: Path to the repository root.
- `--symbol` *(optional, string)*: Filter records to operations involving a specific symbol.
- `--limit` *(optional, integer)*: Limit display to the *N* most recent operations.
- `--json` *(optional, flag)*: Output raw JSON lines for CI ingestion and tooling.

### Example
```bash
# View last 5 operations in human-readable colored output
python -m src.main history --repo-root . --limit 5

# Export full history as JSON
python -m src.main history --repo-root . --json > audit_log.json
```

---

## 5. `review-patch`

Run the **Minimal Patch Guard (MPG)** review pipeline against the working tree to evaluate patch safety, detect test weakening, and score minimality.

### Syntax
```bash
python -m src.main review-patch \
  --repo-root <path> \
  [--base-ref <git_ref_or_dir>] \
  [--test-cmd <command>] \
  [--strict-minimality] \
  [--max-files-changed <int>] \
  [--max-lines-changed <int>] \
  [--require-approval] \
  [--run-generalization] \
  [--skip-generalization] \
  [--operation {rename,extract-function,move-symbol}] \
  [--output-format {text,json}]
```

### Options
- `--repo-root` *(required, string)*: Path to the target repository.
- `--base-ref` *(optional, string, default: `"HEAD"`)*: Git commit/ref or directory path containing the baseline snapshot.
- `--test-cmd` *(optional, string)*: Verification command executed against both baseline and candidate trees. Use `""` to skip test execution.
- `--strict-minimality` *(optional, flag)*: Reject patches that touch files unrelated to the declared changes.
- `--max-files-changed` *(optional, integer)*: Cap on total changed files before flagging scope expansion.
- `--max-lines-changed` *(optional, integer)*: Cap on total modified lines before flagging scope expansion.
- `--require-approval` *(optional, flag)*: Escalate borderline decisions to Require Approval.
- `--run-generalization` *(optional, flag)*: Probe pure changed functions with edge and metamorphic inputs.
- `--skip-generalization` *(optional, flag)*: Disable generalization probes even when hardcoding is detected.
- `--operation` *(optional, choice)*: Declared refactoring operation to validate against expected change footprint.
- `--output-format` *(optional, choice: `text`, `json`, default: `text`)*: Terminal text narration or structured JSON.

### Example
```bash
# Fast pre-commit check (no test suite run)
python -m src.main review-patch --repo-root . --test-cmd ""

# Full CI gating check with strict caps and JSON report
python -m src.main review-patch \
  --repo-root . \
  --base-ref origin/main \
  --strict-minimality \
  --max-files-changed 5 \
  --output-format json
```
