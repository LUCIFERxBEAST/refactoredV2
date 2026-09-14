"""
src/ledger.py — Persistent refactor history store for Refactor Guard

Stores newline-delimited JSON records in <repo_root>/.refactor-guard/ledger.jsonl.
Provides fail-soft append, read, and failure-query capabilities so that no
ledger error can ever crash or disrupt a refactoring run.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LEDGER_DIRNAME = ".refactor-guard"
LEDGER_FILENAME = "ledger.jsonl"


def get_ledger_path(repo_root: str) -> str:
    """Return the absolute path to the ledger file for a given repo root."""
    return os.path.join(os.path.abspath(repo_root), LEDGER_DIRNAME, LEDGER_FILENAME)


def build_record(
    operation: str,
    symbol: str,
    params: Dict[str, Any],
    outcome: str,
    static_files: List[str],
    dynamic_risk_files: List[str],
    failure_symbols: Optional[List[str]] = None,
    test_cmd: str = "",
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Helper to construct a standard refactor history record."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()

    return {
        "timestamp": timestamp,
        "operation": operation,
        "symbol": symbol,
        "params": dict(params),
        "outcome": outcome,
        "static_files": list(static_files),
        "dynamic_risk_files": list(dynamic_risk_files),
        "failure_symbols": list(failure_symbols or []),
        "test_cmd": test_cmd,
    }


def append_record(repo_root: str, record: Dict[str, Any]) -> None:
    """Append a refactor record as a single JSON line to the ledger.

    Fail-soft: if the directory cannot be created or the file cannot be written,
    logs a warning and returns cleanly without raising.
    """
    try:
        if not repo_root:
            logger.warning("Refactor Guard ledger: empty repo_root provided to append_record.")
            return

        ledger_path = get_ledger_path(repo_root)
        ledger_dir = os.path.dirname(ledger_path)

        os.makedirs(ledger_dir, exist_ok=True)

        # Ensure timestamp exists
        rec_to_write = dict(record)
        if "timestamp" not in rec_to_write or not rec_to_write["timestamp"]:
            rec_to_write["timestamp"] = datetime.now(timezone.utc).isoformat()

        line = json.dumps(rec_to_write, default=list, ensure_ascii=False) + "\n"

        with open(ledger_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as exc:
        print(f"  ⚠ WARNING: Refactor Guard ledger write failed ({exc}); continuing without logging.")
        logger.warning("Refactor Guard ledger write failed for %s: %s", repo_root, exc)


def read_records(repo_root: str) -> List[Dict[str, Any]]:
    """Read all valid JSON records from the repository's ledger.

    Fail-soft: if the file does not exist, cannot be read, or contains corrupt
    lines, skips bad lines and returns all successfully parsed records without raising.
    """
    records: List[Dict[str, Any]] = []
    try:
        if not repo_root:
            return records

        ledger_path = get_ledger_path(repo_root)
        if not os.path.isfile(ledger_path):
            return records

        with open(ledger_path, "r", encoding="utf-8", errors="replace") as f:
            for line_no, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        records.append(data)
                    else:
                        print(f"  ⚠ WARNING: Ledger line {line_no} in {ledger_path} is not a JSON object; skipping.")
                except Exception as parse_err:
                    print(f"  ⚠ WARNING: Corrupt ledger line {line_no} in {ledger_path} ({parse_err}); skipping.")
    except Exception as exc:
        print(f"  ⚠ WARNING: Failed reading Refactor Guard ledger at {repo_root} ({exc}).")
        logger.warning("Failed reading Refactor Guard ledger at %s: %s", repo_root, exc)

    return records


def find_prior_failures(
    repo_root: str,
    operation: str,
    symbol: str,
) -> List[Dict[str, Any]]:
    """Return prior records for the same operation and symbol that resulted in rollback.

    Queries the repository's ledger for matching records where outcome == 'rolled_back'.
    Fail-soft: returns an empty list on any read error.
    """
    try:
        all_records = read_records(repo_root)
        return [
            rec for rec in all_records
            if rec.get("operation") == operation
            and rec.get("symbol") == symbol
            and rec.get("outcome") == "rolled_back"
        ]
    except Exception as exc:
        print(f"  ⚠ WARNING: Failed querying prior failures from ledger ({exc}).")
        logger.warning("Failed querying prior failures from ledger for %s: %s", repo_root, exc)
        return []


def find_prior_successes(
    repo_root: str,
    operation: Optional[str],
    symbol: str,
) -> List[Dict[str, Any]]:
    """Return prior records for the symbol (and optional operation) that resulted in success.

    Queries the repository's ledger for matching records where outcome == 'success'.
    Fail-soft: returns an empty list on any read error.
    """
    try:
        all_records = read_records(repo_root)
        return [
            rec for rec in all_records
            if (operation is None or rec.get("operation") == operation)
            and rec.get("symbol") == symbol
            and rec.get("outcome") == "success"
        ]
    except Exception as exc:
        print(f"  ⚠ WARNING: Failed querying prior successes from ledger ({exc}).")
        logger.warning("Failed querying prior successes from ledger for %s: %s", repo_root, exc)
        return []


def format_timestamp_date(timestamp: Optional[str]) -> str:
    """Extract a YYYY-MM-DD date string from an ISO timestamp.

    Fail-soft: returns 'unknown date' if timestamp is empty or cannot be parsed.
    """
    if not timestamp:
        return "unknown date"
    try:
        ts_str = str(timestamp).strip()
        if "T" in ts_str:
            return ts_str.split("T")[0]
        if " " in ts_str:
            return ts_str.split(" ")[0]
        return ts_str
    except Exception:
        return "unknown date"

