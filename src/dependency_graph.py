"""
dependency_graph.py — MAP logic for Refactor Guard (Tree-sitter backend)

Multi-language reference scanning. The file's language is detected by
extension (.py -> Python grammar, .js/.ts -> JavaScript grammar), then the
matching Tree-sitter grammar's syntax tree is used to find two categories:

  - "static" references: normal identifier-like usage of the symbol
      Python:        identifier
      JavaScript:    identifier, property_identifier, shorthand_property_identifier
  - "dynamic-risk" references: the symbol's name appearing inside a string
      Python:        string_content      (e.g. getattr(obj, "symbol"))
      JavaScript:    string_fragment     (e.g. obj["symbol"] / eval("symbol"))

The public ScanResult / FileReferences interface is unchanged from the
original AST-based version, so every caller (and the demo output) behaves
exactly as before.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

import networkx as nx
from tree_sitter import Language, Parser

import tree_sitter_python
import tree_sitter_javascript


_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}

# ext -> (grammar module, static node types, dynamic-risk node types)
_GRAMMAR_SPECS = {
    ".py": (
        tree_sitter_python,
        ("identifier",),
        ("string_content",),
    ),
    ".js": (
        tree_sitter_javascript,
        ("identifier", "property_identifier", "shorthand_property_identifier"),
        ("string_fragment",),
    ),
    ".ts": (
        tree_sitter_javascript,
        ("identifier", "property_identifier", "shorthand_property_identifier"),
        ("string_fragment",),
    ),
}

_LANGUAGES: Dict[str, Language] = {}
_PARSERS: Dict[str, Parser] = {}


def _get_parser(ext: str) -> Parser:
    """Return the cached Tree-sitter Parser for a file extension."""
    if ext in _PARSERS:
        return _PARSERS[ext]

    grammar_module, _static_types, _dynamic_types = _GRAMMAR_SPECS[ext]

    lang = _LANGUAGES.get(ext)
    if lang is None:
        lang = Language(grammar_module.language())
        _LANGUAGES[ext] = lang

    parser = Parser(lang)
    _PARSERS[ext] = parser
    return parser


def _walk(node):
    """Iterative pre-order walk of a syntax tree (order doesn't matter here)."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(current.named_children)


@dataclass
class FileReferences:
    """References found in a single file."""
    static: bool = False
    dynamic_risk: bool = False
    static_lines: List[int] = field(default_factory=list)
    dynamic_lines: List[int] = field(default_factory=list)


@dataclass
class ScanResult:
    """Full scan result across the repo."""
    symbol: str
    files: Dict[str, FileReferences] = field(default_factory=dict)

    @property
    def static_files(self) -> List[str]:
        return [f for f, r in self.files.items() if r.static]

    @property
    def dynamic_risk_files(self) -> List[str]:
        return [f for f, r in self.files.items() if r.dynamic_risk]

    @property
    def has_dynamic_risk(self) -> bool:
        return len(self.dynamic_risk_files) > 0


def scan_source(source: str, symbol: str, extension: str) -> FileReferences:
    """
    Scan a single source file's raw text for references to `symbol`.
    `extension` selects the grammar (e.g. ".py" or ".js").
    """
    static_types, dynamic_types = _node_types_for(extension)
    parser = _get_parser(extension)
    tree = parser.parse(source.encode("utf-8"))
    symbol_bytes = symbol.encode("utf-8")

    static_lines: Set[int] = set()
    dynamic_lines: Set[int] = set()

    for node in _walk(tree.root_node):
        if not node.is_named:
            continue
        ntype = node.type
        if ntype not in static_types and ntype not in dynamic_types:
            continue
        if node.text != symbol_bytes:
            continue

        lineno = node.start_point.row + 1
        if ntype in static_types:
            static_lines.add(lineno)
        else:
            dynamic_lines.add(lineno)

    return FileReferences(
        static=len(static_lines) > 0,
        dynamic_risk=len(dynamic_lines) > 0,
        static_lines=sorted(static_lines),
        dynamic_lines=sorted(dynamic_lines),
    )


def _node_types_for(ext: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    try:
        _mod, static_types, dynamic_types = _GRAMMAR_SPECS[ext]
    except KeyError:
        raise ValueError(f"Unsupported file extension: {ext}")
    return static_types, dynamic_types


def scan_repo(repo_root: str, symbol: str) -> ScanResult:
    """
    Scan every supported source file (.py / .js / .ts) under repo_root for
    references to `symbol`. Returns a ScanResult with static and dynamic-risk
    references identified.
    """
    result = ScanResult(symbol=symbol)

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith('.') and d not in _SKIP_DIRS
        ]

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in _GRAMMAR_SPECS:
                continue

            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, repo_root)
            rel_path = rel_path.replace('\\', '/')

            try:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    source = f.read()
            except (OSError, UnicodeError):
                continue

            ref = scan_source(source, symbol, ext)
            if ref.static or ref.dynamic_risk:
                result.files[rel_path] = ref

    return result

