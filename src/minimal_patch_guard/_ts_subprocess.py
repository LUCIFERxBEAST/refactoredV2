"""
_ts_subprocess.py — Tree-sitter calls isolated in a child Python process.

The installed tree-sitter binding can segfault natively under some CPython
builds (a C-level crash that try/except cannot intercept).  Every call into
src/dependency_graph therefore runs in a subprocess; any failure returns an
empty-but-usable result so the review pipeline degrades to text heuristics
instead of dying.

A one-shot probe caches whether tree-sitter works at all.  Once the first
child process fails, all subsequent calls return empty results instantly
instead of spawning hundreds of doomed children (~1.8 s each on Windows).
Batch variants (``scan_repo_files_batch`` / ``blast_radius_files_batch``)
combine multiple symbols into a single child process so that even when
tree-sitter *does* work, we don't rebuild the dependency graph per symbol.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Dict, List, Optional, Set, Tuple

_PKG_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

# One-shot probe sentinel: None = untested, True = works, False = broken.
_TS_WORKING: Optional[bool] = None


def _run_script(script: str, args: List[str], timeout: int = 45):
    """Run ``script`` with ``sys.argv=[1..]`` in a child interpreter.

    ``sys.argv[-1]`` is always ``_PKG_ROOT`` (injected so
    ``from src.dependency_graph import ...`` resolves inside the child).
    Returns trailing JSON line or None.
    """
    argv = [sys.executable, "-c", script, *args, _PKG_ROOT]
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    line = proc.stdout.strip().splitlines()[-1]
    try:
        return json.loads(line)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# One-shot tree-sitter availability probe
# ---------------------------------------------------------------------------

def probe_tree_sitter(repo_root: str, timeout: int = 15) -> bool:
    """Return True if tree-sitter works in a child process.

    Result is cached for the lifetime of the process.  The first call
    spawns a single lightweight child; every subsequent call is free.
    """
    global _TS_WORKING
    if _TS_WORKING is not None:
        return _TS_WORKING
    script = (
        "import sys, json;"
        "sys.path.insert(0, sys.argv[-1]);"
        "from src.dependency_graph import scan_repo;"
        "res = scan_repo(sys.argv[1], 'json');"
        "print(json.dumps({'ok': True, 'files': len(res.static_files)}))"
    )
    data = _run_script(script, [repo_root], timeout=timeout)
    _TS_WORKING = isinstance(data, dict) and data.get("ok") is True
    return _TS_WORKING  # type: ignore[return-value]


def _ensure_probed(repo_root: str) -> bool:
    """Run the probe if it hasn't run yet.  Returns True if TS works."""
    if _TS_WORKING is not None:
        return _TS_WORKING  # type: ignore[return-value]
    return probe_tree_sitter(repo_root)


def reset_probe() -> None:
    """Reset the probe cache (for testing)."""
    global _TS_WORKING
    _TS_WORKING = None


# ---------------------------------------------------------------------------
# Single-symbol API (kept for backward-compat callers)
# ---------------------------------------------------------------------------

def scan_repo_files(repo_root: str, symbol: str,
                    timeout: int = 45) -> Tuple[Set[str], Set[str]]:
    """References to ``symbol`` under repo_root: (static, dynamic).

    Returns ``(set(), set())`` immediately if tree-sitter is known-broken.
    """
    if not _ensure_probed(repo_root):
        return set(), set()
    script = (
        "import sys, json;"
        "sys.path.insert(0, sys.argv[-1]);"
        "from src.dependency_graph import scan_repo;"
        "res = scan_repo(sys.argv[1], sys.argv[2]);"
        "print(json.dumps({'static_files': res.static_files,"
        " 'dynamic_risk_files': res.dynamic_risk_files}))"
    )
    data = _run_script(script, [repo_root, symbol], timeout=timeout)
    if not isinstance(data, dict):
        global _TS_WORKING
        _TS_WORKING = False
        return set(), set()
    return (set(data.get("static_files", [])),
            set(data.get("dynamic_risk_files", [])))


def blast_radius_files(repo_root: str, symbol: str,
                       timeout: int = 45) -> List[str]:
    """Transitive blast radius of ``symbol`` under repo_root (sorted rel)."""
    if not _ensure_probed(repo_root):
        return []
    script = (
        "import sys, json;"
        "sys.path.insert(0, sys.argv[-1]);"
        "from src.dependency_graph import blast_radius;"
        "print(json.dumps(blast_radius(sys.argv[1], sys.argv[2])))"
    )
    data = _run_script(script, [repo_root, symbol], timeout=timeout)
    if not isinstance(data, list):
        global _TS_WORKING
        _TS_WORKING = False
        return []
    return [str(f) for f in data]


# ---------------------------------------------------------------------------
# Batch API — one subprocess per batch instead of one per symbol
# ---------------------------------------------------------------------------

def scan_repo_files_batch(
    repo_root: str,
    symbols: List[str],
    timeout: int = 60,
) -> Dict[str, Tuple[Set[str], Set[str]]]:
    """Look up reference files for *all* symbols in a single child process.

    Returns ``{token: (static_files, dynamic_files)}`` for each symbol.
    If tree-sitter is broken the result is empty but returns instantly.
    """
    if not symbols:
        return {}
    if not _ensure_probed(repo_root):
        return {s: (set(), set()) for s in symbols}
    symbols_json = json.dumps(symbols)
    script = (
        "import sys, json;"
        "sys.path.insert(0, sys.argv[-1]);"
        "from src.dependency_graph import scan_repo;"
        "symbols = json.loads(sys.argv[2]);"
        "out = {};"
        "for sym in symbols:"
        "    try:"
        "        res = scan_repo(sys.argv[1], sym);"
        "        out[sym] = {'static_files': res.static_files,"
        "                     'dynamic_risk_files': res.dynamic_risk_files};"
        "    except Exception:"
        "        out[sym] = {'static_files': [], 'dynamic_risk_files': []};"
        "print(json.dumps(out))"
    )
    data = _run_script(script, [repo_root, symbols_json], timeout=timeout)
    if not isinstance(data, dict):
        global _TS_WORKING
        _TS_WORKING = False
        return {s: (set(), set()) for s in symbols}
    result: Dict[str, Tuple[Set[str], Set[str]]] = {}
    for sym in symbols:
        entry = data.get(sym, {})
        result[sym] = (
            set(entry.get("static_files", [])),
            set(entry.get("dynamic_risk_files", [])),
        )
    return result


def blast_radius_files_batch(
    repo_root: str,
    symbols: List[str],
    timeout: int = 60,
) -> Dict[str, List[str]]:
    """Compute blast radius for *all* symbols in a single child process.

    Returns ``{token: [file, ...]}``.  If tree-sitter is broken the result
    is empty but returns instantly.
    """
    if not symbols:
        return {}
    if not _ensure_probed(repo_root):
        return {s: [] for s in symbols}
    symbols_json = json.dumps(symbols)
    script = (
        "import sys, json;"
        "sys.path.insert(0, sys.argv[-1]);"
        "from src.dependency_graph import blast_radius;"
        "symbols = json.loads(sys.argv[2]);"
        "out = {};"
        "for sym in symbols:"
        "    try:"
        "        out[sym] = blast_radius(sys.argv[1], sym);"
        "    except Exception:"
        "        out[sym] = [];"
        "print(json.dumps(out))"
    )
    data = _run_script(script, [repo_root, symbols_json], timeout=timeout)
    if not isinstance(data, dict):
        global _TS_WORKING
        _TS_WORKING = False
        return {s: [] for s in symbols}
    return {s: [str(f) for f in data.get(s, [])] for s in symbols}