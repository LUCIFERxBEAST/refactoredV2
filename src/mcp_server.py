"""src/mcp_server.py

MCP server exposing Refactor Guard operations as tools for AI coding assistants
(Claude Desktop, Cursor, Cline, etc.).
"""

from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

# Support both FastMCP in mcp 1.x and MCPServer in mcp 2.x
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    try:
        from mcp.server.mcpserver import MCPServer as FastMCP
    except ImportError:  # pragma: no cover
        class FastMCP:  # type: ignore
            def __init__(self, name: str):
                self.name = name

            def tool(self):
                def decorator(fn):
                    return fn
                return decorator

            def run(self, *args, **kwargs):
                print(f"MCP server '{self.name}' - mcp package not installed.")

from . import main as cli_main
from .minimal_patch_guard import review_patch as mpg_review, reporter as mpg_reporter
from .minimal_patch_guard import models as mpg_models

mcp = FastMCP("refactor-guard")


def _run_with_captured_output(func, *args, **kwargs) -> str:
    """Execute a Refactor Guard workflow while capturing all stdout and stderr."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        try:
            exit_code = func(*args, **kwargs)
        except Exception as e:
            buf.write(f"\nUnhandled exception during refactor execution: {e}\n")
            exit_code = 1
    output = buf.getvalue()
    status_tag = "SUCCESS" if exit_code == 0 else f"FAILURE (exit code {exit_code})"
    return f"[{status_tag}]\n\n{output}"


@mcp.tool()
def refactor_guard_rename(
    repo_root: str,
    symbol: str,
    to: str,
    test_cmd: str,
    dry_run: bool = False,
) -> str:
    """Safely rename a symbol across a repository with blast radius mapping,
    dynamic-risk warnings, snapshot rollback on test failure, and self-heal diagnosis.

    CRITICAL AGENT INSTRUCTION:
    When proposing fixes for failed refactors, you MUST generate general, algorithmic 
    solutions. DO NOT use hardcoded workarounds (e.g., special-casing specific inputs, 
    adding 'if input == X: return Y', or bypassing logic just to make tests pass).
    Ensure fixes apply to the overall architecture, not just the failing test case.

    Args:
        repo_root: Path to the target repository.
        symbol: Old symbol name to rename.
        to: New symbol name.
        test_cmd: Test suite command to verify (e.g. 'pytest -q' or 'node --test').
        dry_run: If True, simulates MAP and WARN steps without editing files or running tests.
    """
    return _run_with_captured_output(
        cli_main.do_rename,
        repo_root=str(repo_root),
        symbol=str(symbol),
        to=str(to),
        test_cmd=str(test_cmd),
        dry_run=bool(dry_run),
    )

@mcp.tool()
def refactor_guard_extract_function(
    repo_root: str,
    rel_file: str,
    start_line: int,
    end_line: int,
    name: str,
    test_cmd: str,
    dry_run: bool = False,
) -> str:
    """Safely extract a block of Python code into a new function with AST variable
    flow analysis, automated parameters and return values, and test verification.

    CRITICAL AGENT INSTRUCTION:
    When proposing fixes for failed refactors, you MUST generate general, algorithmic 
    solutions. DO NOT use hardcoded workarounds (e.g., special-casing specific inputs).
    Ensure fixes apply to the overall architecture, not just the failing test case.

    Args:
        repo_root: Path to the target repository.
        rel_file: Python file (relative to repo root) containing the block.
        start_line: First line of the block (1-based, inclusive).
        end_line: Last line of the block (1-based, inclusive).
        name: Name for the new function.
        test_cmd: Test suite command to verify (e.g. 'pytest -q').
        dry_run: If True, analyzes and plans extraction without modifying files or running tests.
    """
    err = cli_main.check_supported_extension("extract-function", rel_file)
    if err:
        return f"[FAILURE (exit code 2)]\n\n{err}\n"
    return _run_with_captured_output(
        cli_main.do_extract,
        repo_root=str(repo_root),
        rel_file=str(rel_file),
        start=int(start_line),
        end=int(end_line),
        name=str(name),
        test_cmd=str(test_cmd),
        dry_run=bool(dry_run),
    )
    
@mcp.tool()
def refactor_guard_move_symbol(
    repo_root: str,
    symbol: str,
    source: str,
    target: str,
    test_cmd: str,
    dry_run: bool = False,
) -> str:
    """Safely move a top-level symbol (function or class) from one module to another,
    automatically updating imports and references across the entire repository.

    CRITICAL AGENT INSTRUCTION:
    When proposing fixes for failed refactors, you MUST generate general, algorithmic 
    solutions. DO NOT use hardcoded workarounds (e.g., special-casing specific inputs).
    Ensure fixes apply to the overall architecture, not just the failing test case.

    Args:
        repo_root: Path to the target repository.
        symbol: Name of the top-level function/class to move.
        source: Source Python file (relative to repo root).
        target: Target Python file (relative to repo root); created if needed.
        test_cmd: Test suite command to verify (e.g. 'pytest -q').
        dry_run: If True, scans dependencies and simulates move without editing files or running tests.
    """
    for f in (source, target):
        err = cli_main.check_supported_extension("move-symbol", f)
        if err:
            return f"[FAILURE (exit code 2)]\n\n{err}\n"
    return _run_with_captured_output(
        cli_main.do_move,
        repo_root=str(repo_root),
        symbol=str(symbol),
        source=str(source),
        target=str(target),
        test_cmd=str(test_cmd),
        dry_run=bool(dry_run),
    )

@mcp.tool()
def refactor_guard_history(
    repo_root: str,
    symbol: str = "",
    limit: int = 0,
) -> str:
    """Show prior refactor history and rollback records for a repository.

    Args:
        repo_root: Path to the target repository.
        symbol: Optional symbol name to filter history for.
        limit: Optional maximum number of recent records to return (0 = all).
    """
    sym_arg = symbol if symbol else None
    lim_arg = limit if limit > 0 else None
    return _run_with_captured_output(
        cli_main.do_history,
        repo_root=str(repo_root),
        symbol=sym_arg,
        limit=lim_arg,
    )


# --------------------------------------------------------------------------
# Minimal Patch Guard tools (structured JSON, unlike the legacy prose tools)
# --------------------------------------------------------------------------

def _json_body(data) -> str:
    """Serialize a payload as pretty-printed structured JSON."""
    import json
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def refactor_guard_review_patch(
    repo_root: str,
    base_ref: str = "HEAD",
    test_cmd: str = "pytest -q",
    strict_minimality: bool = False,
    max_files_changed: int | None = None,
    max_lines_changed: int | None = None,
    require_approval: bool = False,
    run_generalization: bool = False,
    operation: str | None = None,
) -> str:
    """Run the Minimal Patch Guard on the current tree vs a git ref or a base
    folder and return the full review as structured JSON.

    Detects over-fit patches (hard-coded outputs, test-specific branches,
    removed input dependencies, weakened/deleted tests, exception suppression,
    logic bypass, disabled checks, unrelated changes) and cross-checks them
    with a baseline-vs-candidate verification matrix.

    Args:
        repo_root: Path to the target repository.
        base_ref: Git ref to diff against (default 'HEAD') or a directory
            containing the base snapshot.
        test_cmd: Verification command run against both trees (default
            'pytest -q'). Use '' to skip running tests.
        strict_minimality: Reject any patch with unrelated/expanded changes.
        max_files_changed: Cap on changed files before scope-expansion flags.
        max_lines_changed: Cap on changed lines before scope-expansion flags.
        require_approval: Force a 'require approval' decision where borderline.
        run_generalization: Probe changed pure functions on edge/metamorphic
            inputs and compare base vs candidate behaviour.
        operation: Declared operation ('rename', 'extract-function',
            'move-symbol') to check footprint expectations.
    """
    try:
        review = mpg_review(
            repo_root=str(repo_root), base_ref=str(base_ref),
            test_cmd=(str(test_cmd) if test_cmd else ""),
            strict_minimality=bool(strict_minimality) or None,
            max_files_changed=int(max_files_changed) if max_files_changed else None,
            max_lines_changed=int(max_lines_changed) if max_lines_changed else None,
            require_approval=bool(require_approval) or None,
            run_generalization=bool(run_generalization) or None,
            skip_generalization=None,
            operation=str(operation) if operation else None,
            output_format="json",
        )
        return mpg_reporter.render_json(review)
    except Exception as exc:
        return mpg_reporter.render_json({
            "error": f"MPG review failed: {exc}",
            "decision": "reject",
        })


@mcp.tool()
def refactor_guard_check_minimality(
    repo_root: str,
    base_ref: str = "HEAD",
    max_files_changed: int | None = None,
    max_lines_changed: int | None = None,
    operation: str | None = None,
) -> str:
    """Focus the Minimal Patch Guard on patch minimality/scope and return JSON.

    Detects unrelated changed files, scope expansions over the configured caps,
    and footprint violations for a declared operation. No test suite is run.

    Args:
        repo_root: Path to the target repository.
        base_ref: Git ref or base-folder directory to diff against.
        max_files_changed: Cap on changed files.
        max_lines_changed: Cap on changed lines.
        operation: Declared operation to check ('rename', 'extract-function',
            'move-symbol').
    """
    try:
        review = mpg_review(
            repo_root=str(repo_root), base_ref=str(base_ref), test_cmd="",
            max_files_changed=int(max_files_changed) if max_files_changed else None,
            max_lines_changed=int(max_lines_changed) if max_lines_changed else None,
            operation=str(operation) if operation else None,
            output_format="json",
        )
        scope_metrics = next(
            (g.metrics for g in review.metric_groups if g.name == "scope_metrics"), {})
        return _json_body({
            "patch": {
                "scope": review.scope,
                "changed_files": review.changed_files,
                "scope_metrics": scope_metrics,
            },
            "findings": [f.to_dict() for f in review.findings
                         if f.classification in (mpg_models.CLASS_UNRELATED_CHANGE,
                                                 mpg_models.CLASS_SCOPE_EXPANSION)],
            "score": review.score,
            "decision": review.decision,
        })
    except Exception as exc:
        return _json_body({"error": f"minimality check failed: {exc}"})


@mcp.tool()
def refactor_guard_check_generalization(
    repo_root: str,
    base_ref: str = "HEAD",
    test_cmd: str = "pytest -q",
) -> str:
    """Run the Minimal Patch Guard generalization probes (edge / metamorphic /
    differential) and return JSON.

    Pure changed Python functions are executed in a subprocess harness over
    canonical edge inputs plus literals found in the code/tests; base and
    candidate outputs are compared. Behavioural differences are reported as
    'uncovered_variation'.

    Args:
        repo_root: Path to the target repository.
        base_ref: Git ref or base-folder directory to diff against.
        test_cmd: Verification command (default 'pytest -q'); use '' to skip.
    """
    try:
        review = mpg_review(
            repo_root=str(repo_root), base_ref=str(base_ref),
            test_cmd=(str(test_cmd) if test_cmd else ""),
            run_generalization=True, output_format="json",
        )
        return _json_body({
            "generalization": review.generalization.to_dict(),
            "affected_findings": [f.to_dict() for f in review.findings
                                  if f.symbol in review.generalization.intended_symbols
                                  or f.classification in (
                                      mpg_models.CLASS_SUSPICIOUS_CONSTANT,
                                      mpg_models.CLASS_TEST_SPECIFIC_HARDCODING)],
            "score": review.score,
            "decision": review.decision,
        })
    except Exception as exc:
        return _json_body({"error": f"generalization probe failed: {exc}"})


@mcp.tool()
def refactor_guard_compare_runs(
    repo_root: str,
    base_ref: str = "HEAD",
    test_cmd: str = "pytest -q",
) -> str:
    """Compare baseline vs candidate verification runs and return JSON.

    Materializes the base tree (git archive or base folder), runs parse +
    compile + targeted + full tests on both trees, and reports which failures
    are new, resolved, or still failing.

    Args:
        repo_root: Path to the target repository.
        base_ref: Git ref or base-folder directory to diff against.
        test_cmd: Verification command (default 'pytest -q').
    """
    try:
        review = mpg_review(
            repo_root=str(repo_root), base_ref=str(base_ref),
            test_cmd=(str(test_cmd) if test_cmd else ""),
            skip_generalization=True, output_format="json",
        )
        return _json_body({"verification": review.verification.to_dict()})
    except Exception as exc:
        return _json_body({"error": f"verification comparison failed: {exc}"})


@mcp.prompt()
def strict_refactoring_guidelines() -> str:
    """Load the project's strict anti-hardcoding and safety guidelines."""
    return """
    # Refactor Guard: Agent Constraints
    You are operating within the Refactor Guard safety harness. 
    
    1. GENERALITY MANDATE: Never write hardcoded logic, mock-style bypasses, or if/else branches tailored to specific test inputs.
    2. ARCHITECTURAL FIXES: If a dynamic reference breaks, fix the mechanism (e.g., dynamically resolving the new symbol string), do not hardcode the expected output.
    3. FAIL FAST: If a general solution cannot be found, explain why rather than forcing a narrow fix.
    """

    