def _toplevel_definitions(source: str, ext: str) -> Set[str]:
    """Return the top-level function/class names defined in `source`.

    Only names defined directly at module scope count — nested functions and
    class methods are ignored, because only top-level definitions are the
    natural targets of cross-file calls/imports.
    """
    parser = _get_parser(ext)
    tree = parser.parse(source.encode("utf-8"))
    root = tree.root_node
    names: Set[str] = set()

    def _name_of(node):
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return name_node.text.decode("utf-8")
        return None

    if ext == ".py":
        # def foo(...) / async def foo(...) / class Foo(...)
        def_types = ("function_definition", "class_definition")
    else:
        # function foo() / async function foo() / function* foo() / class Foo
        def_types = (
            "function_declaration",
            "generator_function_declaration",
            "class_declaration",
        )

    def _collect(node):
        if not node.is_named:
            return
        if node.type in def_types:
            nm = _name_of(node)
            if nm:
                names.add(nm)
            # definitions are captured whole — do not descend into bodies
            return
        if node.type == "export_statement":
            # export function foo() / export default function foo()
            for child in node.named_children:
                _collect(child)
            return
        if ext != ".py" and node.type in (
            "lexical_declaration",
            "variable_declaration",
        ):
            # const foo = function () {} / const foo = () => {}
            for dec in node.named_children:
                if dec.type != "variable_declarator":
                    continue
                value = dec.child_by_field_name("value")
                if value is not None and value.type in (
                    "arrow_function",
                    "function_expression",
                    "generator_function",
                    "function",
                ):
                    nm = _name_of(dec)
                    if nm:
                        names.add(nm)
            return

    for child in root.named_children:
        _collect(child)
    return names


def _used_names(source: str, ext: str) -> Set[str]:
    """Return names a file calls or imports from other modules.

    Covers simple calls (``foo()``), dotted/bracket calls (``mod.foo()``,
    ``mod["foo"]()``), Python imports, ES6 named imports, and destructured
    CommonJS requires (``const { foo } = require('./mod')``).
    """
    parser = _get_parser(ext)
    tree = parser.parse(source.encode("utf-8"))
    used: Set[str] = set()

    def _callee_name(fn):
        """Pulled identifier from a call target node."""
        if fn.type == "identifier":
            return fn.text.decode("utf-8")
        if fn.type in ("attribute", "member_expression"):
            text = fn.text.decode("utf-8")
            # drop the object part, keep the property/method name
            tail = text.rsplit(".", 1)[-1]
            tail = tail.strip().strip("[]'\"")
            if tail.isidentifier():
                return tail
        return None

    for node in _walk(tree.root_node):
        if not node.is_named:
            continue

        # ---- function calls ----
        if node.type in ("call", "call_expression"):
            fn = node.child_by_field_name("function")
            if fn is not None:
                name = _callee_name(fn)
                if name is not None:
                    used.add(name)

        # ---- Python: from X import Y, Z ----
        elif ext == ".py" and node.type == "import_from_statement":
            module_name = node.child_by_field_name("module_name")
            for child in node.named_children:
                if child is module_name or child.type != "dotted_name":
                    continue
                used.add(child.text.decode("utf-8"))

        # ---- Python: import X.Y.Z ----
        elif ext == ".py" and node.type == "import_statement":
            for child in node.named_children:
                if child.type == "dotted_name":
                    used.add(child.text.decode("utf-8").rsplit(".", 1)[-1])

        # ---- JavaScript: ES6 `import { A } from 'mod'` ----
        elif ext != ".py" and node.type == "import_statement":
            for spec in _walk(node):
                if spec.type == "import_specifier":
                    for ident in spec.named_children:
                        if ident.type == "identifier":
                            used.add(ident.text.decode("utf-8"))

        # ---- JavaScript: `const { a, b } = require('./mod')` ----
        elif ext != ".py" and node.type == "object_pattern":
            vd = node.parent
            if vd is not None and vd.type == "variable_declarator":
                value = vd.child_by_field_name("value")
                if (
                    value is not None
                    and value.type == "call_expression"
                    and value.child_by_field_name("function") is not None
                    and value.child_by_field_name("function").type == "identifier"
                    and value.child_by_field_name("function").text.decode("utf-8")
                    == "require"
                ):
                    for child in node.named_children:
                        if child.type == "shorthand_property_identifier_pattern":
                            used.add(child.text.decode("utf-8"))
                        elif child.type == "pair":
                            key = child.child_by_field_name("key")
                            if key is not None:
                                used.add(key.text.decode("utf-8"))

    return used
def blast_radius(repo_root: str, symbol: str) -> List[str]:
    """Return the files transitively affected by a change to `symbol`.

    Builds a directed call graph over the whole repo (Python / JavaScript /
    TypeScript, using the same Tree-sitter infra as `scan_repo`):

        caller_file -> defining_file   when caller calls or imports a
                                       top-level name that defining_file
                                       defines at module scope.

    A change to `symbol` affects the file that defines it, plus every file
    that calls or imports it directly, plus every file that calls *those*
    files' functions, and so on up the chain.  The transitive closure is
    computed with networkx's directed-graph traversal (`nx.ancestors`).

    Returns a sorted list of relative paths (forward slashes).
    """
    definitions: Dict[str, Set[str]] = {}
    file_uses: List[Tuple[str, Set[str]]] = []

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith('.') and d not in _SKIP_DIRS
        ]
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in _GRAMMAR_SPECS:
                continue
            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, repo_root)
            rel_path = rel_path.replace('\\', '/')

            try:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    source = f.read()
            except (OSError, UnicodeError):
                continue

            for name in _toplevel_definitions(source, ext):
                definitions.setdefault(name, set()).add(rel_path)
            file_uses.append((rel_path, _used_names(source, ext)))

    # build the file-level call graph
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_nodes_from(f for f, _ in file_uses)
    for caller, used in file_uses:
        for name in used:
            for defining_file in definitions.get(name, ()):
                if defining_file != caller:
                    graph.add_edge(caller, defining_file)

    if symbol not in definitions:
        return []

    affected = set()
    for defining_file in definitions[symbol]:
        affected.add(defining_file)
        # everything that can reach this file in the call graph depends on it
        affected.update(nx.ancestors(graph, defining_file))
    return sorted(affected)
