"""
refactor_ops.py — ACT logic for Refactor Guard

Performs precise AST identifier-based rename of a symbol in files that have
confirmed static references. Uses Tree-sitter byte-range spans of verified
identifier nodes to rebuild the file, ensuring comments, docstrings, and
string literals are preserved without accidental modification.
"""

import os
import re
from typing import Dict, List, Optional, Tuple

from .dependency_graph import _GRAMMAR_SPECS, scan_source


def rename_symbol_in_file(
    filepath: str,
    old_symbol: str,
    new_symbol: str,
    spans: Optional[List[Tuple[int, int]]] = None,
) -> int:
    """
    Rename old_symbol to new_symbol in a single file by operating entirely on
    bytes, rebuilding the file from Tree-sitter AST static identifier byte-range
    spans. If Tree-sitter parsing fails or produces an error node, falls back to
    word-boundary regex for that file only.
    """
    with open(filepath, 'rb') as f:
        content_bytes = f.read()

    ext = os.path.splitext(filepath)[1].lower()
    old_bytes = old_symbol.encode("utf-8")
    new_bytes = new_symbol.encode("utf-8")

    def _fallback_regex() -> int:
        try:
            content_str = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            content_str = content_bytes.decode("utf-8", errors="replace")
        pattern = r'\b' + re.escape(old_symbol) + r'\b'
        new_content_str, count = re.subn(pattern, new_symbol, content_str)
        if count > 0:
            with open(filepath, 'wb') as f_out:
                f_out.write(new_content_str.encode("utf-8"))
        return count

    # If extension has no Tree-sitter grammar support, use regex
    if ext not in _GRAMMAR_SPECS:
        return _fallback_regex()

    # If spans not provided, parse via Tree-sitter
    if spans is None:
        try:
            ref = scan_source(content_bytes, old_symbol, ext)
            if ref.has_parse_error:
                print(f"WARNING: Tree-sitter parsing produced an error node for {filepath}; falling back to regex.")
                return _fallback_regex()
            spans = ref.static_spans
        except Exception as e:
            print(f"WARNING: Tree-sitter parsing failed for {filepath} ({e}); falling back to regex.")
            return _fallback_regex()

    if not spans:
        return 0

    # Deduplicate and sort spans in ascending byte offset order
    sorted_spans = sorted(list(set(spans)), key=lambda s: (s[0], s[1]))

    # Hard assertion / validation: spans must match old_symbol's bytes exactly
    spans_valid = all(
        0 <= s <= e <= len(content_bytes) and content_bytes[s:e] == old_bytes
        for s, e in sorted_spans
    )
    if not spans_valid:
        # On mismatch, fall back to a fresh scan_source() call rather than using stale spans
        try:
            ref = scan_source(content_bytes, old_symbol, ext)
            if ref.has_parse_error:
                print(f"WARNING: Tree-sitter error node on re-scan for {filepath}; falling back to regex.")
                return _fallback_regex()
            sorted_spans = ref.static_spans
            fresh_valid = all(
                0 <= s <= e <= len(content_bytes) and content_bytes[s:e] == old_bytes
                for s, e in sorted_spans
            )
            if not fresh_valid:
                print(f"WARNING: Tree-sitter spans mismatched on re-scan for {filepath}; falling back to regex.")
                return _fallback_regex()
        except Exception as e:
            print(f"WARNING: Fresh scan_source() failed for {filepath} ({e}); falling back to regex.")
            return _fallback_regex()

    if not sorted_spans:
        return 0

    # Reconstruct the file purely using byte slices and encoded symbols
    chunks: List[bytes] = []
    last_idx = 0
    count = 0
    for start, end in sorted_spans:
        if start < last_idx:
            # Overlapping span guard
            continue
        chunks.append(content_bytes[last_idx:start])
        chunks.append(new_bytes)
        last_idx = end
        count += 1
    chunks.append(content_bytes[last_idx:])

    new_content_bytes = b"".join(chunks)

    with open(filepath, 'wb') as f:
        f.write(new_content_bytes)

    return count


def rename_in_files(
    repo_root: str,
    old_symbol: str,
    new_symbol: str,
    files: List[str],
    file_spans: Optional[Dict[str, List[Tuple[int, int]]]] = None,
) -> dict:
    """
    Rename old_symbol -> new_symbol in the given list of files (relative paths).
    Optionally reuses precomputed AST static spans from `scan_repo`.
    Returns a dict mapping each file to the number of replacements made.
    """
    results = {}
    for rel_path in files:
        filepath = os.path.join(repo_root, rel_path)
        if os.path.isfile(filepath):
            spans = file_spans.get(rel_path) if file_spans else None
            count = rename_symbol_in_file(filepath, old_symbol, new_symbol, spans=spans)
            results[rel_path] = count
    return results

