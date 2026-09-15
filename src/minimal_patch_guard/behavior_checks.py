"""
behavior_checks.py — Level-2 function-level deltas for the Minimal Patch Guard (Phase 4).

Computes per-function observational differences between base and candidate:
parameters, referenced free variables, called functions, returns, branches,
loops, exception handlers, early returns and a whole-body-rewrite estimate.
The deltas feed the independent metric groups (control_flow_metrics,
behavior_metrics, input_dependency_metrics, complexity_metrics).
"""

from __future__ import annotations

import ast
import difflib
from typing import Dict, List, Optional

from . import ast_utils
from . import models
from .patch_parser import Patch

# Common builtins so free-variable tracking stays meaningful.
_BUILTINS = {
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes", "callable",
    "chr", "classmethod", "compile", "complex", "delattr", "dict", "dir", "divmod",
    "enumerate", "eval", "exec", "filter", "float", "format", "frozenset", "getattr",
    "globals", "hasattr", "hash", "hex", "id", "input", "int", "isinstance",
    "issubclass", "iter", "len", "list", "locals", "map", "max", "memoryview",
    "min", "next", "object", "oct", "open", "ord", "pow", "print", "property",
    "range", "repr", "reversed", "round", "set", "setattr", "slice", "sorted",
    "staticmethod", "str", "sum", "super", "tuple", "type", "vars", "zip",
}

_CF_KINDS = ("if", "for", "while", "try", "raise", "return")


def _parents(fn) -> Dict[ast.AST, Optional[ast.AST]]:
    parents: Dict[ast.AST, Optional[ast.AST]] = {fn: None}
    for node in ast.walk(fn):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _early_returns(fn) -> int:
    """Returns that are not the final statement of their enclosing block."""
    parents = _parents(fn)
    count = 0
    for ret in ast_utils.walk(fn, ast.Return):
        parent = parents.get(ret)
        block = None
        if parent is not None:
            for attr in ("body", "orelse", "finalbody"):
                lst = getattr(parent, attr, None)
                if isinstance(lst, list) and ret in lst:
                    block = lst
                    break
            if block is None and hasattr(parent, "handlers"):
                for handler in parent.handlers:
                    if ret in handler.body:
                        block = handler.body
                        break
        if block is not None and block.index(ret) != len(block) - 1:
            count += 1
    return count


def _imperative_call_count(fn) -> int:
    """Expression-statements that are bare calls (side-effect reads)."""
    count = 0
    for stmt in ast_utils.body_statements(fn):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, (ast.Call, ast.Await)):
            count += 1
        elif isinstance(stmt, ast.Assign) and any(
                isinstance(t, (ast.Attribute, ast.Subscript)) for t in stmt.targets):
            count += 1
    return count


def function_delta(sym: models.ChangedSymbol, base_fn, cand_fn) -> Optional[Dict]:
    """Observationally careful delta between base_fn and cand_fn."""
    if base_fn is None or cand_fn is None:
        return None
    d: Dict = {"name": sym.name, "file": sym.file}

    base_params = set(sym.old_params)
    cand_params = set(sym.new_params)
    d["params_added"] = sorted(cand_params - base_params)
    d["params_removed"] = sorted(base_params - cand_params)
    d["params_unchanged"] = sorted(base_params & cand_params)

    base_names = ast_utils.used_names_in(base_fn) - base_params - _BUILTINS
    cand_names = ast_utils.used_names_in(cand_fn) - cand_params - _BUILTINS
    d["referenced_names_added"] = sorted(cand_names - base_names)
    d["referenced_names_removed"] = sorted(base_names - cand_names)

    base_calls = ast_utils.calls_in(base_fn)
    cand_calls = ast_utils.calls_in(cand_fn)
    d["calls_added"] = sorted(cand_calls - base_calls)
    d["calls_removed"] = sorted(base_calls - cand_calls)

    base_cf = ast_utils.statement_summary(base_fn)
    cand_cf = ast_utils.statement_summary(cand_fn)
    for kind in _CF_KINDS:
        d[f"{kind}_added"] = cand_cf[kind] - base_cf[kind]
        d[f"{kind}_removed"] = base_cf[kind] - cand_cf[kind]

    base_ret = [r.value for r in ast_utils.returns_of(base_fn) if r.value is not None]
    cand_ret = [r.value for r in ast_utils.returns_of(cand_fn) if r.value is not None]
    d["return_set_changed"] = (
        len(base_ret) != len(cand_ret)
        or any(ast_utils.is_constant_node(b) != ast_utils.is_constant_node(c)
               for b, c in zip(base_ret, cand_ret))
    )

    d["early_returns_added"] = max(0, _early_returns(cand_fn) - _early_returns(base_fn))
    d["early_returns_removed"] = max(0, _early_returns(base_fn) - _early_returns(cand_fn))
    d["side_effect_statements_added"] = max(
        0, _imperative_call_count(cand_fn) - _imperative_call_count(base_fn))
    d["body_rewritten"] = _body_rewritten(base_fn, cand_fn)
    d["complexity_base"] = _complexity(base_fn)
    d["complexity_candidate"] = _complexity(cand_fn)
    return d
