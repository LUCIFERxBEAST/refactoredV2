"""
snapshot.py — SNAPSHOT / ROLLBACK logic for Refactor Guard

Copies the entire target repo to a temp backup folder before editing,
and can restore it if tests fail.
"""

import os
import shutil
import stat
import tempfile
import time
from typing import Optional


def _force_remove_tree(path: str, max_attempts: int = 3) -> None:
    """
    Delete a directory tree even when it contains read-only entries (git
    object files are stored read-only) or files transiently locked by
    antivirus / search indexers on Windows.

    A plain shutil.rmtree raises PermissionError on the first such entry,
    which used to abort the rollback mid-way and leave the repo half-deleted.
    We clear read-only attributes between sweeps and retry with a short pause
    so auto-rollback restores a clean tree.  A persistent lock eventually
    re-raises, since nothing can be done about a file another process holds.
    """
    if not os.path.exists(path):
        return
    for attempt in range(1, max_attempts + 1):
        try:
            shutil.rmtree(path)
            return
        except OSError:
            if attempt == max_attempts:
                raise
            # Strip read-only/immutable bits so the next sweep can unlink.
            for base, dirs, files in os.walk(path):
                for name in files + dirs:
                    entry = os.path.join(base, name)
                    try:
                        os.chmod(entry, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
                    except OSError:
                        pass
            time.sleep(0.25 * attempt)


def create_snapshot(repo_root: str) -> str:
    """
    Copy the entire repo_root directory to a temporary backup location.
    Returns the path to the backup directory.
    """
    repo_name = os.path.basename(os.path.normpath(repo_root))
    backup_dir = tempfile.mkdtemp(prefix=f"refactor_guard_backup_")
    backup_path = os.path.join(backup_dir, repo_name)
    shutil.copytree(repo_root, backup_path)
    return backup_path


def restore_snapshot(backup_path: str, repo_root: str) -> None:
    """
    Restore the repo from the backup, completely overwriting whatever is
    currently at repo_root.
    """
    # Remove the current repo contents (robust to read-only/locked entries)
    _force_remove_tree(repo_root)
    # Copy the backup back
    shutil.copytree(backup_path, repo_root)


def cleanup_snapshot(backup_path: str) -> None:
    """Delete the backup directory."""
    _force_remove_tree(backup_path)
