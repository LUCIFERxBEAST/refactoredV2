"""
static_checks.py — Level-1 static risk rules for the Minimal Patch Guard (Phase 2).

Implements the MPG rules that are detectable purely from AST / text:

  MPG-001  Constant replacement / output-only result         (suspicious_constant…)
  MPG-002  Input dependency removed                          (input_dependency_removed)
  MPG-003  Special-case / test-specific hardcoding branch    (special_case_branch /
                                                              test_specific_hardcoding)
  MPG-006  Exception suppression (try/except swallow)        (exception_suppression)
  MPG-007  Logic bypass / skipped implementation             (logic_bypass)
  MPG-008  Disabled checks (`if 0:`, commented-out asserts)  (disabled_check)

All rules are heuristic; they produce *findings* that feed the scoring model
rather than hard guarantees.
"""

from __future__ import annotations

import ast
import difflib
from typing import Dict, List, Optional, Set, Tuple

from . import ast_utils
from . import models
from .patch_parser import Patch, is_test_file


def _find(rule_id, title, severity, classification, description,
          file="", symbol="", evidence=""):
    return models.Finding(
        rule_id=rule_id, title=title, severity=severity,
        classification=classification, description=description,
        evidence=evidence[:2000], file=file, symbol=symbol,
    )


# --------------------------------------------------------------------------
# Test-literal mining (used by MPG-003 to link branches to test inputs)
# --------------------------------------------------------------------------

def collect_test_literals(patch: Patch) -> Set[str]:
    """Every string/number constant found inside changed test files (both sides)."""
    literals: Set[str] = set()
    for rel in patch.changed_files:
        if not is_test_file(rel):
            continue
        for text in (patch.base_files.get(rel), patch.cand_files.get(rel)):
            if not text:
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant):
                    if isinstance(node.value, str):
                        literals.add(repr(node.value))
                    elif isinstance(node.value, (int, float)) \
                            and not isinstance(node.value, bool):
                        literals.add(repr(float(node.value)))
    return literals
# --------------------------------------------------------------------------
# Per-function analysis
# --------------------------------------------------------------------------

def _returns_constant_set(fn) -> Set[str]:
    vals: Set[str] = set()
    for ret in ast_utils.returns_of(fn):
        if ret.value is None:
            vals.add("<none>")
            continue
        val = ast_utils.constant_value(ret.value)
        if val is ast_utils._NOT_CONSTANT:
            vals.add("<computed>")
        else:
            vals.add(repr(val))
    return vals


def _all_returns_constant(fn) -> bool:
    rets = ast_utils.returns_of(fn)
    if not rets:
        return False
    return all(
        r.value is not None and ast_utils.is_constant_node(r.value) for r in rets
    )


