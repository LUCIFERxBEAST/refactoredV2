"""
test_integrity.py — Test weakening detection (Phase 5, MPG-005).

Flags, for changed Python test files:
  deleted tests, newly skipped tests, softened assertions, changed expected
  values, and assertions hidden behind comments / constant-false branches.
"""

from __future__ import annotations

import ast
import re
from typing import Dict, List, Set, Tuple

from . import models
from .patch_parser import Patch, is_test_file

_SKIP_DECORATORS = ("pytest.mark.skip", "pytest.mark.xfail", "unittest.skip",
                    "pytest.mark.skipif")
_SKIP_CALLS = ("pytest.skip", "self.skipTest", "skipTest")

_OP_NAMES = {
    "Eq": "==", "NotEq": "!=", "Lt": "<", "LtE": "<=",
    "Gt": ">", "GtE": ">=", "In": "in", "NotIn": "not in",
    "Is": "is", "IsNot": "is not",
}

_COMMENT_ASSERT = re.compile(r"^\s*#.*\b(assert|assertEqual|assertTrue)\b")


def _test_names(source: str) -> Dict[str, ast.FunctionDef]:
    """test function name -> node (top-level or methods starting with test_)."""
    out: Dict[str, ast.FunctionDef] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name.startswith("test_"):
            out[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and sub.name.startswith("test_"):
                    out[f"{node.name}.{sub.name}"] = sub
    return out


def _decorators(fn) -> List[str]:
    out: List[str] = []
    for dec in getattr(fn, "decorator_list", []):
        if hasattr(ast, "unparse"):
            try:
                out.append(ast.unparse(dec))
                continue
            except Exception:
                pass
        out.append(ast.dump(dec))
    return out


def _has_skip_call(fn) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if any(name == s or name.endswith("." + s) for s in _SKIP_CALLS):
                return True
    return False


def _assertion_ops(fn) -> List[Tuple[str, str]]:
    """(op, literal-repr) pairs extracted from assertions in fn."""
    out: List[Tuple[str, str]] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            test = node.test
            if isinstance(test, ast.Compare):
                for op, comp in zip(test.ops, test.comparators):
                    val = _lit(comp)
                    if val is not None:
                        out.append(
                            (_OP_NAMES.get(type(op).__name__, type(op).__name__), val))
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            if name in ("assertEqual", "assertEquals", "assertNotEqual",
                        "assertGreater", "assertGreaterEqual",
                        "assertLess", "assertLessEqual"):
                if len(node.args) >= 2:
                    val = _lit(node.args[1])
                    if val is not None:
                        out.append((name, val))
    return out


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        parts = []
        cur = node.func
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def _lit(node) -> str:
    try:
        if isinstance(node, ast.Constant):
            return repr(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant) \
                and not isinstance(node.operand.value, str):
            return repr(-node.operand.value)
    except Exception:
        pass
    return None
def run_test_integrity(patch: Patch) -> List[models.Finding]:
    findings: List[models.Finding] = []
    for rel in patch.changed_files:
        if not is_test_file(rel) or not rel.endswith(".py"):
            continue
        base_text = patch.base_files.get(rel) or ""
        cand_text = patch.cand_files.get(rel) or ""

        base_tests = _test_names(base_text)
        cand_tests = _test_names(cand_text)

        # ---- deleted tests -------------------------------------------------
        deleted = [n for n in base_tests if n not in cand_tests]
        for name in deleted:
            findings.append(_finding(
                "MPG-005", "Deleted test — coverage was removed", models.SEVERITY_HIGH,
                models.CLASS_TEST_WEAKENING,
                f"Test {name!r} was deleted. Removing a failing test hides "
                "regressions instead of fixing them.",
                rel, name,
                evidence=_source_excerpt(base_text, base_tests[name]),
            ))

        # ---- skipped / weakened tests -------------------------------------
        common = [n for n in base_tests if n in cand_tests]
        for name in common:
            base_fn, cand_fn = base_tests[name], cand_tests[name]
            new_d = set(_decorators(cand_fn)) - set(_decorators(base_fn))
            skip_added = any(d.startswith(_SKIP_DECORATORS) for d in new_d)
            if skip_added or (_has_skip_call(cand_fn) and not _has_skip_call(base_fn)):
                findings.append(_finding(
                    "MPG-005", "Test skipped or marked xfail", models.SEVERITY_HIGH,
                    models.CLASS_TEST_WEAKENING,
                    f"Test {name!r} was given a skip/xfail marker or a skip call.",
                    rel, name,
                    evidence="decorator added: " + ", ".join(sorted(new_d)),
                ))

            base_ops = _assertion_ops(base_fn)
            cand_ops = _assertion_ops(cand_fn)
            if base_ops and not cand_ops:
                findings.append(_finding(
                    "MPG-005", "Assertion removed from test", models.SEVERITY_MEDIUM,
                    models.CLASS_TEST_WEAKENING,
                    f"Test {name!r} contained assertions that are now gone; the "
                    "test is weaker (e.g. `assert x == y` -> bare `assert x`).",
                    rel, name,
                    evidence=f"old assertions: {base_ops}",
                ))
            elif len(cand_ops) < len(base_ops):
                findings.append(_finding(
                    "MPG-005", "Fewer assertions after the change", models.SEVERITY_MEDIUM,
                    models.CLASS_TEST_WEAKENING,
                    f"Test {name!r} lost an assertion ({len(base_ops)} -> "
                    f"{len(cand_ops)}).",
                    rel, name,
                    evidence=f"removed: {sorted(set(base_ops) - set(cand_ops))}",
                ))

            base_map = _op_literals(base_ops)
            cand_map = _op_literals(cand_ops)
            for key in sorted(base_map.keys() & cand_map.keys()):
                if base_map[key] != cand_map[key]:
                    findings.append(_finding(
                        "MPG-005", "Expected value changed in test",
                        models.SEVERITY_MEDIUM, models.CLASS_TEST_WEAKENING,
                        f"Assertion {key} in {name!r} changed expected value "
                        f"{base_map[key]} -> {cand_map[key]}.",
                        rel, name,
                        evidence=f"old={base_map[key]} new={cand_map[key]}",
                    ))

        # ---- assertions hidden behind comments ----------------------------
        base_comments = {ln.strip() for ln in base_text.splitlines()
                         if ln.lstrip().startswith("#")}
        for ln in cand_text.splitlines():
            stripped = ln.strip()
            if stripped.startswith("#") and stripped not in base_comments:
                if _COMMENT_ASSERT.match(stripped):
                    findings.append(_finding(
                        "MPG-005", "Assertion commented out in test",
                        models.SEVERITY_HIGH, models.CLASS_TEST_WEAKENING,
                        "An assertion was added as a comment line in the test file.",
                        rel, "", evidence=stripped[:200],
                    ))

    return findings


def _op_literals(ops: List[Tuple[str, str]]) -> Dict[str, Set[str]]:
    out: Dict[str, Set[str]] = {}
    for op, val in ops:
        out.setdefault(op, set()).add(val)
    return out


def _source_excerpt(source: str, node) -> str:
    try:
        seg = ast.get_source_segment(source, node)
    except (TypeError, ValueError):
        seg = None
    return "\n".join([ln.rstrip() for ln in (seg or "").splitlines()[:8]])


def _finding(rule_id, title, severity, classification, description, file, symbol,
             evidence=""):
    return models.Finding(
        rule_id=rule_id, title=title, severity=severity,
        classification=classification, description=description,
        evidence=evidence[:1000], file=file, symbol=symbol,
        recommended_action=(
            "Restore the original assertions; tests should be changed only to "
            "reflect *relative* improvements, never to hide regressions."),
    )