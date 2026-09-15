"""
extract_function.py — ACT logic for the 'extract-function' operation.

Extracts a contiguous block of statements (identified by 1-based line numbers)
from a Python file into a brand-new top-level function, replacing the block
inline with a call to that function.

The new function's shape is derived automatically from the block:
  - parameters: free variables referenced in the block but not defined there,
    excluding Python builtins and names already available at module level;
  - return value: variables assigned at the block's own depth that are still
    referenced afterwards inside the enclosing function (returned as a tuple).

Analysis uses the tree-sitter-python syntax tree so we know exactly what is
an identifier, an assignment target, a definition, an import, and so on.
"""

import builtins
import os
import re
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

from tree_sitter import Language, Parser

import tree_sitter_python

_BUILTINS = (
    set(dir(builtins))
    | {"True", "False", "None", "__name__", "__file__", "__doc__", "__all__"}
)

# node types whose identifiers represent definitions inside the current scope
_BINDING_PARENT_TYPES = {
    "function_definition",
    "class_definition",
    "for_statement",
    "import_statement",
    "import_from_statement",
    "aliased_import",
    "dotted_name",
    "parameters",
    "as_pattern",
    "with_item",
    "default_parameter",
    "typed_parameter",
    "type_parameter",
    "assignment",
    "augmented_assignment",
    "expression_statement",
    "named_expression",
}


@dataclass
class ExtractPlan:
    """The computed shape of an extraction."""
    new_name: str
    parameters: List[str]
    returned: List[str]
    block_returns: bool
    base_indent: str
    enclosing_function_line: int
    enclosing_function_name: str


def _get_python_parser() -> Parser:
    return Parser(Language(tree_sitter_python.language()))
def _leading_ws(line: str) -> str:
    """Leading whitespace of a single line."""
    return line[: len(line) - len(line.lstrip(" \t"))]