def _analyze_function(sym: models.ChangedSymbol, base_fn, cand_fn,
                      test_literals: Set[str], findings: List[models.Finding],
                      allowed_vars: Set[str]) -> None:
    if cand_fn is None:  # removed — handled by scope/behavior checks
        return
    base_params = set(sym.old_params)
    cand_params = set(sym.new_params)

    # ---- MPG-001 constant replacement / output-only result --------------
    cand_const = _all_returns_constant(cand_fn)
    return_vals = _returns_constant_set(cand_fn)

    if cand_const and base_fn is not None:
        base_nonconst = not _all_returns_constant(base_fn)
        base_vals = _returns_constant_set(base_fn)
        if base_nonconst:
            findings.append(_find(
                "MPG-001",
                "Constant replacement — computed output replaced by a literal",
                models.SEVERITY_HIGH, models.CLASS_SUSPICIOUS_CONSTANT,
                (f"Function {sym.name!r} previously computed its return value but "
                 f"now returns only constant literal(s) regardless of input."),
                file=sym.file, symbol=sym.name,
                evidence=f"new returns: {sorted(return_vals)}; old returns: "
                         f"{sorted(base_vals)}",
            ))
        elif return_vals and base_vals == return_vals:
            return  # legit constant change (same constant) — nothing to flag
        elif cand_params and not return_vals.issubset(base_vals):
            findings.append(_find(
                "MPG-001",
                "Output has become a constant while inputs still exist",
                models.SEVERITY_LOW, models.CLASS_SUSPICIOUS_CONSTANT,
                (f"Function {sym.name!r} now returns constant(s) {sorted(return_vals)} "
                 "despite still accepting parameters."),
                file=sym.file, symbol=sym.name,
                evidence=f"params={sorted(cand_params)} returns={sorted(return_vals)}",
            ))
    elif cand_const and base_fn is None:
        if sym.new_params and not _references_any(cand_fn):
            findings.append(_find(
                "MPG-001",
                "New function is a constant-only stub",
                models.SEVERITY_LOW, models.CLASS_SUSPICIOUS_CONSTANT,
                (f"New function {sym.name!r} accepts input but returns a fixed "
                 "constant; verify this is a deliberate stub."),
                file=sym.file, symbol=sym.name,
                evidence=f"returns={sorted(return_vals)}",
            ))

    # ---- MPG-002 input dependency removed -------------------------------
    base_usage = ast_utils.param_usage_counts(base_fn) if base_fn else {}
    cand_usage = ast_utils.param_usage_counts(cand_fn)
    removed_params = []
    for param in sorted(base_params):
        if cand_usage.get(param, 0) == 0 and base_usage.get(param, 0) > 0:
            if param in allowed_vars:
                continue  # policy-declared conditionally-allowed name
            removed_params.append(param)
    for param in removed_params:
        severity = models.SEVERITY_HIGH if cand_const else models.SEVERITY_MEDIUM
        findings.append(_find(
            "MPG-002",
            "Input dependency removed — parameter no longer used",
            severity, models.CLASS_INPUT_DEPENDENCY_REMOVED,
            (f"Parameter {param!r} of {sym.name!r} was used by the original "
             "implementation but is no longer referenced, so the candidate can "
             "ignore its input."),
            file=sym.file, symbol=sym.name,
            evidence=f"param={param} base_usages={base_usage[param]} "
                     f"candidate_usages=0",
        ))
# ---- MPG-003 special-case / test-specific branch --------------------
    base_if_dumps = _if_dumps(base_fn) if base_fn else set()
    for if_node in ast_utils.walk(cand_fn, ast.If):
        if ast.dump(if_node) in base_if_dumps:
            continue
        literal_conds = _if_param_literals(if_node)
        if not literal_conds:
            continue
        branch_const = _all_returns_constant(if_node)
        for param, op, val in literal_conds:
            if val in test_literals:
                findings.append(_find(
                    "MPG-003",
                    "Test-specific hardcoding — branch matches a literal used in tests",
                    models.SEVERITY_CRITICAL, models.CLASS_TEST_SPECIFIC_HARDCODING,
                    (f"New branch in {sym.name!r} special-cases {param} == {val}, "
                     "which matches a value used by the test suite. This pattern is "
                     "the classic over-fit: the code returns canned output for the "
                     "exact test inputs."),
                    file=sym.file, symbol=sym.name,
                    evidence=(f"{param} {op} {val}; branch returns "
                              f"{'constants' if branch_const else 'values'}"),
                ))
                continue
            findings.append(_find(
                "MPG-003",
                "Special-case branch added on a literal input",
                models.SEVERITY_LOW, models.CLASS_SPECIAL_CASE_BRANCH,
                (f"New branch in {sym.name!r} special-cases the literal "
                 f"{param} {op} {val}. Only justified if it fixes a real bug."),
                file=sym.file, symbol=sym.name,
                evidence=f"{param} {op} {val} (new condition)",
            ))

    # ---- MPG-006 exception suppression -----------------------------------
    base_try_dumps = _try_dumps(base_fn) if base_fn else set()
    for try_node in ast_utils.walk(cand_fn, (ast.Try, ast.TryStar)):
        if ast.dump(try_node) in base_try_dumps:
            continue
        if _handlers_suppress(try_node) and _try_wraps_call(try_node):
            findings.append(_find(
                "MPG-006",
                "Exception suppression — errors silently swallowed",
                models.SEVERITY_HIGH, models.CLASS_EXCEPTION_SUPPRESSION,
                (f"A new try/except in {sym.name!r} catches errors around a call "
                 "but does not re-raise, so failures degrade silently."),
                file=sym.file, symbol=sym.name,
                evidence=f"handler kinds: {_handler_kinds(try_node)}",
            ))

    # ---- MPG-007 logic bypass --------------------------------------------
    bypass = _logic_bypass(sym, base_fn, cand_fn)
    if bypass is not None:
        findings.append(_find(
            "MPG-007",
            "Logic bypass — real implementation skipped",
            models.SEVERITY_CRITICAL, models.CLASS_LOGIC_BYPASS,
            f"Original logic of {sym.name!r} appears to have been bypassed "
            f"({bypass[0]}).",
            file=sym.file, symbol=sym.name, evidence=bypass[1],
        ))

    # ---- MPG-008 disabled checks ------------------------------------------
    base_const = {ast.dump(n) for n in ast_utils.constant_branches(base_fn)} if base_fn else set()
    for node in ast_utils.constant_branches(cand_fn):
        if ast.dump(node) not in base_const:
            findings.append(_find(
                "MPG-008",
                "Constant-false branch added (disabled code)",
                models.SEVERITY_MEDIUM, models.CLASS_DISABLED_CHECK,
                (f"A branch with an always-constant test (e.g. `if False:` / "
                 f"`if 0:`) was added inside {sym.name!r}, which may hide logic "
                 "from tests and reviewers."),
                file=sym.file, symbol=sym.name,
                evidence=ast.dump(node.test),
            ))
            break  # one finding per function is enough
