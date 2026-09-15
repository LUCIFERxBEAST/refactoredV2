# memory.md — Refactor Guard Project Memory

**Purpose:** Persistent context for AI agents and new contributors. Read this before making changes.

**Last updated:** September 15, 2026
**Project root:** `C:\Users\pondh\Downloads\REFACTOR-GAURD`
**Git:** `main` branch, HEAD `6b8fae1` — "Clarify SUCCESS/FAILURE summary file lists in CLI output"

---

## 1. What this project is

**Refactor Guard** — a Samsung PRISM Hackathon project (Agentic Code Intelligence track).
A refactoring **safety harness** that detects stale references across a codebase
before, during, and after a change, with **automatic rollback** when verification fails.

- **Operations & CLI Tools:** `rename` (Python, JavaScript, TypeScript), `extract-function` (Python only), `move-symbol` (Python only; unsupported languages fail fast with exit code 2), and `history` CLI subcommand / MCP query tool.
- **3 languages:** Python (`.py`), JavaScript (`.js`), TypeScript (`.ts` reuses the JS grammar). Multi-language support applies to `rename`; AST transformations (`extract-function`, `move-symbol`) strictly require Python.
- **Backend:** Tree-sitter AST parsing (not regex-only).
- **Extras:** MCP server for IDE integration (`refactor_guard_*` tools including `refactor_guard_history`), optional Gemini AI self-heal (`GEMINI_MODEL` configurable with 404 pre-flight check and anti-hardcode guard), blast-radius call graph, persistent refactor ledger (`.refactor-guard/ledger.jsonl`).

## 2. The 5-step pipeline (core mental model)

Every refactor operation runs the same pipeline, orchestrated by `src/main.py`:

| Step | Name       | Module(s)                                  | What happens |
|------|-----------|---------------------------------------------|--------------|
| 1    | **MAP**   | `dependency_graph.py` + `ledger.py`         | Tree-sitter scan for references, split into *static* (calls, imports, definitions, member access) and *dynamic-risk* (name inside a string literal). Prints blast radius (networkx transitive call graph). Surfaces prior successful refactor runs (if any). |
| 2    | **WARN**  | `main.py` + `ledger.py`                     | Prints dynamic-risk files **before anything changes** — these can't be auto-rewritten. Surfaces advisory prior-failure history and highlights repeat offenders (advisory only; never blocks, prompts, or alters refactor outcome). |
| 3    | **SNAPSHOT** | `snapshot.py`                             | Scalable backup: zero-copy Git throwaway ref snapshot (isolated temp index seeded from HEAD, pathspec-scoped restore, zero-commit resilience) or copytree fallback excluding large dirs (`node_modules`, `.git`, `venv`, `__pycache__`, etc.). **Fully transparent to the CLI** (identical signatures: `create_snapshot`, `restore_snapshot`, `cleanup_snapshot`). |
| 4    | **ACT**   | `refactor_ops.py` / `extract_function.py` / `move_symbol.py` | Applies the edit (Tree-sitter AST byte-range span rename in binary mode, preserving comments/docstrings/strings with regex fallback on parse errors; Python AST block extraction / symbol move with import rewriting). |
| 5    | **VERIFY** | `test_runner.py` + `self_heal.py` + `ledger.py` | Runs the target repo's test suite. Pass → keep + delete backup. Fail → AI diagnosis (optional) + exactly one bounded retry → still failing → **auto-rollback** + diagnosis pointing at dynamic-risk file. Appends full record to persistent ledger (`.refactor-guard/ledger.jsonl`) on all terminal outcomes (success, rolled_back, error; skipped on `--dry-run`). |

Exit codes: `0` = success (change kept), `1` = failure (rolled back or ACT error), `2` = usage/input error (bad repo root, missing file, no definition found, unsupported language for operation).

## 3. Module map

