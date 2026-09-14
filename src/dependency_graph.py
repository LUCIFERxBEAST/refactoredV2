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