def _references_any(fn) -> bool:
    return bool(ast_utils.used_names_in(fn))


def _if_dumps(fn) -> Set[str]:
    return {ast.dump(n) for n in ast_utils.walk(fn, ast.If)}


def _try_dumps(fn) -> Set[str]:
    return {ast.dump(n) for n in ast_utils.walk(fn, (ast.Try, ast.TryStar))}


def _if_param_literals(if_node: ast.If) -> List[Tuple[str, str, str]]:
    """(param, op_name, literal_repr) for Compare tests of this If."""
    out: List[Tuple[str, str, str]] = []
    test = if_node.test
    if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name):
        for op, comp in zip(test.ops, test.comparators):
            val = ast_utils.constant_value(comp)
            if val is not ast_utils._NOT_CONSTANT:
                out.append((test.left.id, type(op).__name__, repr(val)))
    elif isinstance(test, ast.BoolOp):
        for val_node in test.values:
            if isinstance(val_node, ast.Compare) and isinstance(val_node.left, ast.Name):
                for op, comp in zip(val_node.ops, val_node.comparators):
                    val = ast_utils.constant_value(comp)
                    if val is not ast_utils._NOT_CONSTANT:
                        out.append((val_node.left.id, type(op).__name__, repr(val)))
    return out


def _handlers_suppress(try_node) -> bool:
    """True when every except handler swallows (no raise, ends in pass/return)."""
    if not getattr(try_node, "handlers", None):
        return False
    for handler in try_node.handlers:
        body = handler.body
        has_raise = any(isinstance(s, ast.Raise) for s in ast.walk(handler))
        if has_raise:
            return False
        if not body:
            continue
        last = body[-1]
        if isinstance(last, (ast.Pass, ast.Return)):
            continue
        return False  # handler does something meaningful
    return True


def _handler_kinds(try_node) -> List[str]:
    return sorted(
        h.type.id if isinstance(h.type, ast.Name) else getattr(h.type, "id", "?")
        for h in try_node.handlers if h.type is not None
    )


def _try_wraps_call(try_node) -> bool:
    return any(
        isinstance(n, ast.Call)
        or (isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Call) for t in ast.walk(n.value)))
        for n in try_node.body
    )


