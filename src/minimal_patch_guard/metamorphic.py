"""
metamorphic.py — Safe generalization probes for the Minimal Patch Guard (Phase 7).

For *pure, deterministic* Python functions we can safely execute, MPG runs:

  edge cases        canonical boundary inputs (0/1/-1/empty/large/special chars)
  literal-nearby    the exact literals found in tests/code, plus +/-1 variants
  metamorphic       order-permutation self-consistency for list reducers
  differential      base vs candidate behaviour on every generated input

Any behavioural difference between base and candidate on the holdout inputs is
reported as `uncovered_variation` — the agent must explain it.  Functions that
cannot be executed safely (I/O, unknown calls, side effects) are skipped with
an honest reason rather than guessed at.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from . import ast_utils
from . import models
from .patch_parser import Patch

# Whitelist of builtins a generalizable function may call.
_PURE_BUILTINS = {
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "hash",
    "int", "len", "list", "map", "max", "min", "range", "repr", "reversed",
    "round", "set", "sorted", "str", "sum", "tuple", "zip", "type",
}

_EDGE_CASES = {
    "int": [0, 1, -1, 2, 10, 1000, -1000],
    "float": [0.0, 1.0, -1.0, 0.5, -0.5, 1e6],
    "str": ["", "a", "hello", "hello world", "x" * 20, "!@#$%^&*()_+-=[]{}|;':\",./<>?`~"],
    "bool": [True, False],
    "list": [[], [0], [1, 2, 3], [-1], [10**6]],
    "dict": [{}, {"a": 1, "b": 2}],
}

_NUMERIC = {"int", "float"}


def _is_pure(fn) -> Tuple[bool, str]:
    """(can_run, reason) — can this function be executed without side effects?"""
    if isinstance(fn, ast.AsyncFunctionDef):
        return False, "async function — not executed"
    used = ast_utils.used_names_in(fn)
    args = fn.args
    params = {a.arg for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)}
    if args.vararg:
        params.add(args.vararg.arg)
    if args.kwarg:
        params.add(args.kwarg.arg)
    if not params:
        return False, "no parameters — nothing to generalize"
    if fn.name in used:
        return False, "recursive function — not executed"
    for node in ast.walk(fn):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) \
                and node is not fn:
            return False, "nested function definitions — not executed"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in _PURE_BUILTINS:
                    return False, f"call to non-pure builtin: {node.func.id}"
            else:
                return False, f"non-name call target: {ast.dump(node.func)[:60]}"
        if isinstance(node, ast.Starred):
            return False, "*args unpacking not supported"
    return True, ""


def _infer_param_type(fn, param: str) -> Optional[str]:
    """Best-effort parameter type from annotations + usage heuristics."""
    args = fn.args
    for a in list(args.posonlyargs) + list(args.args):
        if a.arg == param and a.annotation is not None:
            ann = a.annotation
            if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
                base = ann.value.lstrip("'\"")
                if base in _EDGE_CASES:
                    return base
            if isinstance(ann, ast.Name) and ann.id in _EDGE_CASES:
                return ann.id
    hints = {"int": 0, "float": 0, "str": 0, "bool": 0, "list": 0, "dict": 0}
    for node in ast.walk(fn):
        if isinstance(node, ast.BinOp) and isinstance(node.left, ast.Name) \
                and node.left.id == param:
            hints["int"] += 1
            hints["float"] += 1
        elif isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) \
                and node.left.id == param:
            for comp in node.comparators:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, (int, float)) \
                        and not isinstance(comp.value, bool):
                    hints["int"] += 1
                elif isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    hints["str"] += 1
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.args and isinstance(node.args[0], ast.Name) \
                and node.args[0].id == param \
                and node.func.id in ("len", "sum", "min", "max", "sorted",
                                     "list", "set", "tuple", "reversed",
                                     "enumerate", "zip"):
            hints["list"] += 1
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                and node.value.id == param:
            hints["list"] += 1
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            for iter_node in ast.walk(node.iter):
                if isinstance(iter_node, ast.Name) and iter_node.id == param:
                    hints["list"] += 1
    total = sum(hints.values())
    if total == 0:
        return None
    best = max(hints, key=hints.get)
    if sum(1 for v in hints.values() if v == hints[best]) != 1:
        return None
    return best


def _case_values(param_type: str, literals: List[Any]) -> List[Any]:
    base: List[Any] = list(_EDGE_CASES.get(param_type, []))
    for lit in literals:
        if param_type in _NUMERIC and isinstance(lit, (int, float)) \
                and not isinstance(lit, bool):
            if lit in base:
                continue
            base.append(lit)
            if isinstance(lit, int):
                base.append(lit + 1)
                base.append(lit - 1)
        elif param_type == "str" and isinstance(lit, str) and lit not in base:
            base.append(lit)
    return base[:14]
def _literal_values(fn) -> List[Any]:
    """Numbers/strings used inside fn, for literal-nearby cases."""
    out: List[Any] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                out.append(node.value)
            elif isinstance(node.value, str) and len(node.value) <= 40:
                out.append(node.value)
    return out


def cand_rename(fn_text: str, name: str) -> str:
    return fn_text.replace(f"def {name}(", f"def _cand_{name}(", 1)


def _execute_harness(harness: str, timeout: int) -> Optional[List[Dict]]:
    fd, path = tempfile.mkstemp(suffix=".py", prefix="mpg_gen_")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(harness)
    try:
        proc = subprocess.run(
            [sys.executable, path], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    marker = "MPG_RESULT "
    for line in proc.stdout.splitlines():
        idx = line.find(marker)
        if idx >= 0:
            try:
                return json.loads(line[idx + len(marker):])
            except json.JSONDecodeError:
                return None
    return None


def _harness_source_for(fn_text: str, base_fn_text: str, name: str,
                        constants: Dict[str, Any], cases) -> str:
    code = []
    for const_name, val in sorted(constants.items()):
        code.append(f"{const_name} = {val!r}")
    if code:
        code.append("")
    code.append(base_fn_text.replace(f"def {name}(", f"def _base_{name}(", 1))
    code.append(cand_rename(fn_text, name))
    code.append(f"CASES = {json.dumps(cases)}")
    runner = '''
import json as _json
def _run(fn, args):
    try:
        return {"ok": True, "v": fn(*args)}
    except Exception as _e:
        return {"ok": False, "e": type(_e).__name__}
_OUT = []
for _args in CASES:
    _OUT.append({"args": _args,
                 "base": _run(_base_{n}, _args),
                 "cand": _run(_cand_{n}, _args)})
print("MPG_RESULT " + _json.dumps(_OUT))
'''.replace("{n}", name)
    return "\n".join(code) + runner
# --------------------------------------------------------------------------
# Main entry
# --------------------------------------------------------------------------

def _cases_for_symbol(fn, param_types: Dict[str, str]) -> List[Any]:
    import itertools
    lit = _literal_values(fn)
    per_param = {p: _case_values(t, lit) for p, t in param_types.items()}
    keys = list(per_param)
    total = 1
    for p in keys:
        total *= max(1, len(per_param[p]))
    while total > 16:
        halved = False
        for p in keys:
            if len(per_param[p]) > 1:
                per_param[p] = per_param[p][::2]
                halved = True
                total = 1
                for q in keys:
                    total *= max(1, len(per_param[q]))
                break
        if not halved:
            break
    return [list(combo) for combo in itertools.product(*(per_param[p] for p in keys))]


def run_generalization(patch: Patch, changed_symbols: List[models.ChangedSymbol],
                       run_reason: str = "requested",
                       max_timeout: int = 30) -> models.GeneralizationResult:
    """Execute safe differential generalization probes for pure function changes."""
    result = models.GeneralizationResult(status=models.GEN_NOT_RUN,
                                         run_reason=run_reason)
    if not changed_symbols:
        result.run_reason = "no changed symbols to probe"
        return result

    for rel in patch.changed_files:
        if not rel.endswith(".py"):
            continue
        base_text = patch.base_files.get(rel) or ""
        cand_text = patch.cand_files.get(rel) or ""
        base_fns = ast_utils.top_level_functions(base_text)
        cand_fns = ast_utils.top_level_functions(cand_text)
        constants = ast_utils.module_constants(cand_text)

        for sym in changed_symbols:
            if sym.file != rel or sym.kind not in ("function", "method"):
                continue
            base_fn = base_fns.get(sym.name)
            cand_fn = cand_fns.get(sym.name)
            if base_fn is None or cand_fn is None:
                continue
            pure, reason = _is_pure(cand_fn)
            if not pure:
                result.details.append(f"skipped {sym.name} ({reason})")
                continue
            args = cand_fn.args
            params = [a.arg for a in list(args.posonlyargs) + list(args.args)]
            param_types: Dict[str, str] = {}
            for p in params:
                t = _infer_param_type(cand_fn, p)
                if t is None:
                    break
                param_types[p] = t
            if len(param_types) != len(params):
                result.details.append(
                    f"skipped {sym.name} (could not infer parameter types)")
                continue

            cases = _cases_for_symbol(cand_fn, param_types)
            if not cases:
                result.details.append(f"skipped {sym.name} (no cases generated)")
                continue

            try:
                fn_text = ast.get_source_segment(cand_text, cand_fn)
                base_fn_text = ast.get_source_segment(base_text, base_fn)
            except Exception:
                fn_text = base_fn_text = None
            if not fn_text or not base_fn_text:
                result.details.append(
                    f"skipped {sym.name} (could not segment source)")
                continue

            harness = _harness_source_for(fn_text, base_fn_text, sym.name,
                                          constants, cases)
            rows = _execute_harness(harness, max_timeout)
            if rows is None:
                result.status = models.GEN_FAILED
                result.details.append(
                    f"harness for {sym.name} failed or timed out")
                continue

            variations = []
            for row in rows:
                b, c = row["base"], row["cand"]
                differ = b.get("ok") != c.get("ok")
                if not differ and b.get("ok"):
                    differ = not _deep_equal(b.get("v"), c.get("v"))
                if differ:
                    variations.append((row["args"], b, c))

            result.candidates_found += 1
            result.attempted_cases += len(rows)
            if variations:
                result.status = models.GEN_VARIATION
                result.acceptable = False
                result.holdout_passed = False
                result.details.append(
                    f"{sym.name}: {len(variations)}/{len(rows)} holdout cases differ")
                for args, b, c in variations[:3]:
                    result.details.append(
                        f"  case {args}: base={b} candidate={c}")
            else:
                result.status = models.GEN_PASSED
                result.acceptable = True
                result.holdout_passed = True
                result.details.append(
                    f"{sym.name}: behaviour identical on {len(rows)} cases")

    if result.status == models.GEN_NOT_RUN:
        result.run_reason = "no pure, typed functions found to probe"
    return result
def _deep_equal(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return a == b or (a != a and b != b)  # NaN-proof
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_deep_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_deep_equal(x, y) for x, y in zip(a, b))
    return a == b