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
#
# V8 normalizes member access when building these messages, but the exact
# shape varies by Node version and how the property was accessed:
#   TypeError: mathutils.computeTotal is not a function     (dot notation)
#   TypeError: mathutils["computeTotal"] is not a function  (bracket notation)
#   TypeError: mathutils['computeTotal'] is not a function  (bracket, single)
#   TypeError: Cannot read properties of undefined (reading 'computeTotal')
#               (when the *object* went missing, not the property)
# So capture the whole expression text and extract the identifier tokens from
# it later — that is robust to the quoting/notation the runtime happens to use.
_JS_TYPE_ERROR_PATTERN = re.compile(
    r"TypeError:\s*(.+?)\s+is not a function"
)
_JS_REFERENCE_ERROR_PATTERN = re.compile(
    r"ReferenceError:\s*(.+?)\s+is not defined"
)
_JS_READ_PROPERTY_PATTERN = re.compile(
    r"Cannot read properties of (?:undefined|null) \(reading '([^']+)'\)"
)
# Older V8 (< 9.x / Node < 15) used a different phrasing:
#   "Cannot read property 'foo' of undefined"
_JS_READ_PROPERTY_OLD = re.compile(
    r"Cannot read property '([^']+)' of (?:undefined|null)"
)

# Match ANSI color / control escape sequences (Node may colorize output).
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _clean_output(text: str) -> str:
    """Strip ANSI color/control sequences so error parsing is color-safe."""
    return _ANSI_ESCAPE.sub("", text)


def _js_tokens(expression: str) -> set:
    """Identifier-ish tokens inside a JS error expression, e.g. 'computeTotal'.

    'mathutils.computeTotal'    -> {'mathutils', 'computeTotal'}
    'mathutils["computeTotal"]' -> {'mathutils', 'computeTotal'}
    """
    return set(re.findall(r"[A-Za-z_$][\w$]*", expression))


def _js_name_matches(expression: str, symbol: str) -> bool:
    """Whether a JS error expression refers to the renamed symbol.

    Handles dot notation (`mathutils.computeTotal`), bracket notation
    (`mathutils["computeTotal"]`), and bare names (`computeTotal`).
    """
    return symbol in _js_tokens(expression)


def _dynamic_files_in_output(test_output: str,
                             dynamic_risk_files: List[str]) -> List[str]:
    """Dynamic-risk file paths referenced in test output (e.g. stack traces).

    Normalizes path separators so Windows stack frames (`pkg\\dynamic_call.js`)
    match the relative paths from the MAP scan (`pkg/dynamic_call.js`).
    """
    normalized = test_output.replace("\\", "/")
    return [f for f in dynamic_risk_files
            if f.replace("\\", "/") in normalized]


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
    test_output = _clean_output(test_output)

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
        name = m.group(1).strip()
        if _js_name_matches(name, symbol):
            results.append((name, None))

    for m in _JS_REFERENCE_ERROR_PATTERN.finditer(test_output):
        name = m.group(1).strip()
        if _js_name_matches(name, symbol):
            results.append((name, None))

    for m in _JS_READ_PROPERTY_PATTERN.finditer(test_output):
        name = m.group(1)
        if name == symbol:
            results.append((name, None))

    for m in _JS_READ_PROPERTY_OLD.finditer(test_output):
        name = m.group(1)
        if name == symbol:
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
        # Belt-and-suspenders fallback: the symbol wasn't named in any
        # error message, but Node's stack trace may still point at one of
        # the dynamic-risk files.  This covers message-shape variants that
        # the regex above doesn't recognise (very old Node, custom reporters,
        # non-ASCII locales, etc.).
        cleaned = _clean_output(test_output)
        frame_files = _dynamic_files_in_output(cleaned, dynamic_risk_files)
        if frame_files:
            lines = [
                "The test output does not mention the renamed symbol directly, but"
                " the failure stack trace points into a file that was flagged as a"
                " dynamic-risk reference during MAP:",
                "",
                ">>> Likely caused by the dynamic reference in:",
            ]
            for f in frame_files:
                lines.append(f"    {f}")
            lines.append(
                ">>> The symbol name is used inside a string literal there, so "
                "it was deliberately not renamed and now points at code that "
                "no longer exists."
            )
            return "\n".join(lines)

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