def _logic_bypass(sym, base_fn, cand_fn):
    """Return (reason, evidence) when the candidate avoids the original logic."""
    if base_fn is None or cand_fn is None:
        return None
    base_dump = ast_utils.body_dump(base_fn)
    cand_dump = ast_utils.body_dump(cand_fn)
    if not base_dump.strip():
        return None

    ratio = difflib.SequenceMatcher(None, base_dump, cand_dump).ratio()

    # 1) Original logic hidden under an always-false branch.
    base_stmts = {ast.dump(s) for s in ast_utils.body_statements(base_fn)}
    for node in ast_utils.constant_branches(cand_fn):
        hidden = [ast.dump(s) for s in node.body if ast.dump(s) in base_stmts]
        if hidden:
            return ("original statements moved under a constant-false branch",
                    f"hidden statements: {hidden[:3]}")

    # 2) Early guard that returns a constant while the parameter is ignored.
    body = ast_utils.body_statements(cand_fn)
    if body and isinstance(body[0], ast.If):
        first = body[0]
        if _all_returns_constant(first) and ratio < 0.35 \
                and _cand_ignores_params(cand_fn, sym.new_params):
            return ("the only remaining behaviour returns a constant under "
                    "a guard condition",
                    f"guard test: {ast.dump(first.test)}; body similarity={ratio:.2f}")

    # 3) Wholesale rewrite that stopped using inputs.
    if ratio < 0.15 and bool(getattr(base_fn, "args", None) and base_fn.args.args) \
            and _cand_ignores_params(cand_fn, sym.new_params):
        return ("original body was replaced wholesale and inputs are ignored",
                f"body similarity={ratio:.2f}")

    return None


def _cand_ignores_params(cand_fn, params: List[str]) -> bool:
    usage = ast_utils.param_usage_counts(cand_fn)
    return all(usage.get(p, 0) == 0 for p in params)


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def _commented_out_asserts(base_text: str, cand_text: str) -> List[str]:
    base_comments = {
        ln.strip() for ln in (base_text or "").splitlines()
        if ln.lstrip().startswith("#")
    }
    added = []
    for ln in (cand_text or "").splitlines():
        stripped = ln.strip()
        if stripped.startswith("#") and stripped not in base_comments:
            if "assert" in stripped or "raise" in stripped or "== " in stripped:
                added.append(stripped)
    return added


def run_static_checks(patch: Patch, changed_symbols: List[models.ChangedSymbol],
                      allowed_vars: Set[str]) -> List[models.Finding]:
    """All MPG static findings for the patch."""
    findings: List[models.Finding] = []
    test_literals = collect_test_literals(patch)

    # Group changed symbols by file so we can pair them with AST nodes.
    by_file: Dict[str, List[models.ChangedSymbol]] = {}
    for sym in changed_symbols:
        if sym.kind in ("function", "method"):
            by_file.setdefault(sym.file, []).append(sym)

    for rel, syms in by_file.items():
        ext = rel.rsplit(".", 1)[-1].lower()
        if ext != "py":
            # Honest degradation: JS/TS served by coarse symbol analysis.
            for sym in syms:
                if sym.status == models.CHANGE_MODIFIED:
                    findings.append(_find(
                        "MPG-900",
                        "JavaScript/TypeScript symbol change — manual review advised",
                        models.SEVERITY_LOW, models.CLASS_UNKNOWN,
                        (f"{sym.name!r} changed in a {ext} file; MPG deep static "
                         "analysis currently covers Python. Please review manually."),
                        file=rel, symbol=sym.name,
                    ))
            continue
        base_text = patch.base_files.get(rel) or ""
        cand_text = patch.cand_files.get(rel) or ""
        base_fns = ast_utils.top_level_functions(base_text)
        cand_fns = ast_utils.top_level_functions(cand_text)

        for sym in syms:
            _analyze_function(sym, base_fns.get(sym.name), cand_fns.get(sym.name),
                              test_literals, findings, allowed_vars)

        # MPG-008 (file level): commented-out assertions added by the patch.
        if is_test_file(rel):
            continue  # test-specific comment weakening is handled by MPG-005
        for comment in _commented_out_asserts(base_text, cand_text):
            findings.append(_find(
                "MPG-008",
                "Assertion commented out in source",
                models.SEVERITY_MEDIUM, models.CLASS_DISABLED_CHECK,
                "A line containing an assertion (or comparison) was added as a "
                "comment, disabling the check.",
                file=rel,
                evidence=f"# {comment}",
            ))

    return findings