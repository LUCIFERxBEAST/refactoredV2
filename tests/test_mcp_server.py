import json
import os
import shutil
import pytest
from src.mcp_server import (
    refactor_guard_rename,
    refactor_guard_extract_function,
    refactor_guard_move_symbol,
    refactor_guard_history,
    refactor_guard_review_patch,
    refactor_guard_check_minimality,
    refactor_guard_check_generalization,
    refactor_guard_compare_runs,
    refactor_rename,
    refactor_extract_function,
    refactor_move_symbol,
    refactor_history,
    refactor_review_patch,
    refactor_check_minimality,
    refactor_check_generalization,
    refactor_compare_runs,
)


def _sample_repo_copy(tmp_path):
    repo_src = os.path.join(os.path.dirname(__file__), "sample_repo")
    dest = tmp_path / "repo"
    shutil.copytree(repo_src, dest)
    return dest


def test_mcp_rename_success(tmp_path):
    repo = _sample_repo_copy(tmp_path)
    output = refactor_guard_rename(
        repo_root=str(repo),
        symbol="build_report",
        to="generate_report",
        test_cmd="pytest -q",
    )
    assert "[SUCCESS]" in output
    assert "generate_report" in output

    mathutils = repo / "pkg" / "mathutils.py"
    assert "def generate_report" in mathutils.read_text(encoding="utf-8")


def test_mcp_rename_dry_run(tmp_path):
    repo = _sample_repo_copy(tmp_path)
    mathutils = repo / "pkg" / "mathutils.py"
    original = mathutils.read_text(encoding="utf-8")

    output = refactor_guard_rename(
        repo_root=str(repo),
        symbol="build_report",
        to="generate_report",
        test_cmd="pytest -q",
        dry_run=True,
    )
    assert "[SUCCESS]" in output
    assert "DRY-RUN SUMMARY" in output
    assert mathutils.read_text(encoding="utf-8") == original


def test_mcp_extract_function(tmp_path):
    repo = _sample_repo_copy(tmp_path)
    output = refactor_guard_extract_function(
        repo_root=str(repo),
        rel_file="pkg/mathutils.py",
        start_line=30,
        end_line=31,
        name="_build_summary_and_count",
        test_cmd="pytest -q",
    )
    assert "[SUCCESS]" in output
    assert "_build_summary_and_count" in output

    mathutils = repo / "pkg" / "mathutils.py"
    assert "def _build_summary_and_count" in mathutils.read_text(encoding="utf-8")


def test_mcp_move_symbol(tmp_path):
    repo = _sample_repo_copy(tmp_path)
    output = refactor_guard_move_symbol(
        repo_root=str(repo),
        symbol="build_report",
        source="pkg/mathutils.py",
        target="pkg/reportbuilder.py",
        test_cmd="pytest -q",
    )
    assert "[SUCCESS]" in output
    target_file = repo / "pkg" / "reportbuilder.py"
    assert target_file.exists()


def test_mcp_rename_failure_rollback(tmp_path, monkeypatch):
    repo = _sample_repo_copy(tmp_path)
    # Remove gemini key to test plain rollback
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    output = refactor_guard_rename(
        repo_root=str(repo),
        symbol="compute_total",
        to="sum_items",
        test_cmd="pytest -q",
    )
    assert "[FAILURE" in output
    assert "Outcome: repository restored from snapshot; rollback performed" in output

    mathutils = repo / "pkg" / "mathutils.py"
    assert "def compute_total" in mathutils.read_text(encoding="utf-8")


def test_mcp_aliases(tmp_path):
    repo = _sample_repo_copy(tmp_path)
    output = refactor_rename(
        repo_root=str(repo),
        symbol="build_report",
        to="generate_report",
        test_cmd="pytest -q",
    )
    assert "[SUCCESS]" in output


def test_mcp_extract_unsupported_language_fails_fast(tmp_path):
    repo = _sample_repo_copy(tmp_path)
    output = refactor_guard_extract_function(
        repo_root=str(repo),
        rel_file="index.js",
        start_line=1,
        end_line=5,
        name="helper",
        test_cmd="node --test",
    )
    assert "[FAILURE (exit code 2)]" in output
    assert "extract-function" in output
    assert "does not support '.js'" in output
    assert "Operation / Language support matrix:" in output


