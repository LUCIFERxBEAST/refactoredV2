"""
main.py — CLI entrypoint for Refactor Guard

Ties together all 5 steps: MAP -> WARN -> SNAPSHOT -> ACT -> VERIFY.

Commands:
  rename
      python -m src.main rename --repo-root /path --symbol old --to new --test-cmd "pytest -q"
  extract-function
      python -m src.main extract-function --repo-root /path --file pkg/mod.py \
          --start-line 10 --end-line 12 --name helper --test-cmd "pytest -q"
  move-symbol
      python -m src.main move-symbol --repo-root /path --symbol fn \
          --source pkg/a.py --target pkg/b.py --test-cmd "pytest -q"
"""

import argparse
import os
import sys

import colorama
from colorama import Fore, Style

colorama.init()


def _green(s: str) -> str:
    return f"{Fore.GREEN}{s}{Style.RESET_ALL}"


def _yellow(s: str) -> str:
    return f"{Fore.YELLOW}{s}{Style.RESET_ALL}"


def _red(s: str) -> str:
    return f"{Fore.RED}{s}{Style.RESET_ALL}"


from .dependency_graph import blast_radius, scan_repo
from .extract_function import analyze_block, extract_into_file
from .move_symbol import move_symbol as apply_move_symbol
from .refactor_ops import rename_in_files
from .self_heal import get_diagnosis, has_api_key
from .snapshot import create_snapshot, restore_snapshot, cleanup_snapshot
from .test_runner import run_tests, diagnose_failures, language_of_files

# Windows consoles default to code pages (cp1252/cp437) that cannot represent
# the ✓/⚠/→/🔍/💡 glyphs used below.  Reconfigure so human-readable output
# never crashes the CLI (e.g. with UnicodeEncodeError).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def build_parser():
    parser = argparse.ArgumentParser(
        prog="refactor-guard",
        description="Safely refactor symbols across a codebase.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rename_p = sub.add_parser(
        "rename", help="Rename a symbol with safety checks."
    )
    rename_p.add_argument("--repo-root", required=True, help="Path to the target repo")
    rename_p.add_argument("--symbol", required=True, help="Old symbol name to rename")
    rename_p.add_argument("--to", required=True, help="New symbol name")
    rename_p.add_argument(
        "--test-cmd", required=True,
        help="Test command to verify, e.g. 'pytest -q'",
    )
    rename_p.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Simulate the refactoring without modifying files on disk or running tests",
    )

    extract_p = sub.add_parser(
        "extract-function",
        help="Extract a block of lines into a new function.",
    )
    extract_p.add_argument("--repo-root", required=True, help="Path to the target repo")
    extract_p.add_argument(
        "--file", required=True,
        help="Python file (relative to repo root) containing the block",
    )
    extract_p.add_argument(
        "--start-line", type=int, required=True,
        help="First line of the block (1-based, inclusive)",
    )
    extract_p.add_argument(
        "--end-line", type=int, required=True,
        help="Last line of the block (1-based, inclusive)",
    )
    extract_p.add_argument(
        "--name", required=True, help="Name for the new function"
    )
    extract_p.add_argument(
        "--test-cmd", required=True,
        help="Test command to verify, e.g. 'pytest -q'",
    )
    extract_p.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Simulate the refactoring without modifying files on disk or running tests",
    )

    move_p = sub.add_parser(
        "move-symbol",
        help="Move a top-level definition to another file.",
    )
    move_p.add_argument("--repo-root", required=True, help="Path to the target repo")
    move_p.add_argument(
        "--symbol", required=True,
        help="Name of the top-level function/class to move",
    )
    move_p.add_argument(
        "--source", required=True,
        help="Source Python file (relative to repo root)",
    )
    move_p.add_argument(
        "--target", required=True,
        help="Target Python file (relative to repo root); created if needed",
    )
    move_p.add_argument(
        "--test-cmd", required=True,
        help="Test command to verify, e.g. 'pytest -q'",
    )
    move_p.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Simulate the refactoring without modifying files on disk or running tests",
    )
    return parser