def _body_rewritten(base_fn, cand_fn) -> bool:
    base_dump = ast_utils.body_dump(base_fn)
    cand_dump = ast_utils.body_dump(cand_fn)
    if not base_dump.strip() or not cand_dump.strip():
        return False
    ratio = difflib.SequenceMatcher(None, base_dump, cand_dump).ratio()
    return ratio < 0.4


def _complexity(fn) -> int:
    """McCabe-lite: 1 + branches + loops + try + with (nested defs excluded)."""
    cf = ast_utils.statement_summary(fn)
    return 1 + cf["if"] + cf["for"] + cf["while"] + cf["try"] + cf["with"]


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

def analyze_behavior(patch: Patch,
                     changed_symbols: List[models.ChangedSymbol]) -> Dict[str, Dict]:
    """Return {group_name: metrics} for behaviour/control/input-dependency buckets."""
    deltas: List[Dict] = []
    by_file: Dict[str, List[models.ChangedSymbol]] = {}
    for sym in changed_symbols:
        if sym.kind in ("function", "method") \
                and sym.status == models.CHANGE_MODIFIED:
            by_file.setdefault(sym.file, []).append(sym)

    for rel, syms in by_file.items():
        if not rel.endswith(".py"):
            continue
        base_fns = ast_utils.top_level_functions(patch.base_files.get(rel) or "")
        cand_fns = ast_utils.top_level_functions(patch.cand_files.get(rel) or "")
        for sym in syms:
            dl = function_delta(sym, base_fns.get(sym.name), cand_fns.get(sym.name))
            if dl is not None:
                deltas.append(dl)

    control_flow = {
        "branches_added": sum(d["if_added"] for d in deltas),
        "branches_removed": sum(d["if_removed"] for d in deltas),
        "loops_added": sum(d["for_added"] + d["while_added"] for d in deltas),
        "loops_removed": sum(d["for_removed"] + d["while_removed"] for d in deltas),
        "exception_handlers_added": sum(d["try_added"] for d in deltas),
        "exception_handlers_removed": sum(d["try_removed"] for d in deltas),
        "early_returns_added": sum(d["early_returns_added"] for d in deltas),
        "early_returns_removed": sum(d["early_returns_removed"] for d in deltas),
        "functions_with_body_rewrite": sum(1 for d in deltas if d["body_rewritten"]),
    }
    behavior = {
        "params_added": sum(len(d["params_added"]) for d in deltas),
        "params_removed": sum(len(d["params_removed"]) for d in deltas),
        "params_unchanged": sum(len(d["params_unchanged"]) for d in deltas),
        "referenced_names_added": sorted({
            n for d in deltas for n in d["referenced_names_added"]})[:40],
        "referenced_names_removed": sorted({
            n for d in deltas for n in d["referenced_names_removed"]})[:40],
        "calls_added": sorted({n for d in deltas for n in d["calls_added"]})[:40],
        "calls_removed": sorted({n for d in deltas for n in d["calls_removed"]})[:40],
        "return_sets_changed": sum(1 for d in deltas if d["return_set_changed"]),
        "side_effect_statements_added": sum(
            d["side_effect_statements_added"] for d in deltas),
        "body_rewritten_count": sum(1 for d in deltas if d["body_rewritten"]),
    }
    input_dependency = {
        "parameters_unchanged": sum(len(d["params_unchanged"]) for d in deltas),
        "parameters_added": sum(len(d["params_added"]) for d in deltas),
        "parameters_removed": sum(len(d["params_removed"]) for d in deltas),
        "new_free_variables": sorted({
            n for d in deltas for n in d["referenced_names_added"]})[:40],
    }
    base_cx = [d["complexity_base"] for d in deltas]
    cand_cx = [d["complexity_candidate"] for d in deltas]
    complexity = {
        "base_avg": round(sum(base_cx) / len(base_cx), 2) if base_cx else None,
        "candidate_avg": round(sum(cand_cx) / len(cand_cx), 2) if cand_cx else None,
        "delta": (round(sum(cand_cx) / len(cand_cx), 2)
                  - round(sum(base_cx) / len(base_cx), 2)) if base_cx else None,
        "functions_measured": len(deltas),
    }
    return {
        "control_flow_metrics": control_flow,
        "behavior_metrics": behavior,
        "input_dependency_metrics": input_dependency,
        "complexity_metrics": complexity,
    }