def _walk_in_order(node):
    """Pre-order walk yielding descendants in document order."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        children = list(current.named_children)
        for child in reversed(children):
            stack.append(child)


def _collect_target_names(node, out: Set[str]) -> None:
    """Collect bound identifier names from an assignment target."""
    if node.type == "identifier":
        out.add(node.text.decode("utf-8", "replace"))
    elif node.type in ("tuple", "list", "expression_list"):
        for child in node.named_children:
            _collect_target_names(child, out)


def _bounds_identifier(parent, child) -> bool:
    """True if `child` is the binding target (name) side of `parent`."""
    if parent.type not in _BINDING_PARENT_TYPES:
        return False
    if parent.type == "assignment":
        left = parent.child_by_field_name("left")
        return left is not None and left.start_byte <= child.start_byte < left.end_byte
    if parent.type == "augmented_assignment":
        left = parent.child_by_field_name("left")
        return left is not None and left.start_byte <= child.start_byte < left.end_byte
    if parent.type == "for_statement":
        left = parent.child_by_field_name("left")
        return left is not None and left.start_byte <= child.start_byte < left.end_byte
    if parent.type in ("function_definition", "class_definition"):
        return parent.child_by_field_name("name") == child
    # names inside imports, parameters, as_pattern, with_item targets, etc.
    # are all bindings within the scope being analyzed.
    return True


def _collect_module_bindings(node, out: Set[str]) -> None:
    """Top-level bindings of a module (function/class/import/assignment)."""
    ntype = node.type
    if ntype in ("function_definition", "class_definition"):
        name = node.child_by_field_name("name")
        if name is not None:
            out.add(name.text.decode("utf-8", "replace"))
    elif ntype in ("import_statement", "import_from_statement"):
        for child in _walk_in_order(node):
            if child.is_named and child.type == "identifier":
                out.add(child.text.decode("utf-8", "replace"))
    elif ntype in ("assignment", "augmented_assignment", "named_expression"):
        left = node.child_by_field_name("left")
        if left is not None:
            _collect_target_names(left, out)
    elif ntype == "decorated_definition":
        for child in node.named_children:
            _collect_module_bindings(child, out)


def _find_enclosing_function(root, row_a: int, row_b: int):
    """Smallest function_definition whose span fully contains the block."""
    candidates = []
    for node in _walk_in_order(root):
        if node.type != "function_definition":
            continue
        if node.start_point.row <= row_a and node.end_point.row >= row_b:
            candidates.append(node)
    if not candidates:
        return None
    # smallest span wins — deepest enclosing function
    return min(
        candidates,
        key=lambda n: (n.end_point.row - n.start_point.row, n.start_point.row),
    )
def analyze_block(source: str, start_line: int, end_line: int) -> Optional[ExtractPlan]:
    """
    Analyze a line range and return an ExtractPlan describing how to extract
    it into a new function, or None when the block is empty / unusable.
    start_line / end_line are 1-based inclusive.
    """
    lines = source.splitlines(keepends=True)
    n = len(lines)
    if start_line < 1 or end_line < start_line or end_line > n:
        return None

    row_a = start_line - 1
    row_b = end_line - 1

    # base indentation: the indentation of the first non-empty line in range
    first_non_empty = None
    for i in range(row_a, row_b + 1):
        if lines[i].strip():
            first_non_empty = i
            break
    if first_non_empty is None:
        return None
    base_indent = _leading_ws(lines[first_non_empty])

    parser = _get_python_parser()
    tree = parser.parse(source.encode("utf-8"))
    root = tree.root_node

    block_identifiers: List[Tuple[str, int]] = []       # (name, row)
    assignment_targets: Set[str] = set()
    defined_in_block: Set[str] = set()
    block_returns = False

    for node in _walk_in_order(root):
        if not node.is_named:
            continue
        # only consider nodes fully inside the block range
        if node.start_point.row < row_a or node.end_point.row > row_b:
            continue

        if node.type == "identifier":
            name = node.text.decode("utf-8", "replace")
            block_identifiers.append((name, node.start_point.row))
            parent = node.parent
            if parent is not None and _bounds_identifier(parent, node):
                defined_in_block.add(name)

        elif node.type == "assignment":
            left = node.child_by_field_name("left")
            if left is not None:
                _collect_target_names(left, assignment_targets)

        elif node.type == "return_statement":
            block_returns = True

    assigned_in_block = set(assignment_targets)
    defined_in_block |= assigned_in_block

    module_level: Set[str] = set()
    for stmt in root.named_children:
        _collect_module_bindings(stmt, module_level)

    # free variables = used but not defined, not builtin, not module-global
    free_vars: List[str] = []
    seen: Set[str] = set()
    for name, _row in block_identifiers:
        if name in defined_in_block or name in module_level or name in _BUILTINS:
            continue
        if name not in seen:
            seen.add(name)
            free_vars.append(name)

    # return values = block assignments still referenced after the block
    enclosing = _find_enclosing_function(root, row_a, row_b)
    enclosing_line = 1
    enclosing_name = "(module-level block)"
    end_row = row_b
    if enclosing is not None:
        enclosing_line = enclosing.start_point.row + 1
        name_node = enclosing.child_by_field_name("name")
        enclosing_name = (
            name_node.text.decode("utf-8", "replace")
            if name_node is not None
            else enclosing_name
        )
        end_row = enclosing.end_point.row

    after_names: Set[str] = set()
    for node in _walk_in_order(root):
        if node.type != "identifier":
            continue
        row = node.start_point.row
        if row > row_b and row <= end_row:
            after_names.add(node.text.decode("utf-8", "replace"))

    returned: List[str] = []
    seen_ret: Set[str] = set()
    for name, _row in block_identifiers:
        if name in assignment_targets and name in after_names and name not in seen_ret:
            seen_ret.add(name)
            returned.append(name)

    return ExtractPlan(
        new_name="",  # filled in by the caller
        parameters=free_vars,
        returned=returned,
        block_returns=block_returns,
        base_indent=base_indent,
        enclosing_function_line=enclosing_line,
        enclosing_function_name=enclosing_name,
    )


def apply_extraction(
    source: str,
    start_line: int,
    end_line: int,
    new_name: str,
) -> Tuple[str, ExtractPlan]:
    """
    Produce the new file contents after extracting lines [start_line, end_line]
    into a top-level function named `new_name`.
    Returns (new_source, plan).
    """
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", new_name):
        raise ValueError(f"invalid function name: {new_name!r}")

    plan = analyze_block(source, start_line, end_line)
    if plan is None:
        raise ValueError(
            f"cannot extract lines {start_line}-{end_line}: "
            "range is empty or outside the file"
        )
    plan.new_name = new_name

    lines = source.splitlines(keepends=True)
    row_a = start_line - 1
    row_b = end_line - 1
    base = plan.base_indent

    # --- build the new function body --------------------------------------
    body_lines: List[str] = []
    for i in range(row_a, row_b + 1):
        raw = lines[i]
        if not raw.strip():
            body_lines.append("\n")
            continue
        body_lines.append("    " + raw[len(base):])

    body = "".join(body_lines)
    if not body.strip():
        body = "    pass\n"
    if plan.returned:
        ret = ", ".join(plan.returned)
        body = body.rstrip("\n") + f"\n    return {ret}\n"

    params = ", ".join(plan.parameters)
    new_fn = f"def {new_name}({params}):\n{body}\n"

    # --- build the call site ------------------------------------------------
    call = base
    if plan.block_returns:
        call += "return "
    elif plan.returned:
        call += ", ".join(plan.returned) + " = "
    call += f"{new_name}({params})\n"

    # --- splice everything together -----------------------------------------
    new_lines: List[str] = []
    insert_at = plan.enclosing_function_line - 1
    for i, ln in enumerate(lines):
        if i == insert_at:
            new_lines.append(new_fn)
        if row_a <= i <= row_b:
            if i == row_a:
                new_lines.append(call)
            continue
        new_lines.append(ln)

    return "".join(new_lines), plan


def extract_into_file(
    repo_root: str,
    rel_path: str,
    start_line: int,
    end_line: int,
    new_name: str,
) -> Tuple[str, ExtractPlan]:
    """
    Read `rel_path` inside repo_root, apply the extraction, and write it back.
    Returns (relative_path, plan).
    """
    filepath = os.path.join(repo_root, rel_path)
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()
    new_source, plan = apply_extraction(source, start_line, end_line, new_name)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_source)
    return rel_path, plan