def _verify_step(repo_root: str, test_cmd: str, snapshot: str,
                 symbol: str, dynamic_files, action_desc: str = "",
                 changed_files: list = None) -> int:
    """STEP 5. Returns process exit code (0 = success)."""
    print()
    print("=" * 60)
    print("  STEP 5: VERIFY")
    print("  → Running the project's real tests to make sure nothing broke...")
    print(f"  (Technical) running test suite: {test_cmd}")
    print("=" * 60)
    passed, output, code = run_tests(repo_root, test_cmd)
    if output.strip():
        for line in output.strip().splitlines():
            print(f"  {line}")
    print(f"  Exit code: {code}")

    if passed:
        print()
        print(_green("=" * 60))
        print(_green("  SUCCESS ✓ — All tests pass. Change is kept."))
        print(_green("=" * 60))
        cleanup_snapshot(snapshot)
        print(_green(f"  Backup deleted: {snapshot}"))
        print()
        print(_green("=" * 60))
        print(_green("SUMMARY: SUCCESS — pipeline completed safely"))
        print(_green(f"What you asked to do: {action_desc if action_desc else f'Refactor symbol {symbol}'}"))
        if changed_files:
            print(_green(f"Files actually changed: {', '.join(changed_files)}"))
        print(_green("Changed files: see STEP 1 static-file list (edits only applied to those files)"))
        if dynamic_files:
            print(_green(f"Risky files skipped/flagged: {', '.join(dynamic_files)}"))
        print(_green("Risk files: see STEP 1 dynamic-risk list (not auto-changed)"))
        print(_green("Final outcome: SUCCESS — All tests passed!"))
        print(_green("Outcome: VERIFY passed; rollback not performed"))
        print(_green("=" * 60))
        return 0

    print()
    print(_yellow("=" * 60))
    print(_yellow("  === Self-Heal: AI Diagnosis ==="))
    print(_yellow("=" * 60))
    if has_api_key():
        diagnosis = get_diagnosis(symbol, output, dynamic_files)
        if diagnosis:
            print(_yellow(diagnosis))
        print()
        print(_yellow("  Retrying test suite exactly once…"))
        passed2, output2, code2 = run_tests(repo_root, test_cmd)
        if output2.strip():
            for line in output2.strip().splitlines():
                print(f"  {line}")
        print(f"  Exit code: {code2}")
        if passed2:
            print()
            print(_green("=" * 60))
            print(_green("  SUCCESS ✓ — AI diagnosis helped resolve a transient "
                        "issue. Change is kept."))
            print(_green("=" * 60))
            cleanup_snapshot(snapshot)
            print(_green(f"  Backup deleted: {snapshot}"))
            print()
            print(_green("=" * 60))
            print(_green("SUMMARY: SUCCESS — pipeline completed safely"))
            print(_green(f"What you asked to do: {action_desc if action_desc else f'Refactor symbol {symbol}'}"))
            if changed_files:
                print(_green(f"Files actually changed: {', '.join(changed_files)}"))
            print(_green("Changed files: see STEP 1 static-file list (edits only applied to those files)"))
            if dynamic_files:
                print(_green(f"Risky files skipped/flagged: {', '.join(dynamic_files)}"))
            print(_green("Risk files: see STEP 1 dynamic-risk list (not auto-changed)"))
            print(_green("Final outcome: SUCCESS — Tests passed on retry!"))
            print(_green("Outcome: VERIFY passed; rollback not performed"))
            print(_green("=" * 60))
            return 0
    else:
        print(_yellow("  Skipping AI diagnosis — no API key configured"))

    print()
    print(_red("=" * 60))
    print(_red("  FAILURE ✗ — tests failed after the change. Rolling back…"))
    print(_red("=" * 60))
    restore_snapshot(snapshot, repo_root)
    print(_red("  Repo restored from snapshot."))
    cleanup_snapshot(snapshot)
    print(_red("  Backup deleted."))
    print()
    print(_red("=" * 60))
    print(_red("SUMMARY: FAILURE — VERIFY failed; changes were automatically undone"))
    print(_red(f"What you asked to do: {action_desc if action_desc else f'Refactor symbol {symbol}'}"))
    if changed_files:
        print(_red(f"Files affected (rolled back): {', '.join(changed_files)}"))
    print(_red("Changed files: see STEP 1 static-file list (rolled back after tests failed)"))
    if dynamic_files:
        print(_red(f"Risky files skipped/flagged: {', '.join(dynamic_files)}"))
    print(_red("Risk files: see STEP 1 dynamic-risk list (not auto-changed)"))
    print(_red("Final outcome: ROLLED BACK — Tests failed; changes were undone."))
    print(_red("Outcome: repository restored from snapshot; rollback performed"))
    print(_red("=" * 60))
    print()
    print(_red("=" * 60))
    print(_red("  DIAGNOSIS"))
    print(_red("=" * 60))
    print(_red(diagnose_failures(output, symbol, dynamic_files)))
    return 1


