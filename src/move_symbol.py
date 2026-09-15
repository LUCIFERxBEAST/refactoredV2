"""
move_symbol.py — ACT logic for the 'move-symbol' operation.

Moves a top-level function or class definition from one Python file to
another (optionally creating the target file), then updates every static
reference in the repo so the tests keep passing:

  - direct `from <old/module> import <symbol>` lines are rewritten to import
    from the new module;
  - attribute-style references like `mathutils.build_report(...)` become a
    bare `build_report(...)` with a fresh `from <new> import <symbol>` added;
  - names the moved definition depended on (module-level names of its old
    file) are imported into the target file automatically.

Analysis is backed by the tree-sitter-python grammar.
"""

import os
import re
from typing import Dict, List, Optional, Set, Tuple

from tree_sitter import Language, Parser

import tree_sitter_python

from .extract_function import (
    _BUILTINS,
    _bounds_identifier,
    _collect_module_bindings,
    _get_python_parser,
    _walk_in_order,
)


def dotted_module(rel_path: str) -> str:
    """'pkg/mathutils.py' -> 'pkg.mathutils'"""
    p = rel_path.replace("\\", "/")
    if p.endswith(".py"):
        p = p[:-3]
    return p.replace("/", ".")


def _resolve_relative_module(mod: str, rel_path: str) -> str:
    """Resolve a relative `.module` against a file's repo-relative path."""
    if not mod.startswith("."):
        return mod
    base = os.path.dirname(rel_path).replace("\\", "/")
    base_dotted = base.replace("/", ".") if base not in ("", ".") else ""
    depth = len(mod) - len(mod.lstrip("."))
    name = mod.lstrip(".")
    parts = base_dotted.split(".") if base_dotted else []
    if depth > 1:
        parts = parts[: -(depth - 1)] if parts else parts
    prefix = ".".join(parts)
    if not name:
        name = parts[-1] if parts else ""
    return f"{prefix}.{name}" if prefix else name


def _module_bindings(source: str, rel_path: str) -> Dict[str, Tuple[str, str]]:
    """
    Map every name a file binds through an import to the (dotted_module, name)
    it points at.  `from pkg import mathutils` maps `mathutils` to
    (`pkg.mathutils`, `mathutils`); `import pkg.mathutils` maps `pkg` to
    `pkg.mathutils`.
    """
    bindings: Dict[str, Tuple[str, str]] = {}

    for m in re.finditer(r"(?m)^\s*import\s+([^\n#]+)", source):
        for part in m.group(1).split(","):
            am = re.match(r"([\w.]+)(?:\s+as\s+(\w+))?", part.strip())
            if am is None:
                continue
            mod = am.group(1)
            alias = am.group(2)
            if alias:
                bindings[alias] = (mod, alias)
            else:
                bindings[mod.split(".")[0]] = (mod, mod)

    for m in re.finditer(r"(?m)^\s*from\s+([.\w]+)\s+import\s+([^\n#]+)", source):
        mod = m.group(1)
        dotted = _resolve_relative_module(mod, rel_path)
        for name_part in m.group(2).split(","):
            nm = re.match(r"(\w+)(?:\s+as\s+(\w+))?", name_part.strip())
            if nm is None:
                continue
            bound = nm.group(2) or nm.group(1)
            bindings[bound] = (f"{dotted}.{bound}" if dotted else bound, bound)

    return bindings
def find_top_level_definition(source: str, symbol: str):
    """Return the top-level definition node for `symbol`, or None."""
    parser = _get_python_parser()
    tree = parser.parse(source.encode("utf-8"))
    root = tree.root_node
    for node in root.named_children:
        if node.type not in ("function_definition", "class_definition"):
            continue
        name_node = node.child_by_field_name("name")
        if name_node is not None and name_node.text.decode("utf-8") == symbol:
            return node
    return None


def _collapse_blank_lines(lines: List[str]) -> List[str]:
    """Keep at most one consecutive blank line."""
    result: List[str] = []
    prev_blank = False
    for ln in lines:
        if not ln.strip():
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False
        result.append(ln)
    return result


def _import_line_exists(source: str, import_line: str) -> bool:
    wanted = import_line.strip()
    for ln in source.splitlines():
        if ln.strip() == wanted:
            return True
    return False


def _insert_import_after_imports(source: str, new_import: str) -> str:
    """Insert a new import line right after the last top-of-file import."""
    lines = source.splitlines(keepends=True)
    last_import = -1
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            last_import = i
    if last_import == -1:
        return new_import + "\n\n" + source
    lines.insert(last_import + 1, new_import + "\n")
    return "".join(lines)


def _needed_imports(source: str, symbol: str) -> List[str]:
    """Names the moved def uses that are module-level in the old file."""
    parser = _get_python_parser()
    tree = parser.parse(source.encode("utf-8"))
    root = tree.root_node

    module_level: Set[str] = set()
    for stmt in root.named_children:
        _collect_module_bindings(stmt, module_level)

    def_node = find_top_level_definition(source, symbol)
    if def_node is None:
        return []

    used: Set[str] = set()
    defined: Set[str] = set()
    for node in _walk_in_order(def_node):
        if node.type != "identifier":
            continue
        name = node.text.decode("utf-8", "replace")
        used.add(name)
        parent = node.parent
        if parent is not None and _bounds_identifier(parent, node):
            defined.add(name)

    free = used - defined - _BUILTINS
    return sorted(free & module_level)
