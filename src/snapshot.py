"""
snapshot.py — SNAPSHOT / ROLLBACK logic for Refactor Guard

Copies the entire target repo to a temp backup folder before editing,
and can restore it if tests fail.
"""

import os
import shutil
import tempfile
from typing import Optional


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
    # Remove the current repo contents
    if os.path.exists(repo_root):
        shutil.rmtree(repo_root)
    # Copy the backup back
    shutil.copytree(backup_path, repo_root)


def cleanup_snapshot(backup_path: str) -> None:
    """Delete the backup directory."""
    if os.path.exists(backup_path):
        shutil.rmtree(backup_path)