def _snapshot_step(repo_root: str) -> str:
    print()
    print("=" * 60)
    print("  STEP 3: SNAPSHOT")
    print("  → Backing up the entire project first, so this can always be undone.")
    print("  (Technical) backing up repo before editing")
    print("=" * 60)
    snapshot = create_snapshot(repo_root)
    print(f"  Backup created at: {snapshot}")
    return snapshot


def _print_blast_radius(repo_root: str, symbol: str) -> None:
    """STEP 1 informational output: files transitively affected (call graph)."""
    try:
        files = blast_radius(repo_root, symbol)
    except Exception as e:  # never let informational output break a run
        print(f"  Blast radius: (could not compute — {e})")
        return
    print("  Blast radius — files transitively affected:")
    if files:
        print(f"    {len(files)} file(s) transitively affected")
        for f in files:
            print(f"    - {f}")
    else:
        print("    (none)")


def do_rename(repo_root: str, symbol: str, to: str, test_cmd: str,
              dry_run: bool = False) -> int:
    repo_root = os.path.abspath(repo_root)

    # ── 1. MAP ────────────────────────────────────────────────────────────
    print("=" * 60)
    print("  STEP 1: MAP")
    print("  → Looking through the entire project to find every place this code is used...")
    print(f"  (Technical) scanning for references to '{symbol}'")
    print("=" * 60)
    if not os.path.isdir(repo_root):
        print(_red(f"ERROR: repo root does not exist: {repo_root}"))
        return 2

    print(f"  Scanning: {repo_root}")
    result = scan_repo(repo_root, symbol)

    print("  Static references found in:")
    if result.static_files:
        for f in result.static_files:
            print(f"    - {f}")
    else:
        print("    (none)")

    print("  Dynamic-risk references found in:")
    if result.dynamic_risk_files:
        for f in result.dynamic_risk_files:
            print(f"    - {f}")
    else:
        print("    (none)")

    _print_blast_radius(repo_root, symbol)

    if not result.static_files:
        print(_yellow(f"\n  WARNING: no static references to '{symbol}' found; nothing to do."))
        return 0

    # ── 2. WARN ───────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  STEP 2: WARN")
    print("  → Found some risky spots where the name is only used as text (not real code) —")
    print("    these can't be safely auto-changed, so I'll flag them instead of guessing.")
    print("  (Technical) dynamic-risk check (nothing changed yet)")
    print("=" * 60)
    if result.has_dynamic_risk:
        print(_yellow(f"  ⚠ WARNING: '{symbol}' appears inside string literals in:"))
        for f in result.dynamic_risk_files:
            print(_yellow(f"    - {f}"))
        if language_of_files(result.dynamic_risk_files) == {"javascript"}:
            print(_yellow("  These files access the symbol by name at runtime "
                          "(e.g. obj['name'] — bracket-notation member access)."))
        else:
            print(_yellow("  These files use the symbol dynamically "
                          "(e.g. getattr(obj, 'name'))."))
        print(_yellow("  They will NOT be renamed automatically."))
    else:
        print(_green("  No dynamic-risk references detected — safe to proceed."))

    if dry_run:
        print()
        print(_yellow("=" * 60))
        print(_yellow("DRY-RUN SUMMARY — no changes were made to disk"))
        print(_yellow(f"What you asked to do: Rename symbol '{symbol}' → '{to}'"))
        if result.static_files:
            print(_yellow(f"Files that would be changed: {', '.join(result.static_files)}"))
        else:
            print(_yellow("Files that would be changed: (none)"))
        if result.dynamic_risk_files:
            print(_yellow(f"Risky files flagged/skipped: {', '.join(result.dynamic_risk_files)}"))
        else:
            print(_yellow("Risky files flagged/skipped: (none)"))
        print(_yellow("Final outcome: DRY-RUN COMPLETED (Snapshot, Act, and Verify steps skipped)"))
        print(_yellow("=" * 60))
        return 0

    # ── 3. SNAPSHOT ───────────────────────────────────────────────────────
    snapshot = _snapshot_step(repo_root)

    # ── 4. ACT ────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  STEP 4: ACT")
    print("  → Applying the change to the files I'm confident about...")
    print(f"  (Technical) renaming '{symbol}' → '{to}' in static files")
    print("=" * 60)
    try:
        changes = rename_in_files(repo_root, symbol, to, result.static_files)
        total_edits = 0
        for f, count in changes.items():
            print(f"    {f}: {count} replacement(s)")
            total_edits += count
        if total_edits == 0:
            print(_yellow("  WARNING: no text replacements were actually performed!"))
        else:
            print(f"  Total replacements across {len(changes)} file(s): {total_edits}")
    except Exception as e:
        print(_red(f"  ERROR during rename: {e}"))
        restore_snapshot(snapshot, repo_root)
        cleanup_snapshot(snapshot)
        return 1

    # ── 5. VERIFY ─────────────────────────────────────────────────────────
    action_desc = f"Rename symbol '{symbol}' → '{to}' across codebase"
    return _verify_step(repo_root, test_cmd, snapshot, symbol,
                        result.dynamic_risk_files, action_desc=action_desc,
                        changed_files=result.static_files)