```
src/
├── main.py               CLI entrypoint; build_parser(); do_rename/do_extract/do_move/do_history;
│                         _verify_step/_snapshot_step/_print_blast_radius; check_supported_extension; exposes do_* for MCP.
├── dependency_graph.py   MAP. scan_repo/scan_source/blast_radius. Grammar specs per extension (Python, JS, TS). Detects parse error nodes.
├── refactor_ops.py       ACT rename. Tree-sitter AST byte-range span replacement in binary mode (open rb/wb), preserving comments/docstrings; word-boundary regex fallback on parse error.
├── extract_function.py   ACT extract. analyze_block/apply_extraction/extract_into_file (Python only).
├── move_symbol.py        ACT move. move_symbol/find_top_level_definition/dotted_module (Python only).
├── snapshot.py           Scalable dual-strategy snapshot: Git throwaway ref (isolated temporary index, HEAD seeding, scoped restore, zero-commit handling, gitignored detection fallback) and non-git copytree fallback. Fully transparent via identical signatures.
├── test_runner.py        VERIFY. run_tests (subprocess, timeout=300s), diagnose_failures (pytest and node test output).
├── self_heal.py          Optional AI diagnosis (GEMINI_MODEL env var, default: gemini-3.6-flash) with dynamic _MODEL lookup, 404/deprecated pre-flight check, and anti-hardcode guard.
├── ledger.py             Persistent refactor audit store (<repo_root>/.refactor-guard/ledger.jsonl). append_record, read_ledger, find_prior_failures, find_prior_successes. Gitignored and fail-soft.
└── mcp_server.py         FastMCP server exposing refactor_guard_* tools (including refactor_guard_history) with per-operation language checks.
```

## 4. Key design decisions

1. **Tree-sitter for scanning**, not regex — multi-language AST correctness.
2. **AST byte-range span rename (not blind regex)** — AST static identifier spans from Tree-sitter are used to rebuild files in binary mode (`open(..., 'rb')`/`'wb'`), ensuring comments, docstrings, string literals, and non-ASCII/emojis are never modified or corrupted. Falls back to word-boundary regex for that file only if Tree-sitter produces a syntax error node.
3. **Dynamic-risk references flagged, never auto-rewritten** — name inside string literals.
4. **Self-heal is optional and non-blocking** — skipped gracefully without API key or if the configured GEMINI_MODEL is unavailable/deprecated (404/not-found).
5. **Bounded retry = exactly one** test-suite re-run after AI diagnosis.
6. **AI only diagnoses, never edits code** — outcome is keep-or-rollback.
7. **Scalable dual-strategy snapshot/rollback** — Git throwaway refs (`refs/refactor-guard/*`) with isolated index (`GIT_INDEX_FILE`), seeded with `HEAD` for subdirectory isolation and scoped restore; non-git fallback uses `copytree` excluding `node_modules`, `.git`, `venv`, `__pycache__`, etc. Real index is never modified. Handles zero-commit repos (omits `-p HEAD`) and falls back to copytree when gitignored source files are present. **Fully transparent to the CLI**: `create_snapshot(repo_root: str) -> str`, `restore_snapshot(backup_path: str, repo_root: str) -> None`, and `cleanup_snapshot(backup_path: str, repo_root: str) -> None` maintain identical signatures across both Git and copytree strategies.
8. **Anti-hardcode guard & check** — system prompt instructs model to propose general fixes; response scanned for narrow/hardcoded fix patterns (`just return`, `hardcode`, `special case`, etc.) to warn developer.
9. **Configurable Gemini model** — `GEMINI_MODEL` env var overrides default (`gemini-3.6-flash`); 404/deprecated model errors are caught via pre-flight check and skipped gracefully. Dynamic module `__getattr__` prevents `_MODEL` drift.
10. **Per-operation language enforcement** — `SUPPORTED_EXTENSIONS` table in `main.py` and `mcp_server.py` validates target extensions before execution. `rename` allows `.py`, `.js`, `.ts`; `extract-function` and `move-symbol` enforce `.py` only, failing fast with exit code 2.
11. **Persistent refactor ledger (`.refactor-guard/ledger.jsonl`)** — Stores newline-delimited JSON records of all completed refactors (success, rolled_back, error) containing timestamps, operation, symbol, params, static files, dynamic risk files, failure symbols, and test command. The ledger is automatically gitignored and excluded from copytree snapshots. Writes are fail-soft (exceptions never alter the operation exit code or disrupt rollbacks; skipped on `--dry-run`). In STEP 2 (WARN), prior failures for the same operation+symbol are surfaced as an **advisory-only** warning highlighting repeat offenders — it never aborts, blocks, or alters the operation's outcome. Auditable via the `history` CLI subcommand (`--repo-root`, `--symbol`, `--limit`, `--json`) and `refactor_guard_history` MCP tool.

## 5. Technical Debt & Resolution Notes

