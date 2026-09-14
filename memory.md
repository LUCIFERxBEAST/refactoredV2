# memory.md — Refactor Guard Project Memory

**Purpose:** Persistent context for AI agents and new contributors. Read this before making changes.

**Last updated:** September 14, 2026
**Project root:** `C:\Users\pondh\Downloads\REFACTOR-GAURD`
**Git:** `main` branch, HEAD `6b8fae1` — "Clarify SUCCESS/FAILURE summary file lists in CLI output"

---

## 1. What this project is

**Refactor Guard** — a Samsung PRISM Hackathon project (Agentic Code Intelligence track).
A refactoring **safety harness** that detects stale references across a codebase
before, during, and after a change, with **automatic rollback** when verification fails.

- **3 operations:** `rename`, `extract-function`, `move-symbol`
- **3 languages:** Python, JavaScript, TypeScript (`.ts` reuses the JS grammar)
- **Backend:** Tree-sitter AST parsing (not regex-only)
- **Extras:** MCP server for IDE integration, optional Gemini AI self-heal, blast-radius call graph

## 2. The 5-step pipeline (core mental model)

Every operation runs the same pipeline, orchestrated by `src/main.py`:

| Step | Name       | Module(s)                                  | What happens |
|------|-----------|---------------------------------------------|--------------|
| 1    | **MAP**   | `dependency_graph.py`                        | Tree-sitter scan for references, split into *static* (calls, imports, definitions, member access) and *dynamic-risk* (name inside a string literal). Also prints blast radius (networkx transitive call graph). |
| 2    | **WARN**  | `main.py`                                    | Prints dynamic-risk files **before anything changes** — these can't be auto-rewritten. |
| 3    | **SNAPSHOT** | `snapshot.py`                             | `shutil.copytree` of the whole repo into a `tempfile.mkdtemp` backup. |
| 4    | **ACT**   | `refactor_ops.py` / `extract_function.py` / `move_symbol.py` | Applies the edit (word-boundary rename / block extraction / symbol move with import rewriting). |
| 5    | **VERIFY** | `test_runner.py` + `self_heal.py`           | Runs the target repo's test suite. Pass → keep + delete backup. Fail → AI diagnosis (optional) + exactly one bounded retry → still failing → **auto-rollback** + diagnosis pointing at dynamic-risk file. |

Exit codes: `0` = success (change kept), `1` = failure (rolled back or ACT error), `2` = usage/input error (bad repo root, missing file, no definition found).

## 3. Module map

```
src/
├── main.py               CLI entrypoint; build_parser(); do_rename/do_extract/do_move;
│                         _verify_step/_snapshot_step/_print_blast_radius; exposes do_* for MCP.
├── dependency_graph.py   MAP. scan_repo/scan_source/blast_radius. Grammar specs per extension.
├── refactor_ops.py       ACT rename. rename_symbol_in_file / rename_in_files (\b boundary).
├── extract_function.py   ACT extract. analyze_block/apply_extraction/extract_into_file.
├── move_symbol.py        ACT move. move_symbol/find_top_level_definition/dotted_module.
├── snapshot.py           create_snapshot/restore_snapshot/cleanup_snapshot via shutil.copytree.
├── test_runner.py        VERIFY. run_tests (subprocess, timeout=300s), diagnose_failures.
├── self_heal.py          Optional AI diagnosis. gemini-3.6-flash prompt with anti-hardcode guard.
└── mcp_server.py         Thin MCP wrapper around src.main.do_*.
```

## 4. Key design decisions

1. **Tree-sitter for scanning**, not regex — multi-language AST correctness.
2. **Word-boundary rename** (`\b` + `re.escape`) — prevents partial matches.
3. **Dynamic-risk references flagged, never auto-rewritten** — name inside string literals.
4. **Self-heal is optional and non-blocking** — skipped gracefully without API key.
5. **Bounded retry = exactly one** test-suite re-run after AI diagnosis.
6. **AI only diagnoses, never edits code** — outcome is keep-or-rollback.
7. **Snapshot/rollback via shutil + tempfile** — backup deleted on success and rollback.
8. **Anti-hardcode guard & check** — system prompt instructs model to propose general fixes; response scanned for narrow/hardcoded fix patterns to warn developer.



## 5. Commands & Testing

```powershell
# Unit tests
python -m pytest tests/test_refactor_guard.py -v

# Run all 5 demo scenarios
python demo_run.py

# CLI usage
python -m src.main rename --repo-root <path> --symbol old --to new --test-cmd "pytest -q"
python -m src.main extract-function --repo-root <path> --file pkg/m.py --start-line 30 --end-line 31 --name helper --test-cmd "pytest -q"
python -m src.main move-symbol --repo-root <path> --symbol fn --source pkg/a.py --target pkg/b.py --test-cmd "pytest -q"
```
