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

    Args:
        repo_root: Path to the target repository.
        rel_file: Python file (relative to repo root) containing the block.
        start_line: First line of the block (1-based, inclusive).
        end_line: Last line of the block (1-based, inclusive).
        name: Name for the new function.
        test_cmd: Test suite command to verify (e.g. 'pytest -q').
        dry_run: If True, analyzes and plans extraction without modifying files or running tests.
    """
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

    Args:
        repo_root: Path to the target repository.
        symbol: Name of the top-level function/class to move.
        source: Source Python file (relative to repo root).
        target: Target Python file (relative to repo root); created if needed.
        test_cmd: Test suite command to verify (e.g. 'pytest -q').
        dry_run: If True, scans dependencies and simulates move without editing files or running tests.
    """
    return _run_with_captured_output(
        cli_main.do_move,
        repo_root=str(repo_root),
        symbol=str(symbol),
        source=str(source),
        target=str(target),
        test_cmd=str(test_cmd),
        dry_run=bool(dry_run),
    )


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


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()

