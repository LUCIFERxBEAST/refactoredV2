"""
ast_utils.py — Shared stdlib-ast helpers for the Minimal Patch Guard analyzers.

Keeps all Python static/behavioral analysis in one small place so each check
module stays focused on rules instead of tree walking.
"""

from __future__ import annotations

import ast
import operator
from typing import Any, Dict, List, Optional, Set, Tuple

_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Invert: operator.invert,
}

_BIN_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def walk(node, node_type):
    """Yield every descendant (and self) of type node_type."""
    for child in ast.walk(node):
        if isinstance(child, node_type):
            yield child


def is_constant_node(node: Optional[ast.AST]) -> bool:
    """True when node is a literal (recursively) with no variable reads."""
    if node is None:
        return False
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(is_constant_node(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(k is None or is_constant_node(k) for k in node.keys) and \
            all(is_constant_node(v) for v in node.values)
    if isinstance(node, ast.JoinedStr):
        return all(isinstance(v, ast.Constant) for v in node.values)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return is_constant_node(node.operand)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPERATORS:
        return is_constant_node(node.left) and is_constant_node(node.right)
    return False


_NOT_CONSTANT = object()


def constant_value(node: Optional[ast.AST]) -> Any:
    """Evaluate a constant node to a Python value, or return _NOT_CONSTANT."""
    if not is_constant_node(node):
        return _NOT_CONSTANT
    try:
        return _eval_constant(node)
    except Exception:
        return _NOT_CONSTANT


def _eval_constant(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_eval_constant(e) for e in node.elts]
    if isinstance(node, ast.Dict):
        return {_eval_constant(k): _eval_constant(v)
                for k, v in zip(node.keys, node.values) if k is not None}
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant))
    if isinstance(node, ast.UnaryOp):
        return _UNARY_OPERATORS[type(node.op)](_eval_constant(node.operand))
    if isinstance(node, ast.BinOp):
        return _BIN_OPERATORS[type(node.op)](_eval_constant(node.left),
                                             _eval_constant(node.right))
    raise TypeError(f"non-constant node: {type(node).__name__}")


def returns_of(fn) -> List[ast.Return]:
    """All Return statements inside fn."""
    return list(walk(fn, ast.Return))


def used_names_in(fn) -> Set[str]:
    """Every identifier read (Load context) inside fn, nested scopes excluded."""
    names: Set[str] = set()
    for child in ast.walk(fn):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) \
                and child is not fn:
            continue  # nested scopes excluded
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            names.add(child.id)
    return names


def param_usage_counts(fn) -> Dict[str, int]:
    """param name -> number of Load usages inside fn body (nested defs skipped)."""
    params: Set[str] = set()
    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = fn.args
        params = {a.arg for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)}
        if args.vararg:
            params.add(args.vararg.arg)
        if args.kwarg:
            params.add(args.kwarg.arg)
    counts: Dict[str, int] = {}
    for child in ast.walk(fn):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) \
                and child is not fn:
            continue
        if isinstance(child, ast.Name) and child.id in params \
                and isinstance(child.ctx, ast.Load):
            counts[child.id] = counts.get(child.id, 0) + 1
    return counts


def statement_summary(fn) -> Dict[str, int]:
    """Counts of control-flow statement kinds inside fn (nested defs excluded)."""
    counts: Dict[str, int] = {
        "if": 0, "for": 0, "while": 0, "try": 0, "raise": 0,
        "return": 0, "assert": 0, "with": 0,
    }
    for child in ast.walk(fn):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) \
                and child is not fn:
            continue
        if isinstance(child, ast.If):
            counts["if"] += 1
        elif isinstance(child, ast.For):
            counts["for"] += 1
        elif isinstance(child, ast.While):
            counts["while"] += 1
        elif isinstance(child, ast.Try):
            counts["try"] += 1
        elif isinstance(child, ast.Raise):
            counts["raise"] += 1
        elif isinstance(child, ast.Return):
            counts["return"] += 1
        elif isinstance(child, ast.Assert):
            counts["assert"] += 1
        elif isinstance(child, ast.With):
            counts["with"] += 1
    return counts