- **Resolved: Whole-file regex substitution in `refactor_ops.py`**:
  Previously, `refactor_ops.py` performed whole-file word-boundary regex substitution (`\b<symbol>\b`), which risked erroneously renaming symbol text appearing inside comments, docstrings, or unrelated strings.
  *Fix:* `refactor_ops.py` now reconstructs source files strictly using the byte-range spans of verified AST identifier nodes from Tree-sitter (`dependency_graph.py`'s `static_spans` across Python, JavaScript, and TypeScript), preserving comments, docstrings, and string literals without modification.
- **Resolved: Full-directory copytree snapshot scaling & Git scoping issues**:
  Previously, `snapshot.py` performed a full `shutil.copytree` of the repo on every run.
  *Fix:* Upgraded to a scalable dual-strategy backup system. For Git repos, creates a lightweight commit on `refs/refactor-guard/*` using an isolated `GIT_INDEX_FILE` (real index never touched). Pre-populates temp index via `git read-tree HEAD` to preserve outside files in subdirectories, scopes restore via `git checkout-index -f -z --stdin`, handles zero-commit repos (omitting `-p HEAD`), and automatically falls back to copytree if gitignored source files exist. For non-Git repos, `copytree` excludes large irrelevant directories (`node_modules`, `.git`, `venv`, `__pycache__`, etc.).
- **Resolved: Unclear language support in extract-function & move-symbol**:
  Previously, non-Python files passed to `extract-function` or `move-symbol` produced cryptic AST parsing failures.
  *Fix:* Added explicit validation via `check_supported_extension` in `main.py` and `mcp_server.py`. Python files work unchanged; unsupported extensions fail fast with exit code 2 and a clear support matrix.
- **Resolved: Hardcoded Gemini model & unhandled 404 errors**:
  Previously, model name was hardcoded as a module-level constant and failed API calls raised unhandled exceptions.
  *Fix:* Model name is read dynamically via `get_model_name()` from `GEMINI_MODEL` (default: `gemini-3.6-flash`) with dynamic `__getattr__` for `_MODEL`. Added `is_model_unavailable_error` to catch 404/deprecated errors and skip self-heal gracefully.
- **Resolved: Blind repeat failures & missing refactor history**:
  Previously, Refactor Guard possessed no memory of past runs; repeated attempts on symbols with dynamic-risk callers would repeatedly fail and roll back without warning.
  *Fix:* Created `src/ledger.py` and `.refactor-guard/ledger.jsonl` (gitignored, fail-soft). Pre-flight checks in STEP 1/2 surface prior successes and advisory warnings for prior rollbacks with repeat offender tagging. Added `history` CLI command (`--repo-root`, `--symbol`, `--limit`, `--json`) and `refactor_guard_history` FastMCP tool.
- **Resolved: Upstream Minimal Patch Guard (MPG) integration & conflict resolution**:
  Integrated upstream package `src/minimal_patch_guard/` into Refactor Guard. Reconciled `src/main.py` (added `review-patch` CLI while preserving `history`, language checks, and ledger logging) and `src/mcp_server.py` (added 4 MPG FastMCP tools + 4 aliases alongside `history`, agent instructions, and safety prompt).
- **Resolved: Windows read-only Git objects & permissions error during rollback/cleanup**:
  Previously, read-only files (e.g., git objects `0o444`) caused `shutil.rmtree` or file overwrite to abort with WinError 5 on Windows.
  *Fix:* Added `_force_remove_tree` (chmod retry loop) and `_force_remove_file` in `src/snapshot.py`. Made snapshot restore and directory cleanup resilient against read-only attributes on both Linux and Windows. Scoped `.git` exclusion to real Git repositories via `_get_excluded_dirs`.

## 6. Commands & Testing

```powershell
# Unit tests (147 tests passing)
python -m pytest tests/ -v

# Run all 5 demo scenarios
python demo_run.py

# CLI usage: Refactoring operations
python -m src.main rename --repo-root <path> --symbol old --to new --test-cmd "pytest -q"
python -m src.main extract-function --repo-root <path> --file pkg/m.py --start-line 30 --end-line 31 --name helper --test-cmd "pytest -q"
python -m src.main move-symbol --repo-root <path> --symbol fn --source pkg/a.py --target pkg/b.py --test-cmd "pytest -q"

# CLI usage: Refactor history inspection
python -m src.main history --repo-root <path>
python -m src.main history --repo-root <path> --symbol old --limit 5
python -m src.main history --repo-root <path> --json

# CLI usage: Minimal Patch Guard (MPG) review
python -m src.main review-patch --repo-root <path>
python -m src.main review-patch --repo-root <path> --base-ref HEAD~1 --test-cmd ""
python -m src.main review-patch --repo-root <path> --strict-minimality --output-format json
```
