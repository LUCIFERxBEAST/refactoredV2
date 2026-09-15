"""
snapshot.py — SNAPSHOT / ROLLBACK logic for Refactor Guard

Provides a scalable dual-strategy backup system:
1. Git repositories: Fast, lightweight Git snapshot using temporary index trees
   and throwaway refs (refs/refactor-guard/*). Captures both tracked changes and
   pre-existing untracked files without file copying or disk bloat.
   - Strictly scoped to repo_root via pathspecs.
   - The user's real .git/index is NEVER modified (isolated via GIT_INDEX_FILE).
   - Temporary index is seeded from HEAD to preserve files outside repo_root.
   - Handles repos with 0 commits (omits -p HEAD).
   - Automatically detects gitignored source files and falls back to copytree.
2. Non-Git directories: shutil.copytree fallback that excludes common large/
   irrelevant directories (node_modules, .git, venv, __pycache__, .pytest_cache).
"""

import atexit
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
from typing import List, Optional, Set

EXCLUDED_DIRS: Set[str] = {
    "node_modules",
    "venv",
    ".venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".refactor-guard",
}

_ACTIVE_SNAPSHOTS: Set[str] = set()


def _get_excluded_dirs(repo_root: str) -> Set[str]:
    """Return excluded directories for copy snapshots, scoping .git exclusion to real git repos."""
    dirs = set(EXCLUDED_DIRS)
    if is_git_repo(repo_root):
        dirs.add(".git")
    return dirs


def _ignore_large_dirs(directory: str, files: List[str]) -> Set[str]:
    return {f for f in files if f in EXCLUDED_DIRS or f == ".git"}


def _force_remove_file(filepath: str) -> None:
    """Safely remove a file, clearing read-only attributes if necessary."""
    try:
        os.remove(filepath)
    except OSError:
        try:
            os.chmod(filepath, stat.S_IWRITE | stat.S_IREAD)
            os.remove(filepath)
        except OSError:
            pass