def calls_in(fn) -> Set[str]:
    """Names of functions called inside fn (nested defs excluded)."""
    calls: Set[str] = set()
    for child in ast.walk(fn):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) \
                and child is not fn:
            continue
        if isinstance(child, ast.Call):
            f = child.func
            if isinstance(f, ast.Name):
                calls.add(f.id)
            elif isinstance(f, ast.Attribute):
                calls.add(f.attr)
    return calls


def body_statements(fn) -> List[ast.stmt]:
    """The statements of fn's body."""
    if hasattr(fn, "body"):
        return list(fn.body)
    return []


def body_dump(fn) -> str:
    """Normalized dump of fn's body used for 'body rewritten?' detection."""
    return "\n".join(ast.dump(s) for s in body_statements(fn))


def condition_literals(fn) -> List[Tuple[str, str, Any]]:
    """
    Comparisons of the form `<param> <op> <literal>` inside fn.
    Returns [(param_name, ast_op_class_name, literal_value)].
    """
    out: List[Tuple[str, str, Any]] = []
    params: Set[str] = set()
    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = fn.args
        params = {a.arg for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)}
        if args.vararg:
            params.add(args.vararg.arg)
        if args.kwarg:
            params.add(args.kwarg.arg)
    for child in ast.walk(fn):
        if isinstance(child, ast.Compare):
            left = child.left
            if isinstance(left, ast.Name) and left.id in params:
                for op, comp in zip(child.ops, child.comparators):
                    val = constant_value(comp)
                    if val is not _NOT_CONSTANT:
                        out.append((left.id, type(op).__name__, _repr_value(val)))
    return out


def condition_dumps(fn) -> Set[str]:
    """Set of ast.dumps of every If.test inside fn (nested defs excluded)."""
    dumps: Set[str] = set()
    for child in ast.walk(fn):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) \
                and child is not fn:
            continue
        if isinstance(child, ast.If):
            dumps.add(ast.dump(child.test))
    return dumps


def constant_branches(fn) -> List[ast.If]:
    """If nodes whose test is a constant literal (e.g. `if False:`, `if 0:`)."""
    out: List[ast.If] = []
    for child in ast.walk(fn):
        if isinstance(child, ast.If):
            val = constant_value(child.test)
            if val is not _NOT_CONSTANT:
                out.append(child)
    return out


def module_constants(source: str) -> Dict[str, Any]:
    """Top-level module constant assignments: name -> literal value."""
    out: Dict[str, Any] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, ast.Assign):
            val = constant_value(node.value)
            if val is _NOT_CONSTANT:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = val
    return out


def numeric_literals_in(fn) -> Set[Tuple[float, str]]:
    """(numeric value, repr-source) found inside fn's numbers (incl. compares)."""
    out: Set[Tuple[float, str]] = set()
    for child in ast.walk(fn):
        if isinstance(child, ast.Constant) and isinstance(child.value, (int, float)) \
                and not isinstance(child.value, bool):
            out.add((float(child.value), repr(child.value)))
    return out


def _repr_value(val: Any) -> str:
    """Deterministic, JSON-ish repr for evidence strings."""
    if isinstance(val, str):
        return repr(val)
    if isinstance(val, bool):
        return str(val)
    if isinstance(val, (int, float)):
        return repr(val)
    if isinstance(val, (list, tuple, set)):
        return repr(list(val))
    if isinstance(val, dict):
        return repr(val)
    return str(val)


def top_level_functions(source: str) -> Dict[str, ast.AST]:
    """name -> ast.FunctionDef/AsyncFunctionDef, top-level plus class methods."""
    out: Dict[str, ast.AST] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[f"{node.name}.{sub.name}"] = sub
    return out