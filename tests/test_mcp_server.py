import os
import shutil
import pytest
from src.mcp_server import (
    refactor_guard_rename,
    refactor_guard_extract_function,
    refactor_guard_move_symbol,
    refactor_rename,
    refactor_extract_function,
    refactor_move_symbol,
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