def _force_remove_tree(path: str, max_attempts: int = 3) -> None:
    """
    Delete a directory tree even when it contains read-only entries (git
    object files are stored read-only) or files transiently locked by
    antivirus / search indexers on Windows.

    A plain shutil.rmtree raises PermissionError on the first such entry,
    which used to abort the rollback mid-way and leave the repo half-deleted.
    We clear read-only attributes between sweeps and retry with a short pause
    so auto-rollback restores a clean tree. A persistent lock eventually
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


def is_git_repo(repo_root: str) -> bool:
    """Check if repo_root is inside a git work tree and not ignored by an enclosing repo."""
    try:
        proc = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 or proc.stdout.strip() != "true":
            return False

        # If repo_root has its own .git, it is definitely a git repo
        if os.path.exists(os.path.join(repo_root, ".git")):
            return True

        # If it's a subdirectory of an enclosing repo, check if repo_root itself is gitignored (e.g. _demo*)
        ignore_check = subprocess.run(
            ["git", "-C", repo_root, "check-ignore", "-q", "."],
            capture_output=True,
            check=False,
        )
        if ignore_check.returncode == 0:
            return False

        return True
    except Exception:
        return False


def has_gitignored_source_files(repo_root: str) -> bool:
    """Check if repo_root contains gitignored source files (.py, .js, .ts) that git wouldn't capture."""
    try:
        proc = subprocess.run(
            ["git", "-C", repo_root, "ls-files", "--ignored", "--exclude-standard", "--others", "--", "."],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return False

        for f in proc.stdout.splitlines():
            ext = os.path.splitext(f)[1].lower()
            if ext in {".py", ".js", ".ts"}:
                parts = f.replace("\\", "/").split("/")
                if any(p in EXCLUDED_DIRS for p in parts):
                    continue
                return True
        return False
    except Exception:
        return False


def clean_stale_snapshots(repo_root: str) -> List[str]:
    """Delete any stale refs/refactor-guard/* refs left by previous interrupted runs."""
    cleaned = []
    try:
        proc = subprocess.run(
            ["git", "-C", repo_root, "for-each-ref", "--format=%(refname)", "refs/refactor-guard/"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            for ref in proc.stdout.splitlines():
                ref = ref.strip()
                if ref:
                    subprocess.run(["git", "-C", repo_root, "update-ref", "-d", ref], check=False, capture_output=True)
                    cleaned.append(ref)
    except Exception:
        pass
    return cleaned


def _atexit_cleanup() -> None:
    for snap in list(_ACTIVE_SNAPSHOTS):
        try:
            cleanup_snapshot(snap)
        except Exception:
            pass


atexit.register(_atexit_cleanup)


def _create_git_snapshot(repo_root: str) -> str:
    toplevel_proc = subprocess.run(
        ["git", "-C", repo_root, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    toplevel = os.path.abspath(toplevel_proc.stdout.strip())
    clean_stale_snapshots(toplevel)

    snap_id = uuid.uuid4().hex[:12]
    backup_dir = tempfile.mkdtemp(prefix=f"refactor_guard_backup_git_{snap_id}_")
    temp_idx = os.path.join(backup_dir, f"temp_index_{snap_id}")

    # Check if HEAD exists (empty repo detection)
    head_proc = subprocess.run(
        ["git", "-C", toplevel, "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    has_head = (head_proc.returncode == 0 and bool(head_proc.stdout.strip()))

    env = os.environ.copy()
    # CRITICAL: Never write to the user's real .git/index. All index operations use GIT_INDEX_FILE.
    env["GIT_INDEX_FILE"] = temp_idx

    try:
        # 1. Seed temp index with HEAD if it exists (preserves files outside repo_root)
        if has_head:
            subprocess.run(
                ["git", "-C", toplevel, "read-tree", "HEAD"],
                env=env,
                check=True,
                capture_output=True,
            )

        # 2. Add working tree changes scoped strictly to repo_root via pathspec '-- .'
        subprocess.run(
            ["git", "-C", repo_root, "add", "-A", "--", "."],
            env=env,
            check=True,
            capture_output=True,
        )

        # 3. Write tree from temp index
        tree_proc = subprocess.run(
            ["git", "-C", toplevel, "write-tree"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        tree_sha = tree_proc.stdout.strip()

        # 4. Commit tree: if repo has no commits, omit -p HEAD parent flag
        commit_cmd = ["git", "-C", toplevel, "commit-tree", tree_sha, "-m", f"refactor-guard snapshot {snap_id}"]
        if has_head:
            commit_cmd.extend(["-p", head_proc.stdout.strip()])
        commit_proc = subprocess.run(
            commit_cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        commit_sha = commit_proc.stdout.strip()

        # 5. Set throwaway ref
        ref_name = f"refs/refactor-guard/{snap_id}"
        subprocess.run(
            ["git", "-C", toplevel, "update-ref", ref_name, commit_sha],
            check=True,
            capture_output=True,
        )
    finally:
        if os.path.exists(temp_idx):
            os.remove(temp_idx)

    # Save snapshot metadata in backup_dir
    meta_path = os.path.join(backup_dir, "snapshot_meta.json")
    meta = {
        "strategy": "git",
        "repo_root": repo_root,
        "toplevel": toplevel,
        "snap_id": snap_id,
        "ref_name": ref_name,
        "tree_sha": tree_sha,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)

    _ACTIVE_SNAPSHOTS.add(backup_dir)
    return backup_dir


def _create_copy_snapshot(repo_root: str) -> str:
    repo_name = os.path.basename(os.path.normpath(repo_root))
    backup_dir = tempfile.mkdtemp(prefix="refactor_guard_backup_")
    backup_path = os.path.join(backup_dir, repo_name)
    excluded = _get_excluded_dirs(repo_root)
    shutil.copytree(repo_root, backup_path, ignore=lambda d, files: {f for f in files if f in excluded})
    _ACTIVE_SNAPSHOTS.add(backup_dir)
    return backup_path


def create_snapshot(repo_root: str) -> str:
    """
    Create a snapshot of repo_root before refactoring.
    Uses Git throwaway ref snapshot if repo_root is a git repo and has no gitignored source files;
    otherwise falls back to shutil.copytree excluding large/irrelevant directories.
    Returns the path to the backup directory/metadata.
    """
    repo_root = os.path.abspath(repo_root)

    if is_git_repo(repo_root):
        if has_gitignored_source_files(repo_root):
            print(f"  ⚠ WARNING: Gitignored source file(s) detected in {repo_root}; "
                  "falling back to directory copy snapshot.")
            return _create_copy_snapshot(repo_root)

        try:
            return _create_git_snapshot(repo_root)
        except Exception as e:
            print(f"  ⚠ WARNING: Git snapshot failed ({e}); falling back to directory copy snapshot.")
            return _create_copy_snapshot(repo_root)

    return _create_copy_snapshot(repo_root)


def _restore_git_snapshot(meta: dict, repo_root: str) -> None:
    toplevel = meta["toplevel"]
    tree_sha = meta["tree_sha"]
    snap_id = meta["snap_id"]

    temp_idx = os.path.join(tempfile.gettempdir(), f"rg_restore_idx_{snap_id}")
    env = os.environ.copy()
    # CRITICAL: Never write to the user's real .git/index. All index operations use GIT_INDEX_FILE.
    env["GIT_INDEX_FILE"] = temp_idx

    try:
        # 1. Read snapshot tree into temp index
        subprocess.run(
            ["git", "-C", toplevel, "read-tree", tree_sha],
            env=env,
            check=True,
            capture_output=True,
        )

        # 2. Checkout files scoped strictly to repo_root (pathspec scoped)
        files_proc = subprocess.run(
            ["git", "-C", repo_root, "ls-files", "-z", "--", "."],
            env=env,
            capture_output=True,
            check=True,
        )
        if files_proc.stdout:
            subprocess.run(
                ["git", "-C", repo_root, "checkout-index", "-f", "-z", "--stdin"],
                input=files_proc.stdout,
                env=env,
                check=True,
                capture_output=True,
            )

        # 3. Clean up untracked files created by refactor that were not in tree_sha
        tree_files_proc = subprocess.run(
            ["git", "-C", toplevel, "ls-tree", "-r", "--name-only", tree_sha],
            capture_output=True,
            text=True,
            check=True,
        )
        tree_files = set(tree_files_proc.stdout.splitlines())

        untracked_proc = subprocess.run(
            ["git", "-C", repo_root, "ls-files", "--others", "--exclude-standard", "--", "."],
            capture_output=True,
            text=True,
            check=True,
        )
        for uf in untracked_proc.stdout.splitlines():
            full_path = os.path.join(repo_root, uf)
            rel_to_top = os.path.relpath(full_path, toplevel).replace("\\", "/")
            if rel_to_top not in tree_files:
                if os.path.isfile(full_path) or os.path.islink(full_path):
                    os.remove(full_path)
                    # Clean empty parent directories up to repo_root
                    parent = os.path.dirname(full_path)
                    while parent and parent != repo_root and os.path.isdir(parent) and not os.listdir(parent):
                        os.rmdir(parent)
                        parent = os.path.dirname(parent)
    finally:
        if os.path.exists(temp_idx):
            os.remove(temp_idx)


def _restore_copy_snapshot(backup_path: str, repo_root: str) -> None:
    excluded = _get_excluded_dirs(repo_root)
    # 1. Remove files in repo_root not in backup_path (skipping excluded)
    for root, dirs, files in os.walk(repo_root, topdown=True):
        dirs[:] = [d for d in dirs if d not in excluded]
        rel_root = os.path.relpath(root, repo_root)
        backup_root = os.path.join(backup_path, rel_root) if rel_root != "." else backup_path
        for f in files:
            if not os.path.exists(os.path.join(backup_root, f)):
                _force_remove_file(os.path.join(root, f))

    # Remove empty dirs not in backup_path
    for root, dirs, files in os.walk(repo_root, topdown=False):
        rel_root = os.path.relpath(root, repo_root)
        if rel_root != ".":
            base_dir = rel_root.replace("\\", "/").split("/")[0]
            if base_dir in excluded:
                continue
            backup_root = os.path.join(backup_path, rel_root)
            if not os.path.exists(backup_root) and not os.listdir(root):
                try:
                    os.rmdir(root)
                except OSError:
                    _force_remove_tree(root)

    # 2. Before copying files back, force remove existing destination files (survives read-only files on Windows)
    for root, dirs, files in os.walk(backup_path):
        rel_root = os.path.relpath(root, backup_path)
        dest_root = os.path.join(repo_root, rel_root) if rel_root != "." else repo_root
        for f in files:
            dest_file = os.path.join(dest_root, f)
            if os.path.exists(dest_file):
                _force_remove_file(dest_file)

    # 3. Copy files back from backup_path with dirs_exist_ok=True
    shutil.copytree(backup_path, repo_root, dirs_exist_ok=True)


def restore_snapshot(backup_path: str, repo_root: str) -> None:
    """
    Restore repo_root from the snapshot.
    If Git snapshot: restores files scoped to repo_root via checkout-index and cleans up created files.
    If non-Git copy: restores files from backup directory, preserving excluded directories.
    """
    repo_root = os.path.abspath(repo_root)
    meta_path = os.path.join(backup_path, "snapshot_meta.json")

    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("strategy") == "git":
                _restore_git_snapshot(meta, repo_root)
                return
        except Exception:
            pass

    # Non-Git fallback restore
    _restore_copy_snapshot(backup_path, repo_root)


def cleanup_snapshot(backup_path: str) -> None:
    """Delete the backup directory and any throwaway git refs."""
    meta_path = os.path.join(backup_path, "snapshot_meta.json")
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("strategy") == "git":
                toplevel = meta.get("toplevel")
                ref_name = meta.get("ref_name")
                if toplevel and ref_name:
                    subprocess.run(
                        ["git", "-C", toplevel, "update-ref", "-d", ref_name],
                        check=False,
                        capture_output=True,
                    )
        except Exception:
            pass

    parent_dir = os.path.dirname(backup_path)

    if os.path.exists(backup_path):
        _force_remove_tree(backup_path)

    # If backup_dir was a wrapper directory (e.g. refactor_guard_backup_...) and is now empty, remove it
    if parent_dir and os.path.exists(parent_dir) and "refactor_guard_backup_" in parent_dir:
        try:
            if not os.listdir(parent_dir):
                _force_remove_tree(parent_dir)
        except Exception:
            pass

    _ACTIVE_SNAPSHOTS.discard(backup_path)
    _ACTIVE_SNAPSHOTS.discard(parent_dir)

