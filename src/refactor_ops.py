"""
refactor_ops.py — ACT logic for Refactor Guard

Performs word-boundary-safe rename of a symbol in files that have
confirmed static references. Uses regex replace so "total" inside
"subtotal" is never touched.
"""

import os
import re
from typing import List


def rename_symbol_in_file(
    filepath: str,
    old_symbol: str,
    new_symbol: str,
) -> int:
    """
    Rename old_symbol to new_symbol in a single file using word-boundary-safe
    regex. Returns the number of replacements made.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Use word boundaries (\b) so 'total' inside 'subtotal' is untouched
    pattern = r'\b' + re.escape(old_symbol) + r'\b'
    new_content, count = re.subn(pattern, new_symbol, content)

    if count > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)

    return count


def rename_in_files(
    repo_root: str,
    old_symbol: str,
    new_symbol: str,
    files: List[str],
) -> dict:
    """
    Rename old_symbol -> new_symbol in the given list of files (relative paths).
    Returns a dict mapping each file to the number of replacements made.
    """
    results = {}
    for rel_path in files:
        filepath = os.path.join(repo_root, rel_path)
        if os.path.isfile(filepath):
            count = rename_symbol_in_file(filepath, old_symbol, new_symbol)
            results[rel_path] = count
    return results