def do_extract(repo_root: str, rel_file: str, start: int, end: int,
               name: str, test_cmd: str, dry_run: bool = False) -> int:
    repo_root = os.path.abspath(repo_root)
    filepath = os.path.join(repo_root, rel_file)

    # ── 1. MAP ────────────────────────────────────────────────────────────
    print("=" * 60)
    print("  STEP 1: MAP")
    print("  → Locating the exact code block so we can lift it safely...")
    print(f"  (Technical) analyzing block {start}-{end} of {rel_file}")
    print("=" * 60)
    if not os.path.isfile(filepath):
        print(_red(f"ERROR: file not found: {filepath}"))
        return 2

    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()

    plan = analyze_block(source, start, end)
    if plan is None:
        print(_red(f"ERROR: lines {start}-{end} are empty or outside the file."))
        return 2

    print(f"  Block found inside function '{plan.enclosing_function_name}'")
    print(f"  Extracting it into a new function named '{name}'")
    print("  Derived parameters : ", plan.parameters or "(none)")
    print("  Values passed back : ", plan.returned or "(none)")

    # ── 2. WARN ───────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  STEP 2: WARN — check before changing anything")
    print("  → Checking inputs, outputs, and side-effects before changing anything...")
    print("  (Technical) analyzing extracted block dependencies (nothing changed yet)")
    print("=" * 60)
    if plan.returned:
        print("  The extracted function will return:"
              f" {', '.join(plan.returned)}")
        print("  The block will be replaced with a call that unpacks that.")
    else:
        print("  The block has no outward effect on the enclosing function.")
    print("  Only one file is edited; the test suite will confirm behavior.")

    if dry_run:
        print()
        print(_yellow("=" * 60))
        print(_yellow("DRY-RUN SUMMARY — no changes were made to disk"))
        print(_yellow(f"What you asked to do: Extract lines {start}-{end} of {rel_file} into function '{name}'"))
        print(_yellow(f"Files that would be changed: {rel_file}"))
        print(_yellow("Risky files flagged/skipped: (none)"))
        print(_yellow("Final outcome: DRY-RUN COMPLETED (Snapshot, Act, and Verify steps skipped)"))
        print(_yellow("=" * 60))
        return 0

    # ── 3. SNAPSHOT ───────────────────────────────────────────────────────
    snapshot = _snapshot_step(repo_root)

    # ── 4. ACT ────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  STEP 4: ACT")
    print("  → Applying the change to the files I'm confident about...")
    print(f"  (Technical) extracting block to '{name}'")
    print("=" * 60)
    try:
        rel, _plan = extract_into_file(repo_root, rel_file, start, end, name)
        print(f"    {rel}: extracted lines {start}-{end} → def {name}(…)")
    except Exception as e:
        print(_red(f"  ERROR during extraction: {e}"))
        restore_snapshot(snapshot, repo_root)
        cleanup_snapshot(snapshot)
        return 1

    # ── 5. VERIFY ─────────────────────────────────────────────────────────
    action_desc = f"Extract lines {start}-{end} of {rel_file} into function '{name}'"
    return _verify_step(repo_root, test_cmd, snapshot, name, [],
                        action_desc=action_desc, changed_files=[rel_file])