def _rewrite_attribute_refs(source: str, rel_path: str, symbol: str,
                            old_module: str, new_module: str) -> Tuple[str, bool]:
    """
    Replace `base.symbol` with bare `symbol` wherever `base` is bound to
    old_module. Returns (new_source, changed).
    """
    bindings = _module_bindings(source, rel_path)
    changed = False
    for base, (mod, _name) in bindings.items():
        if mod != old_module:
            continue
        pattern = re.compile(
            r"\b" + re.escape(base) + r"\." + re.escape(symbol) + r"\b"
        )
        source, n = pattern.subn(symbol, source)
        changed = changed or n > 0
    return source, changed


def _rewrite_from_imports(source: str, symbol: str,
                          new_module: str) -> Tuple[str, bool]:
    """Rewrite `from <old_module> import <symbol>` to the new module."""
    symbol_re = re.escape(symbol)
    changed = {"n": False}

    def _repl(m):
        names = m.group(2)
        if re.search(r"(?<!\w)" + symbol_re + r"(?=\s*,|\s*$)", names):
            changed["n"] = True
            return "from {0} import {1}".format(new_module, names)
        return m.group(0)

    pattern = re.compile(r"(?m)^(\s*)from\s+([.\w]+)\s+import\s+([^\n#]+)")
    new_source = pattern.sub(_repl, source)
    return new_source, changed["n"]


def move_symbol(repo_root: str, symbol: str, source_rel: str, target_rel: str) -> Dict[str, str]:
    """
    Perform the move. Returns a dict mapping relative paths to human-readable
    change descriptions.
    """
    results: Dict[str, str] = {}
    source_path = os.path.join(repo_root, source_rel)
    target_path = os.path.join(repo_root, target_rel)

    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"source file not found: {source_rel}")

    with open(source_path, "r", encoding="utf-8") as f:
        source_text = f.read()

    def_node = find_top_level_definition(source_text, symbol)
    if def_node is None:
        raise ValueError(
            f"no top-level definition named {symbol!r} found in {source_rel}"
        )

    remove_node = def_node
    if def_node.parent is not None and def_node.parent.type == "decorated_definition":
        remove_node = def_node.parent

    def_text = source_text[remove_node.start_byte:remove_node.end_byte]

    old_module = dotted_module(source_rel)
    new_module = dotted_module(target_rel)

    # ── 1. remove the definition from the source file ────────────────────
    lines = source_text.splitlines(keepends=True)
    del lines[remove_node.start_point.row:remove_node.end_point.row + 1]
    lines = _collapse_blank_lines(lines)
    new_source = "".join(lines)

    still_references = re.search(r"\b" + re.escape(symbol) + r"\b", new_source)
    if still_references and not _import_line_exists(
        new_source, f"from {new_module} import {symbol}"
    ):
        # Append at the END of the module: the new module imports helpers from
        # this one, so importing it early would create a circular import.
        if not new_source.endswith("\n"):
            new_source += "\n"
        new_source += f"from {new_module} import {symbol}\n"
        results[source_rel] = (
            f"moved def {symbol} -> {target_rel}; re-imported it locally"
        )
    else:
        results[source_rel] = f"moved def {symbol} -> {target_rel}"

    with open(source_path, "w", encoding="utf-8") as f:
        f.write(new_source)

    # ── 2. create / extend the target file ────────────────────────────────
    target_imports = _needed_imports(source_text, symbol)
    import_header = (
        "from {0} import {1}\n\n\n".format(old_module, ", ".join(target_imports))
        if target_imports
        else ""
    )

    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    if os.path.isfile(target_path):
        with open(target_path, "r", encoding="utf-8") as f:
            target_text = f.read()
        if not target_text.endswith("\n"):
            target_text += "\n"
        target_text += "\n\n" + def_text + "\n"
    else:
        target_text = import_header + def_text + "\n"
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(target_text)
    results[target_rel] = f"created/extended with def {symbol}"

    # ── 3. rewrite every other static reference ──────────────────────────
    from .dependency_graph import scan_repo

    scan = scan_repo(repo_root, symbol)
    source_abs = os.path.abspath(source_rel)
    for rel in scan.static_files:
        if os.path.abspath(rel) == source_abs:
            continue
        filepath = os.path.join(repo_root, rel)
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
        orig = text

        text, _attr_rewritten = _rewrite_attribute_refs(
            text, rel, symbol, old_module, new_module
        )
        text, _imp_rewritten = _rewrite_from_imports(text, symbol, new_module)

        if not _attr_rewritten and not _imp_rewritten:
            continue  # no direct reference to update

        if not _import_line_exists(text, f"from {new_module} import {symbol}"):
            text = _insert_import_after_imports(
                text, f"from {new_module} import {symbol}"
            )

        if text != orig:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(text)
            results[rel] = f"rewritten references for {symbol}"

    return results