# Backward-compatible tool aliases
@mcp.tool()
def refactor_rename(
    repo_root: str,
    symbol: str,
    to: str,
    test_cmd: str,
    dry_run: bool = False,
) -> str:
    """Alias for refactor_guard_rename."""
    return refactor_guard_rename(repo_root, symbol, to, test_cmd, dry_run=dry_run)


@mcp.tool()
def refactor_extract_function(
    repo_root: str,
    file: str,
    start_line: int,
    end_line: int,
    name: str,
    test_cmd: str,
    dry_run: bool = False,
) -> str:
    """Alias for refactor_guard_extract_function."""
    return refactor_guard_extract_function(
        repo_root, rel_file=file, start_line=start_line,
        end_line=end_line, name=name, test_cmd=test_cmd,
        dry_run=dry_run
    )


@mcp.tool()
def refactor_move_symbol(
    repo_root: str,
    symbol: str,
    source: str,
    target: str,
    test_cmd: str,
    dry_run: bool = False,
) -> str:
    """Alias for refactor_guard_move_symbol."""
    return refactor_guard_move_symbol(
        repo_root, symbol=symbol, source=source,
        target=target, test_cmd=test_cmd, dry_run=dry_run
    )


@mcp.tool()
def refactor_history(
    repo_root: str,
    symbol: str = "",
    limit: int = 0,
) -> str:
    """Alias for refactor_guard_history."""
    return refactor_guard_history(repo_root, symbol=symbol, limit=limit)