def do_move(repo_root: str, symbol: str, source: str, target: str,
            test_cmd: str, dry_run: bool = False) -> int:
    repo_root = os.path.abspath(repo_root)

    # ── 1. MAP ────────────────────────────────────────────────────────────
    print("=" * 60)
    print("  STEP 1: MAP")
    print("  → Looking through the entire project to find every place this code is used...")
    print(f"  (Technical) scanning for references to '{symbol}'")
    print("=" * 60)
    if not os.path.isdir(repo_root):
        print(_red(f"ERROR: repo root does not exist: {repo_root}"))
        return 2

    result = scan_repo(repo_root, symbol)
    print("  Static references found in:")
    if result.static_files:
        for f in result.static_files:
            print(f"    - {f}")
    else:
        print("    (none)")
    print("  Dynamic-risk references found in:")
    if result.dynamic_risk_files:
        for f in result.dynamic_risk_files:
            print(f"    - {f}")
    else:
        print("    (none)")

    _print_blast_radius(repo_root, symbol)

    if not os.path.isfile(os.path.join(repo_root, source)):
        print(_red(f"ERROR: source file not found: {source}"))
        return 2
    with open(os.path.join(repo_root, source), "r", encoding="utf-8") as f:
        src_text = f.read()
    from .move_symbol import find_top_level_definition
    if find_top_level_definition(src_text, symbol) is None:
        print(_red(f"ERROR: no top-level definition named '{symbol}' in {source}"))
        return 2

    print(f"\n  Move plan: '{symbol}' from {source} → {target}")

    # ── 2. WARN ───────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  STEP 2: WARN")
    print("  → Found some risky spots where the name is only used as text (not real code) —")
    print("    these can't be safely auto-changed, so I'll flag them instead of guessing.")
    print("  (Technical) dynamic-risk check (nothing changed yet)")
    print("=" * 60)
    if result.has_dynamic_risk:
        print(_yellow(f"  ⚠ WARNING: '{symbol}' appears inside string literals in:"))
        for f in result.dynamic_risk_files:
            print(_yellow(f"    - {f}"))
        if language_of_files(result.dynamic_risk_files) == {"javascript"}:
            print(_yellow("  Those dynamic references (e.g. obj['name']) cannot be "
                          "rewritten automatically."))
        else:
            print(_yellow("  Those dynamic references (e.g. getattr(obj, 'name')) "
                          "cannot be rewritten automatically."))
    else:
        print(_green("  No dynamic-risk references detected — safe to proceed."))

    if dry_run:
        print()
        print(_yellow("=" * 60))
        print(_yellow("DRY-RUN SUMMARY — no changes were made to disk"))
        print(_yellow(f"What you asked to do: Move symbol '{symbol}' from {source} → {target}"))
        if result.static_files:
            print(_yellow(f"Files that would be changed: {', '.join(result.static_files)}"))
        else:
            print(_yellow(f"Files that would be changed: {source}, {target}"))
        if result.dynamic_risk_files:
            print(_yellow(f"Risky files flagged/skipped: {', '.join(result.dynamic_risk_files)}"))
        else:
            print(_yellow("Risky files flagged/skipped: (none)"))
        print(_yellow("Final outcome: DRY-RUN COMPLETED (Snapshot, Act, and Verify steps skipped)"))
        print(_yellow("=" * 60))
        return 0

    # ── 3. SNAPSHOT ───────────────────────────────────────────────────────
    snapshot = _snapshot_step(repo_root)

    # ── 4. ACT ────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  STEP 4: ACT")
    print("  → Applying the change to the files I'm confident about...")
    print(f"  (Technical) moving '{symbol}' to {target}")
    print("=" * 60)
    try:
        changes = apply_move_symbol(repo_root, symbol, source, target)
        for rel, desc in changes.items():
            print(f"    {rel}: {desc}")
    except Exception as e:
        print(_red(f"  ERROR during move: {e}"))
        restore_snapshot(snapshot, repo_root)
        cleanup_snapshot(snapshot)
        return 1

    # ── 5. VERIFY ─────────────────────────────────────────────────────────
    action_desc = f"Move symbol '{symbol}' from {source} → {target}"
    return _verify_step(repo_root, test_cmd, snapshot, symbol,
                        result.dynamic_risk_files, action_desc=action_desc,
                        changed_files=list(changes.keys()))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "rename":
        code = do_rename(args.repo_root, args.symbol, args.to, args.test_cmd,
                         dry_run=args.dry_run)
        return code
    elif args.command == "extract-function":
        code = do_extract(args.repo_root, args.file, args.start_line,
                          args.end_line, args.name, args.test_cmd,
                          dry_run=args.dry_run)
        return code
    elif args.command == "move-symbol":
        code = do_move(args.repo_root, args.symbol, args.source,
                       args.target, args.test_cmd,
                       dry_run=args.dry_run)
        return code
    return 0


if __name__ == "__main__":
    sys.exit(main())