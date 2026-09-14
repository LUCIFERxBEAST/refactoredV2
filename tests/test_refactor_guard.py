"""
Unit tests for dependency_graph.py (MAP), refactor_ops.py (ACT),
extract_function.py, move_symbol.py, snapshot.py, and test_runner.py.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import pytest

from src.dependency_graph import blast_radius, scan_repo, scan_source
from src.refactor_ops import rename_symbol_in_file, rename_in_files
from src.snapshot import (
    create_snapshot,
    restore_snapshot,
    cleanup_snapshot,
    clean_stale_snapshots,
    is_git_repo,
    has_gitignored_source_files,
    EXCLUDED_DIRS,
)
from src.test_runner import find_missing_symbols, diagnose_failures, build_command
from src.extract_function import analyze_block, apply_extraction, extract_into_file
from src.move_symbol import move_symbol, find_top_level_definition, dotted_module

SAMPLE_REPO = os.path.join(os.path.dirname(__file__), "sample_repo")
SAMPLE_REPO_JS = os.path.join(os.path.dirname(__file__), "sample_repo_js")
MATHUTILS = os.path.join(SAMPLE_REPO, "pkg", "mathutils.py")


def _sample_repo_copy(tmp_path, name="repo"):
    repo = tmp_path / name
    shutil.copytree(SAMPLE_REPO, repo)
    return repo


def _pytest_in(repo) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(repo), capture_output=True, text=True,
    )


class TestScanRepo:

    def test_finds_definition_in_mathutils(self):
        result = scan_repo(SAMPLE_REPO, "compute_total")
        assert "pkg/mathutils.py" in result.static_files

    def test_finds_static_import_in_reporter(self):
        result = scan_repo(SAMPLE_REPO, "compute_total")
        assert "pkg/reporter.py" in result.static_files

    def test_identifies_dynamic_risk(self):
        result = scan_repo(SAMPLE_REPO, "compute_total")
        assert "pkg/dynamic_caller.py" in result.dynamic_risk_files
        assert result.has_dynamic_risk

    def test_dynamic_caller_not_in_static(self):
        result = scan_repo(SAMPLE_REPO, "compute_total")
        assert "pkg/dynamic_caller.py" not in result.static_files

    def test_build_report_no_dynamic_risk(self):
        result = scan_repo(SAMPLE_REPO, "build_report")
        assert not result.has_dynamic_risk
        assert "pkg/mathutils.py" in result.static_files

    def test_symbol_not_found(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\n")
        result = scan_repo(str(tmp_path), "missing_symbol")
        assert len(result.files) == 0

    def test_word_boundary_at_ast_level(self, tmp_path):
        code = "subtotal = total + 1\ntotal_count = total\n"
        (tmp_path / "a.py").write_text(code)
        result = scan_repo(str(tmp_path), "total")
        assert "a.py" in result.static_files

    def test_async_def_detected(self, tmp_path):
        (tmp_path / "a.py").write_text("async def do_work(): pass\n")
        result = scan_repo(str(tmp_path), "do_work")
        assert "a.py" in result.static_files

    def test_class_def_detected(self, tmp_path):
        (tmp_path / "a.py").write_text("class MyClass: pass\n")
        result = scan_repo(str(tmp_path), "MyClass")
        assert "a.py" in result.static_files

class TestRenameInFile:

    def test_basic_rename(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("total = 10\n")
        count = rename_symbol_in_file(str(f), "total", "sum")
        assert count == 1
        assert f.read_text() == "sum = 10\n"

    def test_word_boundary_skips_subtotal(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("total = 10\nsubtotal = total + 5\n")
        count = rename_symbol_in_file(str(f), "total", "sum")
        assert count == 2
        content = f.read_text()
        assert "subtotal" in content
        assert content == "sum = 10\nsubtotal = sum + 5\n"

    def test_word_boundary_skips_total_count(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("total_count = total\n")
        count = rename_symbol_in_file(str(f), "total", "sum")
        assert count == 1
        content = f.read_text()
        assert "total_count = sum" in content

    def test_import_rename(self, tmp_path):
        code = "from pkg import compute_total\ncompute_total([1, 2])\n"
        f = tmp_path / "a.py"
        f.write_text(code)
        count = rename_symbol_in_file(str(f), "compute_total", "sum_items")
        assert count == 2
        content = f.read_text()
        assert "sum_items" in content
        assert "compute_total" not in content

    def test_no_match_returns_zero(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("x = 1\n")
        count = rename_symbol_in_file(str(f), "total", "sum")
        assert count == 0

    def test_multiline_replacements(self, tmp_path):
        code = (
            "import mathutils\n"
            "result = mathutils.compute_total([1,2,3])\n"
            "print(result)\n"
        )
        f = tmp_path / "a.py"
        f.write_text(code)
        count = rename_symbol_in_file(str(f), "compute_total", "sum_items")
        assert count == 1


class TestRenameInFiles:

    def test_renames_in_multiple_files(self, tmp_path):
        (tmp_path / "a.py").write_text("compute_total([1])\n")
        (tmp_path / "b.py").write_text("from pkg import compute_total\n")
        results = rename_in_files(
            str(tmp_path), "compute_total", "sum_items", ["a.py", "b.py"]
        )
        assert results["a.py"] == 1
        assert results["b.py"] == 1

    def test_nonexistent_file_skipped(self, tmp_path):
        results = rename_in_files(str(tmp_path), "total", "sum", ["nonexistent.py"])
        assert results == {}


class TestSnapshot:

    def test_roundtrip(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "a.py").write_text("x = 1\n")
        snap = create_snapshot(str(repo))
        try:
            (repo / "a.py").write_text("x = 2\n")
            (repo / "new.py").write_text("y = 3\n")
            restore_snapshot(snap, str(repo))
            assert (repo / "a.py").read_text() == "x = 1\n"
            assert not (repo / "new.py").exists()
        finally:
            cleanup_snapshot(snap)

    def test_git_snapshot_seeded_index_preserves_files_outside_repo_root(self, tmp_path):
        """
        Exercises the seeded-index path: create a repo with files both inside and
        outside repo_root, run a snapshot+restore cycle, and assert files OUTSIDE
        repo_root are byte-for-byte unchanged afterward.
        """
        top = tmp_path / "git_top"
        top.mkdir()
        subprocess.run(["git", "init"], cwd=str(top), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(top), check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(top), check=True)

        # Committed files outside repo_root (including binary and utf-8 data)
        outside_committed = top / "outside_committed.txt"
        outside_committed.write_bytes(b"outside committed binary data \x00\xff\xfe\x42")
        outside_subdir = top / "outside_subdir"
        outside_subdir.mkdir()
        outside_sub_file = outside_subdir / "sub_data.bin"
        outside_sub_file.write_bytes(b"outside nested binary \x10\x20\x30\x40")

        # Subdirectory that represents repo_root
        sub_project = top / "sub_project"
        sub_project.mkdir()
        inside_py = sub_project / "inside.py"
        inside_py.write_text("orig_inside = 100\n", encoding="utf-8")

        subprocess.run(["git", "add", "-A"], cwd=str(top), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(top), check=True, capture_output=True)

        # Uncommitted / untracked file outside repo_root
        outside_untracked = top / "outside_untracked.log"
        outside_untracked.write_bytes(b"untracked log data outside repo_root \xaa\xbb\xcc")

        # Record exact byte content of all files outside repo_root before snapshot
        outside_files = [outside_committed, outside_sub_file, outside_untracked]
        outside_bytes_before = {p: p.read_bytes() for p in outside_files}

        # Take snapshot strictly scoped to sub_project (repo_root)
        snap = create_snapshot(str(sub_project))
        try:
            # Verify git strategy was used and tree_sha was recorded
            meta_path = os.path.join(snap, "snapshot_meta.json")
            assert os.path.isfile(meta_path)
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            assert meta["strategy"] == "git"

            # Verify the snapshot tree SHA was seeded from HEAD and includes outside files
            tree_sha = meta["tree_sha"]
            tree_proc = subprocess.run(
                ["git", "-C", str(top), "ls-tree", "-r", "--name-only", tree_sha],
                capture_output=True,
                text=True,
                check=True,
            )
            tree_paths = set(tree_proc.stdout.splitlines())
            assert "outside_committed.txt" in tree_paths
            assert "outside_subdir/sub_data.bin" in tree_paths
            assert "sub_project/inside.py" in tree_paths

            # Mutate and create files INSIDE repo_root
            inside_py.write_text("mutated_inside = 999\n", encoding="utf-8")
            created_during_refactor = sub_project / "created_by_refactor.py"
            created_during_refactor.write_text("new_var = 1\n", encoding="utf-8")
            nested_created = sub_project / "nested" / "deep.py"
            nested_created.parent.mkdir()
            nested_created.write_text("nested = True\n", encoding="utf-8")

            # Restore snapshot
            restore_snapshot(snap, str(sub_project))

            # 1. Assert inside repo_root is perfectly restored
            assert inside_py.read_text(encoding="utf-8") == "orig_inside = 100\n"
            assert not created_during_refactor.exists()
            assert not nested_created.exists()
            assert not (sub_project / "nested").exists()

            # 2. Assert outside repo_root is BYTE-FOR-BYTE UNCHANGED
            for p in outside_files:
                assert p.exists(), f"File outside repo_root was deleted: {p}"
                assert p.read_bytes() == outside_bytes_before[p], (
                    f"File outside repo_root was altered: {p}"
                )
        finally:
            cleanup_snapshot(snap)

    def test_git_snapshot_three_simultaneous_states(self, tmp_path):
        """
        Verify that a repo with committed, staged-uncommitted, and untracked files
        restores all three correctly and cleans up any new files added during refactor.
        """
        repo = tmp_path / "repo_states"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)

        # 1. Committed file
        f_committed = repo / "committed.py"
        f_committed.write_text("committed_v1 = True\n")
        subprocess.run(["git", "add", "committed.py"], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-m", "first"], cwd=str(repo), check=True)

        # 2. Staged-uncommitted file
        f_staged = repo / "staged.py"
        f_staged.write_text("staged_v1 = True\n")
        subprocess.run(["git", "add", "staged.py"], cwd=str(repo), check=True)

        # 3. Untracked file
        f_untracked = repo / "untracked.py"
        f_untracked.write_text("untracked_v1 = True\n")

        snap = create_snapshot(str(repo))
        try:
            # Mutate all three
            f_committed.write_text("committed_v2 = False\n")
            f_staged.write_text("staged_v2 = False\n")
            f_untracked.write_text("untracked_v2 = False\n")
            # Create a new file during refactor
            f_new = repo / "added_by_refactor.py"
            f_new.write_text("bad = True\n")

            restore_snapshot(snap, str(repo))

            assert f_committed.read_text() == "committed_v1 = True\n"
            assert f_staged.read_text() == "staged_v1 = True\n"
            assert f_untracked.read_text() == "untracked_v1 = True\n"
            assert not f_new.exists()
        finally:
            cleanup_snapshot(snap)

    def test_git_snapshot_never_modifies_real_git_index(self, tmp_path):
        """
        Verify that GIT_INDEX_FILE isolation ensures the user's real .git/index
        is NEVER modified or corrupted during snapshot and restore operations.
        """
        repo = tmp_path / "index_isolation"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)

        (repo / "tracked.py").write_text("val = 1\n")
        (repo / "staged.py").write_text("staged_val = 1\n")
        subprocess.run(["git", "add", "tracked.py"], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), check=True)
        subprocess.run(["git", "add", "staged.py"], cwd=str(repo), check=True)

        real_index = repo / ".git" / "index"
        assert real_index.exists()
        index_bytes_before = real_index.read_bytes()
        index_hash_before = hashlib.sha256(index_bytes_before).hexdigest()
        index_mtime_before = real_index.stat().st_mtime_ns

        snap = create_snapshot(str(repo))
        try:
            (repo / "tracked.py").write_text("val = 2\n")
            restore_snapshot(snap, str(repo))

            index_bytes_after = real_index.read_bytes()
            index_hash_after = hashlib.sha256(index_bytes_after).hexdigest()
            index_mtime_after = real_index.stat().st_mtime_ns

            assert index_hash_before == index_hash_after
            assert index_bytes_before == index_bytes_after
            assert index_mtime_before == index_mtime_after
        finally:
            cleanup_snapshot(snap)

    def test_git_snapshot_zero_commits_repo(self, tmp_path):
        """
        Verify that a newly git-init'd repository with 0 commits (no HEAD)
        is supported without failing on '-p HEAD'.
        """
        repo = tmp_path / "zero_commit_repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)

        # No commits yet!
        head_proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            check=False,
        )
        assert head_proc.returncode != 0

        (repo / "initial.py").write_text("x = 42\n")
        snap = create_snapshot(str(repo))
        try:
            (repo / "initial.py").write_text("x = 999\n")
            (repo / "extra.py").write_text("extra = True\n")

            restore_snapshot(snap, str(repo))

            assert (repo / "initial.py").read_text() == "x = 42\n"
            assert not (repo / "extra.py").exists()
        finally:
            cleanup_snapshot(snap)

    def test_gitignored_source_file_triggers_copytree_fallback(self, tmp_path):
        """
        Verify that gitignored source files (.py, .js, .ts) trigger a warning
        and fall back to copytree snapshot so recoverability is never silently lost.
        """
        repo = tmp_path / "ignored_src_repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)

        (repo / ".gitignore").write_text("secret_plugin.py\n")
        (repo / "tracked.py").write_text("normal = 1\n")
        subprocess.run(["git", "add", ".gitignore", "tracked.py"], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), check=True)

        (repo / "secret_plugin.py").write_text("secret_key = 'abc'\n")

        assert has_gitignored_source_files(str(repo)) is True

        snap = create_snapshot(str(repo))
        try:
            # Metadata file should not exist because copytree strategy was used
            meta_path = os.path.join(snap, "snapshot_meta.json")
            assert not os.path.exists(meta_path)

            (repo / "secret_plugin.py").write_text("secret_key = 'corrupted'\n")
            (repo / "tracked.py").write_text("normal = 2\n")

            restore_snapshot(snap, str(repo))

            assert (repo / "secret_plugin.py").read_text() == "secret_key = 'abc'\n"
            assert (repo / "tracked.py").read_text() == "normal = 1\n"
        finally:
            cleanup_snapshot(snap)

    def test_cleanup_stale_snapshots_and_refs(self, tmp_path):
        """
        Verify that clean_stale_snapshots removes orphaned refs/refactor-guard/* refs.
        """
        repo = tmp_path / "stale_refs_repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "root"], cwd=str(repo), check=True)

        subprocess.run(
            ["git", "-C", str(repo), "update-ref", "refs/refactor-guard/deadbeef01", "HEAD"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "update-ref", "refs/refactor-guard/deadbeef02", "HEAD"],
            check=True,
        )

        cleaned = clean_stale_snapshots(str(repo))
        assert "refs/refactor-guard/deadbeef01" in cleaned
        assert "refs/refactor-guard/deadbeef02" in cleaned

        remaining = subprocess.run(
            ["git", "-C", str(repo), "for-each-ref", "refs/refactor-guard/"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert remaining == ""

    def test_nongit_excluded_directories_skipped(self, tmp_path):
        """
        Verify that non-git copy snapshot excludes large irrelevant directories
        (node_modules, venv, __pycache__) during copy and preserves them on restore.
        """
        nongit = tmp_path / "nongit_dir"
        nongit.mkdir()

        (nongit / "main.py").write_text("val = 1\n")
        nm = nongit / "node_modules" / "some_pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("console.log(1);\n")

        cache = nongit / "__pycache__"
        cache.mkdir()
        (cache / "main.cpython-312.pyc").write_bytes(b"\x00\x01\x02")

        snap = create_snapshot(str(nongit))
        try:
            # Assert node_modules and __pycache__ were not copied into snapshot
            assert not os.path.exists(os.path.join(snap, "node_modules"))
            assert not os.path.exists(os.path.join(snap, "__pycache__"))
            assert os.path.exists(os.path.join(snap, "main.py"))

            # Mutate main.py and add a new file
            (nongit / "main.py").write_text("val = 2\n")
            (nongit / "unwanted.py").write_text("trash\n")

            restore_snapshot(snap, str(nongit))

            assert (nongit / "main.py").read_text() == "val = 1\n"
            assert not (nongit / "unwanted.py").exists()
            # node_modules and __pycache__ in repo are preserved
            assert (nm / "index.js").read_text() == "console.log(1);\n"
            assert (cache / "main.cpython-312.pyc").read_bytes() == b"\x00\x01\x02"
        finally:
            cleanup_snapshot(snap)


class TestBuildCommand:

    def test_pytest_uses_current_python(self):
        cmd = build_command("pytest -q")
        assert cmd[0] == sys.executable
        assert cmd[1] == "-m"
        assert cmd[2] == "pytest"
        assert cmd[3:] == ["-q"]

    def test_non_pytest_passthrough(self):
        cmd = build_command("python run_tests.py --verbose")
        assert cmd == ["python", "run_tests.py", "--verbose"]


class TestFindMissingSymbols:

    def test_name_error(self):
        out = "E   NameError: name 'compute_total' is not defined"
        assert find_missing_symbols(out, "compute_total") == [
            ("compute_total", None)
        ]

    def test_attribute_error(self):
        out = ("E   AttributeError: module 'pkg.mathutils' "
               "has no attribute 'compute_total'")
        results = find_missing_symbols(out, "compute_total")
        assert len(results) == 1
        assert results[0][0] == "compute_total"

    def test_import_error(self):
        out = ("E   ImportError: cannot import name 'compute_total' "
               "from 'pkg.mathutils'")
        results = find_missing_symbols(out, "compute_total")
        assert len(results) == 1
        assert results[0] == ("compute_total", "pkg.mathutils")

    def test_no_match(self):
        out = "E   NameError: name 'other_thing' is not defined"
        assert find_missing_symbols(out, "compute_total") == []


class TestDiagnoseFailures:

    def test_blames_dynamic_file(self):
        out = ("E   AttributeError: module 'pkg.mathutils' "
               "has no attribute 'compute_total'")
        diag = diagnose_failures(out, "compute_total", ["pkg/dynamic_caller.py"])
        assert "compute_total" in diag
        assert "pkg/dynamic_caller.py" in diag
        assert "likely caused by the dynamic reference" in diag.lower()

    def test_no_dynamic_files(self):
        out = "E   NameError: name 'x' is not defined"
        diag = diagnose_failures(out, "x", [])
        assert "No dynamic-risk references" in diag

    def test_python_dynamic_file_uses_python_example(self):
        out = ("E   AttributeError: module 'pkg.mathutils' "
               "has no attribute 'compute_total'")
        diag = diagnose_failures(out, "compute_total", ["pkg/dynamic_caller.py"])
        assert "getattr(obj, 'symbol')" in diag
        assert "bracket-notation" not in diag

    def test_js_dynamic_file_uses_js_example(self):
        out = "TypeError: mathutils.computeTotal is not a function"
        diag = diagnose_failures(out, "computeTotal", ["pkg/dynamic_call.js"])
        assert "obj['symbol']" in diag
        assert "bracket-notation" in diag
        assert "getattr" not in diag

    def test_mixed_languages_show_both_examples(self):
        out = "NameError: name 'swap' is not defined"
        diag = diagnose_failures(out, "swap", ["a.py", "b.js"])
        assert "getattr(obj, 'symbol') or obj['symbol']" in diag

    def test_duplicate_failures_are_deduplicated(self):
        out = ("TypeError: mathutils.computeTotal is not a function\n"
               "TypeError: mathutils.computeTotal is not a function")
        diag = diagnose_failures(out, "computeTotal", ["pkg/dynamic_call.js"])
        assert diag.count("is missing") == 1


class TestSampleRepoIntegration:

    def test_full_scan_compute_total(self):
        result = scan_repo(SAMPLE_REPO, "compute_total")
        assert "pkg/mathutils.py" in result.static_files
        assert "pkg/reporter.py" in result.static_files
        assert "pkg/dynamic_caller.py" in result.dynamic_risk_files
        assert result.has_dynamic_risk

    def test_full_scan_build_report(self):
        result = scan_repo(SAMPLE_REPO, "build_report")
        assert "pkg/mathutils.py" in result.static_files
        assert not result.has_dynamic_risk

    def test_decorator_detected(self, tmp_path):
        code = "@my_decorator\ndef foo(): pass\n"
        (tmp_path / "a.py").write_text(code)
        result = scan_repo(str(tmp_path), "my_decorator")
        assert "a.py" in result.static_files
class TestJsScanning:
    """Tree-sitter JavaScript / TypeScript scanning."""

    def test_js_static_and_dynamic(self, tmp_path):
        code = (
            'const m = require("./m");\n'
            "function computeTotal(items) { return 0; }\n"
            "module.exports = { computeTotal };\n"
            'const fn = m["computeTotal"];\n'
        )
        (tmp_path / "a.js").write_text(code)
        result = scan_repo(str(tmp_path), "computeTotal")
        assert "a.js" in result.static_files
        assert "a.js" in result.dynamic_risk_files

    def test_js_member_access_is_static(self, tmp_path):
        (tmp_path / "a.js").write_text("m.computeTotal([1, 2]);\n")
        result = scan_repo(str(tmp_path), "computeTotal")
        assert "a.js" in result.static_files
        assert not result.has_dynamic_risk

    def test_js_shorthand_export_is_static(self, tmp_path):
        (tmp_path / "a.js").write_text("module.exports = { buildReport };\n")
        result = scan_repo(str(tmp_path), "buildReport")
        assert "a.js" in result.static_files

    def test_ts_extension_scans_like_js(self, tmp_path):
        (tmp_path / "a.ts").write_text("m.computeTotal?.(x);\n")
        result = scan_repo(str(tmp_path), "computeTotal")
        assert "a.ts" in result.static_files

    def test_symbol_not_found_in_js(self, tmp_path):
        (tmp_path / "a.js").write_text("const x = 1;\n")
        result = scan_repo(str(tmp_path), "computeTotal")
        assert len(result.files) == 0


class TestScanSource:
    """scan_source: single-file scanning for either grammar."""

    def test_python_static(self):
        ref = scan_source("x = compute_total()\n", "compute_total", ".py")
        assert ref.static
        assert not ref.dynamic_risk

    def test_python_dynamic(self):
        ref = scan_source('getattr(m, "compute_total")\n', "compute_total", ".py")
        assert ref.dynamic_risk
        assert not ref.static

    def test_js_static(self):
        ref = scan_source("m.computeTotal(x);\n", "computeTotal", ".js")
        assert ref.static
        assert not ref.dynamic_risk

    def test_js_dynamic(self):
        ref = scan_source('m["computeTotal"](x);\n', "computeTotal", ".js")
        assert ref.dynamic_risk
        assert not ref.static

    def test_no_match(self):
        ref = scan_source("x = 1\n", "missing", ".py")
        assert not ref.static and not ref.dynamic_risk

    def test_unsupported_extension_raises(self):
        with pytest.raises(ValueError):
            scan_source("code", "sym", ".rb")


class TestSampleRepoJsIntegration:
    """End-to-end scan of the JavaScript sample repo."""

    def test_full_scan_compute_total(self):
        result = scan_repo(SAMPLE_REPO_JS, "computeTotal")
        assert "pkg/mathutils.js" in result.static_files
        assert "pkg/reporter.js" in result.static_files
        assert "tests/test_reporter.test.js" in result.static_files
        assert "pkg/dynamic_call.js" in result.dynamic_risk_files
        assert result.has_dynamic_risk

    def test_build_report_no_dynamic_risk(self):
        result = scan_repo(SAMPLE_REPO_JS, "buildReport")
        assert not result.has_dynamic_risk
        assert "tests/test_reporter.test.js" in result.static_files
class TestExtractFunction:
    """extract-function analysis and application on the Python sample repo."""

    def _read_mathutils(self):
        with open(MATHUTILS, encoding="utf-8") as f:
            return f.read()

    def test_analyze_derives_params_and_returns(self):
        plan = analyze_block(self._read_mathutils(), 30, 31)
        assert plan is not None
        assert plan.parameters == ["items"]
        assert plan.returned == ["summary", "count"]
        assert plan.enclosing_function_name == "describe_items"

    def test_apply_extraction_shape(self):
        new_src, plan = apply_extraction(
            self._read_mathutils(), 30, 31, "_build_summary_and_count"
        )
        assert plan.new_name == "_build_summary_and_count"
        assert "def _build_summary_and_count(items):" in new_src
        assert "    summary = build_report(items)" in new_src
        assert "    return summary, count" in new_src
        assert "    summary, count = _build_summary_and_count(items)" in new_src
        # the rewritten module must still compile
        compile(new_src, "<extracted>", "exec")

    def test_extract_into_file_tests_still_pass(self, tmp_path):
        repo = _sample_repo_copy(tmp_path)
        rel, plan = extract_into_file(
            str(repo), "pkg/mathutils.py", 30, 31, "_build_summary_and_count"
        )
        assert rel == "pkg/mathutils.py"
        assert plan.parameters == ["items"]
        proc = _pytest_in(repo)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_bad_range_returns_none(self):
        assert analyze_block("x = 1\n", 1, 99) is None

    def test_invalid_function_name_raises(self):
        with pytest.raises(ValueError):
            apply_extraction(self._read_mathutils(), 30, 31, "1bad name")


class TestMoveSymbol:
    """move-symbol operation on the Python sample repo."""

    def test_move_build_report_and_tests_pass(self, tmp_path):
        repo = _sample_repo_copy(tmp_path)
        results = move_symbol(
            str(repo), "build_report", "pkg/mathutils.py", "pkg/reportbuilder.py"
        )
        assert "pkg/reportbuilder.py" in results

        builder = (repo / "pkg" / "reportbuilder.py").read_text()
        assert "def build_report(items):" in builder
        assert "from pkg.mathutils import compute_average, compute_total" in builder
        # no self-import
        assert "from pkg.reportbuilder import build_report" not in builder

        mathutils = (repo / "pkg" / "mathutils.py").read_text()
        assert "def build_report" not in mathutils
        # source re-imports the moved symbol at the end of the module
        assert mathutils.rstrip().endswith(
            "from pkg.reportbuilder import build_report"
        )

        test = (repo / "tests" / "test_reporter.py").read_text()
        assert "mathutils.build_report" not in test
        assert "build_report([1, 2, 3])" in test

        proc = _pytest_in(repo)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_find_top_level_definition(self):
        src = "def keep(): pass\ndef target(): pass\n"
        node = find_top_level_definition(src, "target")
        assert node is not None
        assert find_top_level_definition(src, "missing") is None

    def test_dotted_module(self):
        assert dotted_module("pkg/mathutils.py") == "pkg.mathutils"
        assert dotted_module("top.py") == "top"

    def test_move_missing_symbol_raises(self, tmp_path):
        repo = _sample_repo_copy(tmp_path)
        with pytest.raises(ValueError):
            move_symbol(str(repo), "nope", "pkg/mathutils.py", "pkg/x.py")

    def test_move_missing_source_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            move_symbol(str(tmp_path), "x", "no_such.py", "y.py")


class TestJsMissingSymbols:
    """test_runner parsing of Node.js runtime errors."""

    def test_js_type_error(self):
        out = "TypeError: mathutils.computeTotal is not a function"
        assert find_missing_symbols(out, "computeTotal") == [
            ("mathutils.computeTotal", None)
        ]

    def test_js_reference_error(self):
        out = "ReferenceError: sumItems is not defined"
        assert find_missing_symbols(out, "sumItems") == [("sumItems", None)]

    def test_js_bracket_notation_type_error(self):
        """V8 sometimes renders bracket access verbatim in the error text."""
        out = 'TypeError: mathutils["computeTotal"] is not a function'
        results = find_missing_symbols(out, "computeTotal")
        assert len(results) == 1
        assert results[0][1] is None          # no import source

    def test_js_single_quote_bracket_type_error(self):
        out = "TypeError: mathutils['computeTotal'] is not a function"
        results = find_missing_symbols(out, "computeTotal")
        assert len(results) == 1
        assert results[0][1] is None

    def test_js_read_property_error(self):
        """'Cannot read properties of undefined' when the object itself is gone."""
        out = ("TypeError: Cannot read properties of undefined "
               "(reading 'computeTotal')")
        results = find_missing_symbols(out, "computeTotal")
        assert len(results) == 1
        assert results[0] == ("computeTotal", None)

    def test_js_read_property_error_singular(self):
        """Older V8 used singular 'property' instead of 'properties'."""
        out = ("TypeError: Cannot read property 'computeTotal' of undefined")
        results = find_missing_symbols(out, "computeTotal")
        assert len(results) == 1
        assert results[0] == ("computeTotal", None)

    def test_js_ansi_colored_type_error(self):
        """Node may colorize output — ANSI codes must not break the parser."""
        out = ("\x1b[31mTypeError: mathutils.computeTotal is not a function\x1b[0m")
        results = find_missing_symbols(out, "computeTotal")
        assert len(results) == 1
        assert results[0] == ("mathutils.computeTotal", None)

    def test_js_diagnosis_fallback_via_stack_trace(self):
        """When the error text doesn't name the symbol, but the stack trace
        references a dynamic-risk file, diagnose_failures still blames it."""
        # Node stack traces use forward slashes on Linux/macOS and backslashes
        # on Windows.  Forward slashes are simplest for a synthetic test.
        fake_output = (
            "✖ some test failed\n"
            "  TypeError: somethingElse is not a function\n"
            "    at callIt (C:/repo/pkg/dynamic_call.js:8:35)\n"
        )
        result = diagnose_failures(
            fake_output, "computeTotal", ["pkg/dynamic_call.js"]
        )
        assert "pkg/dynamic_call.js" in result
        assert "not mention the renamed symbol directly" in result
        assert "No error mentioning" not in result

    def test_js_diagnosis_fallback_via_stack_trace_backslash(self):
        """Same as above but with Windows-style backslash paths."""
        # To avoid shell-escaping issues, build the string via repr-free
        # concatenation of a single backslash.
        BS = chr(0x5C)  # single backslash
        fake_output = (
            "✖ some test failed\n"
            "  TypeError: somethingElse is not a function\n"
            f"    at callIt (C:{BS}repo{BS}pkg{BS}dynamic_call.js:8:35)\n"
        )
        result = diagnose_failures(
            fake_output, "computeTotal", ["pkg/dynamic_call.js"]
        )
        assert "pkg/dynamic_call.js" in result
        assert "not mention the renamed symbol directly" in result

    def test_js_diagnosis_fallback_no_match_generic(self):
        """When nothing matches at all, the generic message is returned."""
        result = diagnose_failures(
            "PASSED: all good", "computeTotal", []
        )
        assert "No error mentioning" in result

class TestBlastRadius:
    """Blast radius: transitive call-graph traversal (networkx)."""

    def test_python_chain_abc(self, tmp_path):
        """A.py imports from B.py which imports from C.py.
        blast_radius('get_value') defined in C must include both B and A.
        """
        (tmp_path / "c.py").write_text(
            "def get_value():\n"
            "    return 42\n"
        )
        (tmp_path / "b.py").write_text(
            "from c import get_value\n"
            "def middle():\n"
            "    return get_value() + 1\n"
        )
        (tmp_path / "a.py").write_text(
            "from b import middle\n"
            "def top():\n"
            "    return middle() * 2\n"
        )
        radius = blast_radius(str(tmp_path), "get_value")
        assert "c.py" in radius   # defining file
        assert "b.py" in radius   # direct caller
        assert "a.py" in radius   # transitive caller

    def test_python_chain_excludes_unrelated_file(self, tmp_path):
        """An unrelated file D.py that doesn't participate in the chain
        must not appear in the blast radius.
        """
        (tmp_path / "c.py").write_text(
            "def get_value():\n    return 42\n"
        )
        (tmp_path / "b.py").write_text(
            "from c import get_value\ndef middle():\n    return get_value()\n"
        )
        (tmp_path / "d.py").write_text(
            "import os\ndef unrelated():\n    return os.getcwd()\n"
        )
        radius = blast_radius(str(tmp_path), "get_value")
        assert "d.py" not in radius
        assert "c.py" in radius
        assert "b.py" in radius

    def test_js_chain_require(self, tmp_path):
        """JS require-based chain: a.js -> b.js -> c.js.
        blast_radius('getValue') defined in c.js must include b.js and a.js.
        """
        (tmp_path / "c.js").write_text(
            "function getValue() { return 42; }\n"
            "module.exports = { getValue };\n"
        )
        (tmp_path / "b.js").write_text(
            "const { getValue } = require('./c');\n"
            "function middle() { return getValue() + 1; }\n"
            "module.exports = { middle };\n"
        )
        (tmp_path / "a.js").write_text(
            "const { middle } = require('./b');\n"
            "function top() { return middle() * 2; }\n"
            "module.exports = { top };\n"
        )
        radius = blast_radius(str(tmp_path), "getValue")
        assert "c.js" in radius   # defining file
        assert "b.js" in radius   # direct caller
        assert "a.js" in radius   # transitive caller

    def test_blast_radius_missing_symbol(self, tmp_path):
        """blast_radius for a symbol not defined anywhere returns []."""
        (tmp_path / "a.py").write_text("x = 1\n")
        assert blast_radius(str(tmp_path), "nonexistent") == []
class TestSelfHeal:
    """Bounded LLM retry — API-key skip and retry logic (no real API calls)."""

    def test_skips_diagnosis_without_api_key(self, monkeypatch):
        """No GEMINI_API_KEY -> has_api_key() is False, get_diagnosis()
        returns None, and the Gemini API is never touched."""
        # Import first: module-level load_dotenv() may populate the key from
        # .env.  Deleting *after* import ensures has_api_key() sees the gap.
        import src.self_heal as sh
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        os.environ.pop("GEMINI_API_KEY", None)   # belt-and-suspenders

        def _explode(*args, **kwargs):
            raise AssertionError("Gemini API must not be called")

        monkeypatch.setattr(sh, "request_ai_diagnosis", _explode)
        assert sh.has_api_key() is False
        assert sh.get_diagnosis("compute_total", "tests failed", []) is None

    def test_request_ai_diagnosis_uses_gemini_models(self, monkeypatch):
        """request_ai_diagnosis() configures Gemini and builds a
        gemini-3.6-flash prompt — verified with stubbed classes, so no real
        network call ever happens."""
        import src.self_heal as sh

        captured = {}

        class _FakeResponse:
            text = "Root cause: renamed via getattr\nSuggested fix: patch dynamic.py"

        class _FakeModel:
            def __init__(self, model_name, **kwargs):
                captured["model"] = model_name

            def generate_content(self, prompt):
                captured["prompt"] = prompt
                return _FakeResponse()

        monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
        monkeypatch.setattr(sh.genai, "configure",
                            lambda **kw: captured.update(kw))
        monkeypatch.setattr(sh.genai, "GenerativeModel", _FakeModel)
        out = sh.request_ai_diagnosis("compute_total", "FAILED",
                                      ["pkg/dynamic.py"])
        assert out == "Root cause: renamed via getattr\nSuggested fix: patch dynamic.py"
        assert captured["model"] == "gemini-3.6-flash"
        assert captured["api_key"] == "test-key-123"
        assert "code reliability diagnostic assistant" in captured["prompt"]
        assert "Do not suggest hardcoding a specific value" in captured["prompt"]
        assert "address the underlying general behavior" in captured["prompt"]
        assert "compute_total" in captured["prompt"]
        assert "pkg/dynamic.py" in captured["prompt"]

    def test_hardcoding_warning_triggered_on_narrow_suggestion(self):
        """When AI suggests a narrow or hardcoded fix, format_diagnosis appends a warning."""
        from src.self_heal import format_diagnosis, _check_for_hardcoding

        raw = (
            "Root cause: dynamic getattr failed\n"
            "Suggested fix: just return 42 for this specific test case."
        )
        assert _check_for_hardcoding(raw) is True
        formatted = format_diagnosis(raw)
        assert "⚠ This suggested fix may be overly specific to this one case" in formatted

    def test_no_hardcoding_warning_on_general_suggestion(self):
        """A general fix suggestion does not trigger the hardcoding warning."""
        from src.self_heal import format_diagnosis, _check_for_hardcoding

        raw = (
            "Root cause: dynamic getattr failed\n"
            "Suggested fix: replace getattr with direct attribute access or update string literal"
        )
        assert _check_for_hardcoding(raw) is False
        formatted = format_diagnosis(raw)
        assert "⚠ This suggested fix may be overly specific" not in formatted

    def test_verify_step_rolls_back_without_api_key(self, tmp_path, monkeypatch,
                                                   capsys):
        """No key -> _verify_step prints the skip line and rolls back
        (exit code 1) without attempting a retry."""
        repo = _sample_repo_copy(tmp_path)
        snapshot = create_snapshot(str(repo))
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        import src.main as main
        state = {"calls": 0}

        def _fail(*a, **k):
            state["calls"] += 1
            return (False, "FAILED boom", 1)

        monkeypatch.setattr(main, "run_tests", _fail)
        code = main._verify_step(str(repo), "pytest -q", snapshot,
                                 "compute_total", [])
        assert code == 1
        assert state["calls"] == 1                  # initial run only, no retry
        assert not os.path.exists(snapshot)         # backup cleaned up
        out = capsys.readouterr().out
        assert "Skipping AI diagnosis — no API key configured" in out

    def test_verify_step_keeps_change_on_retry(self, tmp_path, monkeypatch,
                                               capsys):
        """Diagnosis runs, the suite is re-run exactly once more, and a
        passing retry keeps the change."""
        repo = _sample_repo_copy(tmp_path)
        snapshot = create_snapshot(str(repo))
        monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
        import src.main as main
        state = {"calls": 0}

        def _run(*args, **kwargs):
            state["calls"] += 1
            if state["calls"] == 1:
                return (False, "FAILED first", 1)
            return (True, "PASSED retry", 0)

        monkeypatch.setattr(main, "run_tests", _run)
        monkeypatch.setattr(main, "get_diagnosis",
                            lambda *a, **k: "  🔍 Root cause: transient\n"
                                            "  💡 Suggested fix: retry")
        code = main._verify_step(str(repo), "pytest -q", snapshot,
                                 "compute_total", [])
        assert code == 0
        assert state["calls"] == 2                  # initial + exactly one retry
        assert not os.path.exists(snapshot)         # change kept, backup cleaned
        out = capsys.readouterr().out
        assert "AI diagnosis helped resolve a transient issue" in out
        assert "Rolling back" not in out

    def test_verify_step_rolls_back_when_retry_fails(self, tmp_path, monkeypatch,
                                                     capsys):
        """Diagnosis runs, retry fails too -> roll back as before."""
        repo = _sample_repo_copy(tmp_path)
        snapshot = create_snapshot(str(repo))
        monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
        import src.main as main
        monkeypatch.setattr(main, "run_tests",
                            lambda *a, **k: (False, "FAILED again", 1))
        monkeypatch.setattr(main, "get_diagnosis",
                            lambda *a, **k: "  🔍 Root cause: broken\n"
                                            "  💡 Suggested fix: fix it")
        code = main._verify_step(str(repo), "pytest -q", snapshot,
                                 "compute_total", [])
        assert code == 1
        assert not os.path.exists(snapshot)
        out = capsys.readouterr().out
        assert "Rolling back" in out
        assert "DIAGNOSIS" in out

    def test_gemini_model_configurable_via_env_var(self, monkeypatch):
        """GEMINI_MODEL environment variable overrides the default model."""
        import src.self_heal as sh
        monkeypatch.setenv("GEMINI_MODEL", "custom-model-test")
        assert sh.get_model_name() == "custom-model-test"

        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        assert sh.get_model_name() == "gemini-3.6-flash"

    def test_legacy_model_attribute_is_dynamic(self, monkeypatch):
        """_MODEL dynamically tracks get_model_name() via __getattr__ and never drifts."""
        import src.self_heal as sh
        monkeypatch.setenv("GEMINI_MODEL", "custom-dynamic-model")
        assert sh._MODEL == "custom-dynamic-model"
        assert sh._MODEL == sh.get_model_name()

        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        assert sh._MODEL == "gemini-3.6-flash"
        assert sh._MODEL == sh.get_model_name()

        with pytest.raises(AttributeError):
            _ = sh.NON_EXISTENT_ATTR

    def test_skips_diagnosis_for_unavailable_or_deprecated_model(self, monkeypatch, capsys):
        """When Gemini API returns 404/not-found/deprecated for a model,
        get_diagnosis() logs a warning and returns None (skips gracefully),
        without raising."""
        import src.self_heal as sh
        monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")

        def _mock_failure(*args, **kwargs):
            raise Exception("404 models/gemini-2.0-flash is not found or deprecated")

        monkeypatch.setattr(sh, "request_ai_diagnosis", _mock_failure)

        result = sh.get_diagnosis("compute_total", "tests failed", ["pkg/dynamic_caller.py"])
        assert result is None
        out = capsys.readouterr().out
        assert "Skipping AI diagnosis" in out
        assert "gemini-2.0-flash" in out
        assert "unavailable or deprecated" in out

    def test_verify_step_rolls_back_when_model_unavailable(self, tmp_path, monkeypatch):
        """When model is unavailable (get_diagnosis returns None),
        _verify_step skips retry and rolls back immediately."""
        repo = _sample_repo_copy(tmp_path)
        snapshot = create_snapshot(str(repo))
        monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
        import src.main as main
        state = {"calls": 0}

        def _fail(*a, **k):
            state["calls"] += 1
            return (False, "FAILED boom", 1)

        monkeypatch.setattr(main, "run_tests", _fail)
        monkeypatch.setattr(main, "get_diagnosis", lambda *a, **k: None)

        code = main._verify_step(str(repo), "pytest -q", snapshot,
                                 "compute_total", [])
        assert code == 1
        assert state["calls"] == 1  # No retry attempted
        assert not os.path.exists(snapshot)


class TestDryRun:
    def test_rename_dry_run_leaves_files_unchanged(self, tmp_path, capsys):
        repo = _sample_repo_copy(tmp_path)
        mathutils = repo / "pkg" / "mathutils.py"
        original_content = mathutils.read_text(encoding="utf-8")

        import src.main as main
        code = main.do_rename(str(repo), "build_report", "generate_report",
                              "pytest -q", dry_run=True)
        assert code == 0
        assert mathutils.read_text(encoding="utf-8") == original_content
        out = capsys.readouterr().out
        assert "DRY-RUN SUMMARY" in out
        assert "DRY-RUN COMPLETED" in out
        assert "build_report" in out

    def test_extract_dry_run_leaves_files_unchanged(self, tmp_path, capsys):
        repo = _sample_repo_copy(tmp_path)
        mathutils = repo / "pkg" / "mathutils.py"
        original_content = mathutils.read_text(encoding="utf-8")

        import src.main as main
        code = main.do_extract(str(repo), "pkg/mathutils.py", 30, 31,
                               "_helper", "pytest -q", dry_run=True)
        assert code == 0
        assert mathutils.read_text(encoding="utf-8") == original_content
        out = capsys.readouterr().out
        assert "DRY-RUN SUMMARY" in out
        assert "DRY-RUN COMPLETED" in out

    def test_move_dry_run_leaves_files_unchanged(self, tmp_path, capsys):
        repo = _sample_repo_copy(tmp_path)
        target = repo / "pkg" / "reportbuilder.py"
        assert not target.exists()

        import src.main as main
        code = main.do_move(str(repo), "build_report", "pkg/mathutils.py",
                            "pkg/reportbuilder.py", "pytest -q", dry_run=True)
        assert code == 0
        assert not target.exists()
        out = capsys.readouterr().out
        assert "DRY-RUN SUMMARY" in out
        assert "DRY-RUN COMPLETED" in out

    def test_cli_dry_run_flag(self, tmp_path, capsys):
        repo = _sample_repo_copy(tmp_path)
        import src.main as main
        code = main.main([
            "rename", "--repo-root", str(repo),
            "--symbol", "build_report", "--to", "generate_report",
            "--test-cmd", "pytest -q", "--dry-run"
        ])
        assert code == 0
        out = capsys.readouterr().out
        assert "DRY-RUN SUMMARY" in out


class TestSupportedExtensionsValidation:
    """Tests that extract-function and move-symbol reject non-Python files fast with code 2."""

    def test_supported_extensions_constant(self):
        import src.main as main
        assert hasattr(main, "SUPPORTED_EXTENSIONS")
        assert main.SUPPORTED_EXTENSIONS["rename"] == {".py", ".js", ".ts"}
        assert main.SUPPORTED_EXTENSIONS["extract-function"] == {".py"}
        assert main.SUPPORTED_EXTENSIONS["move-symbol"] == {".py"}

    def test_extract_unsupported_js_fails_fast(self, tmp_path, capsys):
        repo = _sample_repo_copy(tmp_path)
        import src.main as main
        code = main.do_extract(
            repo_root=str(repo),
            rel_file="index.js",
            start=1,
            end=5,
            name="helper",
            test_cmd="node --test",
        )
        assert code == 2
        out = capsys.readouterr().out
        assert "ERROR: 'extract-function' does not support '.js' files" in out
        assert "Operation / Language support matrix:" in out
        assert "extract-function: Python (.py) only" in out
        assert "rename:           Python (.py), JavaScript (.js), TypeScript (.ts)" in out

    def test_extract_unsupported_ts_fails_fast(self, tmp_path, capsys):
        repo = _sample_repo_copy(tmp_path)
        import src.main as main
        code = main.do_extract(
            repo_root=str(repo),
            rel_file="app.ts",
            start=1,
            end=5,
            name="helper",
            test_cmd="npm test",
        )
        assert code == 2
        out = capsys.readouterr().out
        assert "ERROR: 'extract-function' does not support '.ts' files" in out

    def test_extract_python_file_works_unchanged(self, tmp_path):
        repo = _sample_repo_copy(tmp_path)
        import src.main as main
        code = main.do_extract(
            repo_root=str(repo),
            rel_file="pkg/mathutils.py",
            start=30,
            end=31,
            name="_build_summary_and_count",
            test_cmd="pytest -q",
            dry_run=True,
        )
        assert code == 0

    def test_move_unsupported_source_js_fails_fast(self, tmp_path, capsys):
        repo = _sample_repo_copy(tmp_path)
        import src.main as main
        code = main.do_move(
            repo_root=str(repo),
            symbol="formatItem",
            source="index.js",
            target="pkg/reportbuilder.py",
            test_cmd="node --test",
        )
        assert code == 2
        out = capsys.readouterr().out
        assert "ERROR: 'move-symbol' does not support '.js' files" in out
        assert "Operation / Language support matrix:" in out
        assert "move-symbol:      Python (.py) only" in out

    def test_move_unsupported_target_js_fails_fast(self, tmp_path, capsys):
        repo = _sample_repo_copy(tmp_path)
        import src.main as main
        code = main.do_move(
            repo_root=str(repo),
            symbol="build_report",
            source="pkg/mathutils.py",
            target="pkg/reportbuilder.js",
            test_cmd="pytest -q",
        )
        assert code == 2
        out = capsys.readouterr().out
        assert "ERROR: 'move-symbol' does not support '.js' files" in out

    def test_move_python_files_work_unchanged(self, tmp_path):
        repo = _sample_repo_copy(tmp_path)
        import src.main as main
        code = main.do_move(
            repo_root=str(repo),
            symbol="build_report",
            source="pkg/mathutils.py",
            target="pkg/reportbuilder.py",
            test_cmd="pytest -q",
            dry_run=True,
        )
        assert code == 0

    def test_cli_extract_unsupported_language_exits_2(self, tmp_path, capsys):
        repo = _sample_repo_copy(tmp_path)
        import src.main as main
        code = main.main([
            "extract-function",
            "--repo-root", str(repo),
            "--file", "index.js",
            "--start-line", "1",
            "--end-line", "5",
            "--name", "helper",
            "--test-cmd", "node --test",
        ])
        assert code == 2
        out = capsys.readouterr().out
        assert "ERROR: 'extract-function' does not support '.js' files" in out

    def test_cli_move_unsupported_language_exits_2(self, tmp_path, capsys):
        repo = _sample_repo_copy(tmp_path)
        import src.main as main
        code = main.main([
            "move-symbol",
            "--repo-root", str(repo),
            "--symbol", "formatItem",
            "--source", "index.js",
            "--target", "out.py",
            "--test-cmd", "node --test",
        ])
        assert code == 2
        out = capsys.readouterr().out
        assert "ERROR: 'move-symbol' does not support '.js' files" in out


class TestPreserveCommentsAndDocstrings:
    """Tests that AST byte-range span rename preserves comments, docstrings, and strings."""

    def test_python_rename_preserves_comments_and_docstrings(self, tmp_path):
        f = tmp_path / "calc.py"
        code = (
            "# calculate_score is an important scoring function\n"
            '"""Module docstring for calculate_score."""\n\n'
            "def calculate_score(points):\n"
            '    """calculate_score docstring inside function."""\n'
            "    # calculate_score comment inside body\n"
            '    notes = "calculate_score mentioned in string"\n'
            "    return points * 2\n\n"
            "def run():\n"
            "    return calculate_score(10)\n"
        )
        f.write_text(code, encoding="utf-8")

        count = rename_symbol_in_file(str(f), "calculate_score", "compute_score")
        assert count == 2

        new_text = f.read_text(encoding="utf-8")
        # Real code identifiers renamed
        assert "def compute_score(points):" in new_text
        assert "return compute_score(10)" in new_text
        # Comments, docstrings, and string literals preserved untouched
        assert "# calculate_score is an important scoring function" in new_text
        assert '"""Module docstring for calculate_score."""' in new_text
        assert '"""calculate_score docstring inside function."""' in new_text
        assert "# calculate_score comment inside body" in new_text
        assert 'notes = "calculate_score mentioned in string"' in new_text

    def test_javascript_rename_preserves_comments_and_strings(self, tmp_path):
        f = tmp_path / "calc.js"
        code = (
            "// calculateScore helper function\n"
            "/* Block comment mentioning calculateScore */\n"
            "/**\n"
            " * JSDoc comment for calculateScore\n"
            " */\n"
            "function calculateScore(points) {\n"
            "  // calculateScore inside body\n"
            '  const label = "calculateScore in string";\n'
            "  return points * 2;\n"
            "}\n\n"
            "const total = calculateScore(10);\n"
            "module.exports = { calculateScore };\n"
        )
        f.write_text(code, encoding="utf-8")

        count = rename_symbol_in_file(str(f), "calculateScore", "computeScore")
        assert count == 3

        new_text = f.read_text(encoding="utf-8")
        # Real code identifiers renamed
        assert "function computeScore(points)" in new_text
        assert "const total = computeScore(10);" in new_text
        assert "module.exports = { computeScore };" in new_text
        # Comments and string literals preserved untouched
        assert "// calculateScore helper function" in new_text
        assert "/* Block comment mentioning calculateScore */" in new_text
        assert "* JSDoc comment for calculateScore" in new_text
        assert "// calculateScore inside body" in new_text
        assert 'const label = "calculateScore in string";' in new_text

    def test_typescript_rename_preserves_comments_and_strings(self, tmp_path):
        f = tmp_path / "calc.ts"
        code = (
            "// formatData is exported here\n"
            "/* formatData block comment */\n"
            "/**\n"
            " * formatData JSDoc description\n"
            " */\n"
            "function formatData(value) {\n"
            "  // internal formatData comment\n"
            '  const desc = "formatData description string";\n'
            "  return value;\n"
            "}\n\n"
            'const res = formatData("hello");\n'
        )
        f.write_text(code, encoding="utf-8")

        count = rename_symbol_in_file(str(f), "formatData", "transformData")
        assert count == 2

        new_text = f.read_text(encoding="utf-8")
        # Real code identifiers renamed
        assert "function transformData(value)" in new_text
        assert 'const res = transformData("hello");' in new_text
        # Comments and string literals preserved untouched
        assert "// formatData is exported here" in new_text
        assert "/* formatData block comment */" in new_text
        assert "* formatData JSDoc description" in new_text
        assert "// internal formatData comment" in new_text
        assert 'const desc = "formatData description string";' in new_text

    def test_non_ascii_unicode_emojis_preserved_without_corruption(self, tmp_path):
        f = tmp_path / "unicode_app.py"
        code = (
            "# Author: François Müller 💡 🚀\n"
            '"""Docstring with café ✨ and price €100."""\n\n'
            "def calculate_total(items):\n"
            "    # François's calculation ❤️\n"
            '    label = "calculate_total in unicode context 🌟"\n'
            "    return len(items)\n\n"
            "output = calculate_total([1, 2, 3])\n"
        )
        f.write_text(code, encoding="utf-8")

        count = rename_symbol_in_file(str(f), "calculate_total", "compute_sum")
        assert count == 2

        new_text = f.read_text(encoding="utf-8")
        # Assert identifiers renamed
        assert "def compute_sum(items):" in new_text
        assert "output = compute_sum([1, 2, 3])" in new_text
        # Assert non-ASCII characters, emojis, and symbols preserved with zero corruption
        assert "# Author: François Müller 💡 🚀" in new_text
        assert '"""Docstring with café ✨ and price €100."""' in new_text
        assert "# François's calculation ❤️" in new_text
        assert 'label = "calculate_total in unicode context 🌟"' in new_text

    def test_tree_sitter_error_node_falls_back_to_regex(self, tmp_path, capsys):
        f = tmp_path / "syntax_error.py"
        # Invalid python syntax that causes Tree-sitter has_error == True
        code = (
            "def broken_syntax(\n"
            "calculate_total([1, 2])\n"
        )
        f.write_text(code, encoding="utf-8")

        count = rename_symbol_in_file(str(f), "calculate_total", "compute_sum")
        assert count == 1
        new_text = f.read_text(encoding="utf-8")
        assert "compute_sum([1, 2])" in new_text
        out = capsys.readouterr().out
        assert "WARNING: Tree-sitter parsing produced an error node" in out

    def test_stale_spans_trigger_fresh_scan_fallback(self, tmp_path):
        f = tmp_path / "valid.py"
        code = "val = calculate_total([1, 2])\n"
        f.write_text(code, encoding="utf-8")

        # Pass stale spans that do NOT match calculate_total
        stale_spans = [(0, 3), (100, 115)]
        count = rename_symbol_in_file(str(f), "calculate_total", "compute_sum", spans=stale_spans)
        assert count == 1
        assert "val = compute_sum([1, 2])\n" == f.read_text(encoding="utf-8")