@mcp.tool()
def refactor_review_patch(
    repo_root: str,
    base_ref: str = "HEAD",
    test_cmd: str = "pytest -q",
    strict_minimality: bool = False,
    max_files_changed: int | None = None,
    max_lines_changed: int | None = None,
    require_approval: bool = False,
    run_generalization: bool = False,
    operation: str | None = None,
) -> str:
    """Alias for refactor_guard_review_patch."""
    return refactor_guard_review_patch(
        repo_root=repo_root,
        base_ref=base_ref,
        test_cmd=test_cmd,
        strict_minimality=strict_minimality,
        max_files_changed=max_files_changed,
        max_lines_changed=max_lines_changed,
        require_approval=require_approval,
        run_generalization=run_generalization,
        operation=operation,
    )


@mcp.tool()
def refactor_check_minimality(
    repo_root: str,
    base_ref: str = "HEAD",
    max_files_changed: int | None = None,
    max_lines_changed: int | None = None,
    operation: str | None = None,
) -> str:
    """Alias for refactor_guard_check_minimality."""
    return refactor_guard_check_minimality(
        repo_root=repo_root,
        base_ref=base_ref,
        max_files_changed=max_files_changed,
        max_lines_changed=max_lines_changed,
        operation=operation,
    )


@mcp.tool()
def refactor_check_generalization(
    repo_root: str,
    base_ref: str = "HEAD",
    test_cmd: str = "pytest -q",
) -> str:
    """Alias for refactor_guard_check_generalization."""
    return refactor_guard_check_generalization(
        repo_root=repo_root,
        base_ref=base_ref,
        test_cmd=test_cmd,
    )


@mcp.tool()
def refactor_compare_runs(
    repo_root: str,
    base_ref: str = "HEAD",
    test_cmd: str = "pytest -q",
) -> str:
    """Alias for refactor_guard_compare_runs."""
    return refactor_guard_compare_runs(
        repo_root=repo_root,
        base_ref=base_ref,
        test_cmd=test_cmd,
    )


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()