def test_mcp_move_unsupported_language_fails_fast(tmp_path):
    repo = _sample_repo_copy(tmp_path)
    output = refactor_guard_move_symbol(
        repo_root=str(repo),
        symbol="formatItem",
        source="index.js",
        target="pkg/reportbuilder.py",
        test_cmd="node --test",
    )
    assert "[FAILURE (exit code 2)]" in output
    assert "move-symbol" in output
    assert "does not support '.js'" in output
    assert "Operation / Language support matrix:" in output


def test_mcp_history(tmp_path):
    repo = _sample_repo_copy(tmp_path)
    # 1. Initially empty
    out_empty = refactor_guard_history(repo_root=str(repo))
    assert "[SUCCESS]" in out_empty
    assert "No refactor history recorded yet" in out_empty

    # 2. Run a rename
    refactor_guard_rename(
        repo_root=str(repo),
        symbol="build_report",
        to="generate_report",
        test_cmd="pytest -q",
    )

    # 3. History now has records
    out_history = refactor_guard_history(repo_root=str(repo))
    assert "[SUCCESS]" in out_history
    assert "Total records: 1" in out_history
    assert "rename 'build_report' → 'generate_report'" in out_history
    assert "SUCCESS" in out_history

    # 4. Test alias
    out_alias = refactor_history(repo_root=str(repo))
    assert "[SUCCESS]" in out_alias


def test_mcp_review_patch_folder_base(tmp_path):
    base = tmp_path / "base"
    cand = tmp_path / "cand"
    shutil.copytree(os.path.join(os.path.dirname(__file__), "sample_repo"), base)
    shutil.copytree(base, cand)

    out_json = refactor_guard_review_patch(
        repo_root=str(cand),
        base_ref=str(base),
        test_cmd="",
    )
    data = json.loads(out_json)
    assert data["decision"] in ("accept", "warn")
    assert data["score"] >= 80

    out_alias = refactor_review_patch(
        repo_root=str(cand),
        base_ref=str(base),
        test_cmd="",
    )
    data_alias = json.loads(out_alias)
    assert data_alias["decision"] == data["decision"]


def test_mcp_check_minimality(tmp_path):
    base = tmp_path / "base"
    cand = tmp_path / "cand"
    shutil.copytree(os.path.join(os.path.dirname(__file__), "sample_repo"), base)
    shutil.copytree(base, cand)

    (cand / "pkg" / "mathutils.py").write_text("# comment\n" + (base / "pkg" / "mathutils.py").read_text())

    out_json = refactor_guard_check_minimality(
        repo_root=str(cand),
        base_ref=str(base),
    )
    data = json.loads(out_json)
    assert "patch" in data
    assert "findings" in data
    assert data["decision"] in ("accept", "warn", "require_approval")

    out_alias = refactor_check_minimality(
        repo_root=str(cand),
        base_ref=str(base),
    )
    data_alias = json.loads(out_alias)
    assert "patch" in data_alias


def test_mcp_check_generalization(tmp_path):
    base = tmp_path / "base"
    cand = tmp_path / "cand"
    shutil.copytree(os.path.join(os.path.dirname(__file__), "sample_repo"), base)
    shutil.copytree(base, cand)

    out_json = refactor_guard_check_generalization(
        repo_root=str(cand),
        base_ref=str(base),
        test_cmd="",
    )
    data = json.loads(out_json)
    assert "generalization" in data

    out_alias = refactor_check_generalization(
        repo_root=str(cand),
        base_ref=str(base),
        test_cmd="",
    )
    data_alias = json.loads(out_alias)
    assert "generalization" in data_alias


def test_mcp_compare_runs(tmp_path):
    base = tmp_path / "base"
    cand = tmp_path / "cand"
    shutil.copytree(os.path.join(os.path.dirname(__file__), "sample_repo"), base)
    shutil.copytree(base, cand)

    out_json = refactor_guard_compare_runs(
        repo_root=str(cand),
        base_ref=str(base),
        test_cmd="",
    )
    data = json.loads(out_json)
    assert "verification" in data

    out_alias = refactor_compare_runs(
        repo_root=str(cand),
        base_ref=str(base),
        test_cmd="",
    )
    data_alias = json.loads(out_alias)
    assert "verification" in data_alias



