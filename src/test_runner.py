"""
test_runner.py — VERIFY logic for Refactor Guard

Runs the target repo's test suite (e.g. pytest) via subprocess, parses the
failure output for missing-symbol names, and produces a diagnosis including
a note if the missing symbol matches something from the dynamic-risk list.
"""

import os
import re
import shlex
import subprocess
import sys
from typing import List, Optional, Tuple


def build_command(test_cmd: str) -> List[str]:
    """Parse a test command string into a list of arguments."""
    try:
        parts = shlex.split(test_cmd)
    except ValueError:
        parts = test_cmd.split()

    # Launch pytest through the same interpreter that runs the CLI, so the
    # right environment is always used.
    if parts and parts[0] == "pytest":
        return [sys.executable, "-m", "pytest"] + parts[1:]

    return parts


def run_tests(
    repo_root: str,
    test_cmd: str,
) -> Tuple[bool, str, int]:
    """
    Run the test command in repo_root.
    Returns (passed, output, returncode).
    """
    cmd = build_command(test_cmd)

    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        return False, f"ERROR: command not found: {cmd}", 127
    except subprocess.TimeoutExpired:
        return False, "ERROR: tests timed out after 300 seconds", 124

    output = proc.stdout + proc.stderr
    return proc.returncode == 0, output, proc.returncode


# Patterns for missing-symbol errors I want to catch in test output
_NAME_ERROR_PATTERN = re.compile(
    r"NameError:\s*name\s+'([^']+)'"
)
_ATTRIBUTE_ERROR_PATTERN = re.compile(
    r"AttributeError:\s*[^']*'([^']+)'[^']*has no attribute\s+'([^']+)'"
)
_IMPORT_ERROR_PATTERN = re.compile(
    r"ImportError:\s*cannot import name\s+'([^']+)'[^']*from\s+'([^']+)'"
    r"|ImportError:\s*cannot import name\s+'([^']+)'\s+from\s+'([^']+)'"
)
# JavaScript runtime errors (Node test runner output)
_JS_TYPE_ERROR_PATTERN = re.compile(
    r"TypeError:\s*([\w$][\w$.]*) is not a function"
)
_JS_REFERENCE_ERROR_PATTERN = re.compile(
    r"ReferenceError:\s*([\w$][\w$.]*) is not defined"
)


def _js_name_matches(dotted_name: str, symbol: str) -> bool:
    """Whether a dotted JS name refers to the renamed symbol.

    Handles both a bare name (`computeTotal`) and names reached through a
    member chain (`mathutils.computeTotal`).
    """
    return dotted_name == symbol or symbol in dotted_name.split('.')


def language_of_files(paths: List[str]) -> set:
    """Language families referenced by files, inferred from their extension.

    Returns a set containing 'python' and/or 'javascript'. Unknown
    extensions are ignored.
    """
    langs = set()
    for p in paths:
        ext = os.path.splitext(p)[1].lower()
        if ext == ".py":
            langs.add("python")
        elif ext in (".js", ".ts"):
            langs.add("javascript")
    return langs


def _dynamic_example(langs) -> str:
    """Human-readable dynamic-access example for the given languages."""
    if langs == {"javascript"}:
        return "obj['symbol'] — bracket-notation member access"
    if langs == {"python"}:
        return "getattr(obj, 'symbol')"
    return "getattr(obj, 'symbol') or obj['symbol']"


def find_missing_symbols(test_output: str, symbol: str) -> List[str]:
    """
    Parse test failure output for missing-symbol names.
    Returns a list of (error_name, context_file) tuples, where the name matches
    the symbol we renamed, if any.
    """
    results = []

    for m in _NAME_ERROR_PATTERN.finditer(test_output):
        name = m.group(1)
        if name == symbol:
            results.append((name, None))

    for m in _ATTRIBUTE_ERROR_PATTERN.finditer(test_output):
        # Group 1 = object type, Group 2 = attribute name
        attr = m.group(2)
        if attr == symbol:
            results.append((attr, None))

    for m in _IMPORT_ERROR_PATTERN.finditer(test_output):
        name = m.group(1) or m.group(3)
        source = m.group(2) or m.group(4)
        if name == symbol:
            results.append((name, source))

    for m in _JS_TYPE_ERROR_PATTERN.finditer(test_output):
        name = m.group(1)
        if _js_name_matches(name, symbol):
            results.append((name, None))

    for m in _JS_REFERENCE_ERROR_PATTERN.finditer(test_output):
        name = m.group(1)
        if _js_name_matches(name, symbol):
            results.append((name, None))

    return results


def diagnose_failures(
    test_output: str,
    symbol: str,
    dynamic_risk_files: List[str],
) -> str:
    """
    Produce a human-readable diagnosis of test failures.
    If a missing-symbol error references the renamed symbol AND that symbol was
    in the dynamic-risk list, point at the specific file explicitly.
    """
    missing = find_missing_symbols(test_output, symbol)
    if not missing:
        return (
            "No error mentioning the renamed symbol was found. "
            "Review the test output above for other potential issues."
        )

    # Deduplicate: two failing tests often crash on the same missing name.
    seen = set()
    unique_missing = []
    for name, source in missing:
        key = (name, source)
        if key in seen:
            continue
        seen.add(key)
        unique_missing.append((name, source))
    missing = unique_missing

    lines = []
    lines.append("The test failures reference the renamed symbol "
                 f"'{symbol}':")
    for name, source in missing:
        lines.append(f"  - '{name}' is missing")
        if source:
            lines.append(f"    (could not import from '{source}')")

    # Link to dynamic-risk files
    matching_dynamic = dynamic_risk_files
    if matching_dynamic:
        lines.append("")
        lines.append(">>> Likely caused by the dynamic reference in:")
        for f in matching_dynamic:
            lines.append(f"    {f}")
        example = _dynamic_example(language_of_files(matching_dynamic))
        lines.append(
            ">>> The symbol name is used inside a string literal there "
            f"(e.g. {example}), so it was deliberately not renamed and now "
            "points at code that no longer exists."
        )
    else:
        lines.append(
            "No dynamic-risk references were detected during the scan. "
            "The failure is likely due to an incomplete rename elsewhere."
        )
    return "\n".join(lines)