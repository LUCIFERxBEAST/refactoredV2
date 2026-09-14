"""
tests/test_ledger.py — Unit tests for src/ledger.py (persistent refactor history store).
"""

import json
import os
import stat
from unittest.mock import patch

import pytest

from src.ledger import (
    LEDGER_DIRNAME,
    LEDGER_FILENAME,
    append_record,
    build_record,
    find_prior_failures,
    get_ledger_path,
    read_records,
)


class TestLedger:

    def test_append_read_roundtrip(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()

        rec1 = build_record(
            operation="rename",
            symbol="compute_total",
            params={"to": "sum_items"},
            outcome="success",
            static_files=["pkg/mathutils.py", "pkg/reporter.py"],
            dynamic_risk_files=[],
            failure_symbols=[],
            test_cmd="pytest -q",
        )

        append_record(str(repo), rec1)

        ledger_file = repo / LEDGER_DIRNAME / LEDGER_FILENAME
        assert ledger_file.exists()

        records = read_records(str(repo))
        assert len(records) == 1
        assert records[0]["operation"] == "rename"
        assert records[0]["symbol"] == "compute_total"
        assert records[0]["params"] == {"to": "sum_items"}
        assert records[0]["outcome"] == "success"
        assert records[0]["static_files"] == ["pkg/mathutils.py", "pkg/reporter.py"]
        assert records[0]["dynamic_risk_files"] == []
        assert records[0]["failure_symbols"] == []
        assert records[0]["test_cmd"] == "pytest -q"
        assert "timestamp" in records[0]

        # Append a second record
        rec2 = {
            "operation": "extract-function",
            "symbol": "_compute_helper",
            "params": {"file": "pkg/mathutils.py", "start_line": 10, "end_line": 15},
            "outcome": "rolled_back",
            "static_files": ["pkg/mathutils.py"],
            "dynamic_risk_files": ["pkg/dynamic_caller.py"],
            "failure_symbols": ["compute_total"],
            "test_cmd": "pytest -q",
        }
        append_record(str(repo), rec2)

        records = read_records(str(repo))
        assert len(records) == 2
        assert records[1]["operation"] == "extract-function"
        assert records[1]["symbol"] == "_compute_helper"
        assert records[1]["outcome"] == "rolled_back"
        assert "timestamp" in records[1]

    def test_find_prior_failures_matching_and_non_matching(self, tmp_path):
        repo = tmp_path / "repo_failures"
        repo.mkdir()

        # 1. Matching failure
        append_record(
            str(repo),
            build_record(
                operation="rename",
                symbol="compute_total",
                params={"to": "sum_items"},
                outcome="rolled_back",
                static_files=["pkg/mathutils.py"],
                dynamic_risk_files=["pkg/dynamic_caller.py"],
                failure_symbols=["compute_total"],
                test_cmd="pytest -q",
            ),
        )

        # 2. Same symbol, but outcome is success
        append_record(
            str(repo),
            build_record(
                operation="rename",
                symbol="compute_total",
                params={"to": "calc_total"},
                outcome="success",
                static_files=["pkg/mathutils.py"],
                dynamic_risk_files=[],
                test_cmd="pytest -q",
            ),
        )

        # 3. Different symbol, rolled back
        append_record(
            str(repo),
            build_record(
                operation="rename",
                symbol="build_report",
                params={"to": "generate_report"},
                outcome="rolled_back",
                static_files=["pkg/reporter.py"],
                dynamic_risk_files=["pkg/dynamic_caller.py"],
                failure_symbols=["build_report"],
                test_cmd="pytest -q",
            ),
        )

        # 4. Different operation, same symbol, rolled back
        append_record(
            str(repo),
            build_record(
                operation="extract-function",
                symbol="compute_total",
                params={"file": "pkg/mathutils.py", "start_line": 5, "end_line": 8},
                outcome="rolled_back",
                static_files=["pkg/mathutils.py"],
                dynamic_risk_files=[],
                test_cmd="pytest -q",
            ),
        )

        # 5. Another matching failure
        append_record(
            str(repo),
            build_record(
                operation="rename",
                symbol="compute_total",
                params={"to": "items_total"},
                outcome="rolled_back",
                static_files=["pkg/mathutils.py"],
                dynamic_risk_files=["pkg/dynamic_caller.py"],
                failure_symbols=["compute_total"],
                test_cmd="pytest -q",
            ),
        )

        # Query matching rename compute_total failures
        matches = find_prior_failures(str(repo), "rename", "compute_total")
        assert len(matches) == 2
        assert matches[0]["params"]["to"] == "sum_items"
        assert matches[1]["params"]["to"] == "items_total"

        # Query matching rename build_report failures
        report_matches = find_prior_failures(str(repo), "rename", "build_report")
        assert len(report_matches) == 1
        assert report_matches[0]["symbol"] == "build_report"

        # Query non-matching symbol
        assert find_prior_failures(str(repo), "rename", "non_existent_sym") == []

        # Query non-matching operation
        assert find_prior_failures(str(repo), "move-symbol", "compute_total") == []

    def test_corrupt_line_tolerance(self, tmp_path):
        repo = tmp_path / "repo_corrupt"
        ledger_dir = repo / LEDGER_DIRNAME
        ledger_dir.mkdir(parents=True)
        ledger_file = ledger_dir / LEDGER_FILENAME

        good_rec1 = {"operation": "rename", "symbol": "a", "outcome": "success"}
        good_rec2 = {"operation": "move-symbol", "symbol": "b", "outcome": "rolled_back"}

        content = (
            json.dumps(good_rec1) + "\n"
            + "   \n"  # blank line
            + "NOT VALID JSON {{{{::: 123\n"  # corrupt line
            + json.dumps(["not", "an", "object"]) + "\n"  # non-dict JSON
            + "{\"truncated_json\": \n"  # incomplete JSON
            + json.dumps(good_rec2) + "\n"
        )
        ledger_file.write_text(content, encoding="utf-8")

        records = read_records(str(repo))
        assert len(records) == 2
        assert records[0]["symbol"] == "a"
        assert records[1]["symbol"] == "b"

    def test_missing_file_tolerance(self, tmp_path):
        repo = tmp_path / "empty_repo"
        repo.mkdir()

        # No .refactor-guard directory exists
        assert read_records(str(repo)) == []
        assert find_prior_failures(str(repo), "rename", "any_sym") == []

        # Non-existent path
        non_existent = str(tmp_path / "does_not_exist")
        assert read_records(non_existent) == []
        assert find_prior_failures(non_existent, "rename", "any_sym") == []

    def test_write_failure_unwritable_directory_does_not_raise(self, tmp_path):
        repo = tmp_path / "unwritable_repo"
        repo.mkdir()

        # Place a regular file where the .refactor-guard directory would be created
        blocker = repo / LEDGER_DIRNAME
        blocker.write_text("blocking file")

        rec = {"operation": "rename", "symbol": "x", "outcome": "success"}

        # Must not raise an exception
        append_record(str(repo), rec)

        # Also test when open() raises PermissionError via mock
        repo_mock = tmp_path / "mock_repo"
        repo_mock.mkdir()
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            append_record(str(repo_mock), rec)

    def test_read_failure_does_not_raise(self, tmp_path):
        repo = tmp_path / "read_fail_repo"
        repo.mkdir()

        with patch("builtins.open", side_effect=PermissionError("Cannot read file")):
            records = read_records(str(repo))
            assert records == []

    def test_empty_or_none_inputs_fail_soft(self):
        # Empty string and None must not raise
        append_record("", {})
        append_record(None, {})
        assert read_records("") == []
        assert read_records(None) == []
        assert find_prior_failures("", "rename", "foo") == []
        assert find_prior_failures(None, "rename", "foo") == []


SAMPLE_REPO = os.path.join(os.path.dirname(__file__), "sample_repo")


class TestLedgerPipelineIntegration:

    def _copy_sample(self, tmp_path, name="repo"):
        import shutil
        dest = tmp_path / name
        shutil.copytree(SAMPLE_REPO, dest)
        return str(dest)

    def test_successful_rename_writes_success_record(self, tmp_path):
        from src.main import do_rename
        repo = self._copy_sample(tmp_path, "repo_success")

        code = do_rename(repo, "build_report", "generate_report", "pytest -q")
        assert code == 0

        records = read_records(repo)
        assert len(records) == 1
        rec = records[0]
        assert rec["operation"] == "rename"
        assert rec["symbol"] == "build_report"
        assert rec["params"]["to"] == "generate_report"
        assert rec["outcome"] == "success"
        assert "pkg/mathutils.py" in rec["static_files"]
        assert "tests/test_reporter.py" in rec["static_files"]
        assert rec["dynamic_risk_files"] == []
        assert rec["failure_symbols"] == []
        assert rec["test_cmd"] == "pytest -q"
        assert "timestamp" in rec

    def test_rolled_back_rename_writes_rolled_back_record_with_risk_and_failure_symbols(self, tmp_path):
        from src.main import do_rename
        repo = self._copy_sample(tmp_path, "repo_rollback")

        code = do_rename(repo, "compute_total", "sum_items", "pytest -q")
        assert code == 1

        records = read_records(repo)
        assert len(records) == 1
        rec = records[0]
        assert rec["operation"] == "rename"
        assert rec["symbol"] == "compute_total"
        assert rec["params"]["to"] == "sum_items"
        assert rec["outcome"] == "rolled_back"
        assert "pkg/dynamic_caller.py" in rec["dynamic_risk_files"]
        assert "compute_total" in rec["failure_symbols"]
        assert rec["test_cmd"] == "pytest -q"

    def test_dry_run_writes_no_record(self, tmp_path):
        from src.main import do_rename, do_extract, do_move
        repo = self._copy_sample(tmp_path, "repo_dry_run")

        # 1. rename dry run
        code = do_rename(repo, "build_report", "generate_report", "pytest -q", dry_run=True)
        assert code == 0
        assert read_records(repo) == []

        # 2. extract dry run
        code_ext = do_extract(repo, "pkg/mathutils.py", 30, 31, "_helper", "pytest -q", dry_run=True)
        assert code_ext == 0
        assert read_records(repo) == []

        # 3. move dry run
        code_move = do_move(repo, "build_report", "pkg/mathutils.py", "pkg/reportbuilder.py", "pytest -q", dry_run=True)
        assert code_move == 0
        assert read_records(repo) == []

    def test_simulated_ledger_write_failure_preserves_exit_code(self, tmp_path):
        from src.main import do_rename
        repo_ok = self._copy_sample(tmp_path, "repo_sim_ok")

        # Simulate exception inside append_record during success
        with patch("src.main.append_record", side_effect=RuntimeError("ledger disk failure")):
            code = do_rename(repo_ok, "build_report", "generate_report", "pytest -q")
            assert code == 0  # Exit code 0 is preserved

        # Simulate exception inside append_record during rollback
        repo_fail = self._copy_sample(tmp_path, "repo_sim_fail")
        with patch("src.main.append_record", side_effect=RuntimeError("ledger disk failure")):
            code_fail = do_rename(repo_fail, "compute_total", "sum_items", "pytest -q")
            assert code_fail == 1  # Exit code 1 is preserved

    def test_warn_shows_prior_history_for_matching_failure(self, tmp_path, capsys):
        from src.main import do_rename
        repo = self._copy_sample(tmp_path, "repo_match_fail")

        append_record(
            repo,
            build_record(
                operation="rename",
                symbol="compute_total",
                params={"to": "sum_items"},
                outcome="rolled_back",
                static_files=["pkg/mathutils.py"],
                dynamic_risk_files=["pkg/dynamic_caller.py"],
                failure_symbols=["compute_total"],
                test_cmd="pytest -q",
                timestamp="2026-09-14T10:00:00+00:00",
            ),
        )

        code = do_rename(repo, "compute_total", "sum_items", "pytest -q")
        assert code == 1

        out = capsys.readouterr().out
        assert "PRIOR HISTORY" in out
        assert "⚠ This exact refactor was attempted 1 time(s) before and rolled back." in out
        assert "Last attempt: 2026-09-14 — failed due to dynamic reference in pkg/dynamic_caller.py" in out
        assert "Fix that file first, or this attempt will likely fail the same way." in out
        assert "REPEAT OFFENDER" in out

    def test_warn_suppressed_for_different_symbol_or_operation(self, tmp_path, capsys):
        from src.main import do_rename
        repo = self._copy_sample(tmp_path, "repo_diff_sym_op")

        # 1. Failure for a different symbol
        append_record(
            repo,
            build_record(
                operation="rename",
                symbol="other_symbol",
                params={"to": "new_symbol"},
                outcome="rolled_back",
                static_files=["pkg/mathutils.py"],
                dynamic_risk_files=["pkg/dynamic_caller.py"],
                test_cmd="pytest -q",
            ),
        )

        do_rename(repo, "build_report", "generate_report", "pytest -q")
        out1 = capsys.readouterr().out
        assert "PRIOR HISTORY" not in out1
        assert "This exact refactor was attempted" not in out1
        assert "REPEAT OFFENDER" not in out1

        # 2. Failure for the same symbol, but different operation (extract-function vs rename)
        append_record(
            repo,
            build_record(
                operation="extract-function",
                symbol="build_report",
                params={"file": "pkg/mathutils.py", "start_line": 20, "end_line": 25},
                outcome="rolled_back",
                static_files=["pkg/mathutils.py"],
                dynamic_risk_files=[],
                test_cmd="pytest -q",
            ),
        )

        do_rename(repo, "build_report", "generate_report", "pytest -q")
        out2 = capsys.readouterr().out
        assert "PRIOR HISTORY" not in out2
        assert "This exact refactor was attempted" not in out2

    def test_repeat_offender_file_highlighted(self, tmp_path, capsys):
        from src.main import do_rename
        repo = self._copy_sample(tmp_path, "repo_repeat_offender")

        # Seed 2 prior failures implicating pkg/dynamic_caller.py
        for i in range(1, 3):
            append_record(
                repo,
                build_record(
                    operation="rename",
                    symbol="compute_total",
                    params={"to": f"attempt_{i}"},
                    outcome="rolled_back",
                    static_files=["pkg/mathutils.py"],
                    dynamic_risk_files=["pkg/dynamic_caller.py"],
                    failure_symbols=["compute_total"],
                    test_cmd="pytest -q",
                    timestamp=f"2026-09-1{i}T12:00:00+00:00",
                ),
            )

        code = do_rename(repo, "compute_total", "sum_items", "pytest -q")
        assert code == 1

        out = capsys.readouterr().out
        assert "This exact refactor was attempted 2 time(s) before and rolled back." in out
        assert "pkg/dynamic_caller.py (REPEAT OFFENDER — implicated in prior rollback)" in out
        assert "Repeat offender file(s) implicated in prior rollback: pkg/dynamic_caller.py" in out

    def test_prior_history_is_advisory_and_preserves_exit_code(self, tmp_path):
        from src.main import do_rename
        repo_clean = self._copy_sample(tmp_path, "repo_clean")
        repo_hist = self._copy_sample(tmp_path, "repo_hist")

        # Seed failure history in repo_hist
        append_record(
            repo_hist,
            build_record(
                operation="rename",
                symbol="compute_total",
                params={"to": "sum_items"},
                outcome="rolled_back",
                static_files=["pkg/mathutils.py"],
                dynamic_risk_files=["pkg/dynamic_caller.py"],
                failure_symbols=["compute_total"],
                test_cmd="pytest -q",
            ),
        )

        # Both roll back with exit code 1
        code_clean = do_rename(repo_clean, "compute_total", "sum_items", "pytest -q")
        code_hist = do_rename(repo_hist, "compute_total", "sum_items", "pytest -q")
        assert code_clean == code_hist == 1

        # Both succeed with exit code 0 for build_report, even with history present
        repo_ok_clean = self._copy_sample(tmp_path, "repo_ok_clean")
        repo_ok_hist = self._copy_sample(tmp_path, "repo_ok_hist")
        append_record(
            repo_ok_hist,
            build_record(
                operation="rename",
                symbol="build_report",
                params={"to": "prior_failed_attempt"},
                outcome="rolled_back",
                static_files=["pkg/mathutils.py"],
                dynamic_risk_files=[],
                test_cmd="pytest -q",
            ),
        )

        code_ok_clean = do_rename(repo_ok_clean, "build_report", "generate_report", "pytest -q")
        code_ok_hist = do_rename(repo_ok_hist, "build_report", "generate_report", "pytest -q")
        assert code_ok_clean == code_ok_hist == 0

    def test_prior_success_surfaced_one_line(self, tmp_path, capsys):
        from src.main import do_rename
        repo = self._copy_sample(tmp_path, "repo_succ")

        append_record(
            repo,
            build_record(
                operation="rename",
                symbol="build_report",
                params={"to": "prior_name"},
                outcome="success",
                static_files=["pkg/mathutils.py"],
                dynamic_risk_files=[],
                test_cmd="pytest -q",
                timestamp="2026-09-10T08:30:00+00:00",
            ),
        )

        code = do_rename(repo, "build_report", "generate_report", "pytest -q")
        assert code == 0

        out = capsys.readouterr().out
        assert "this symbol was previously renamed successfully on 2026-09-10" in out
        assert out.count("previously renamed successfully on 2026-09-10") == 1

    def test_extract_and_move_surface_prior_history(self, tmp_path, capsys):
        from src.main import do_extract, do_move
        repo = self._copy_sample(tmp_path, "repo_extract_move")

        # 1. extract-function with prior failure
        append_record(
            repo,
            build_record(
                operation="extract-function",
                symbol="_build_summary_and_count",
                params={"file": "pkg/mathutils.py", "start_line": 30, "end_line": 31},
                outcome="rolled_back",
                static_files=["pkg/mathutils.py"],
                dynamic_risk_files=[],
                test_cmd="pytest -q",
                timestamp="2026-09-12T14:00:00+00:00",
            ),
        )

        code_ext = do_extract(
            repo,
            "pkg/mathutils.py",
            30,
            31,
            "_build_summary_and_count",
            "pytest -q",
        )
        assert code_ext == 0
        out_ext = capsys.readouterr().out
        assert "PRIOR HISTORY" in out_ext
        assert "This exact refactor was attempted 1 time(s) before and rolled back." in out_ext

        # 2. move-symbol with prior failure
        append_record(
            repo,
            build_record(
                operation="move-symbol",
                symbol="build_report",
                params={"source": "pkg/mathutils.py", "target": "pkg/reportbuilder.py"},
                outcome="rolled_back",
                static_files=["pkg/mathutils.py", "pkg/reportbuilder.py"],
                dynamic_risk_files=[],
                test_cmd="pytest -q",
                timestamp="2026-09-13T09:00:00+00:00",
            ),
        )

        code_move = do_move(
            repo,
            "build_report",
            "pkg/mathutils.py",
            "pkg/reportbuilder.py",
            "pytest -q",
        )
        assert code_move == 0
        out_move = capsys.readouterr().out
        assert "PRIOR HISTORY" in out_move
        assert "This exact refactor was attempted 1 time(s) before and rolled back." in out_move

    def test_history_cli_subcommand(self, tmp_path, capsys):
        from src.main import main
        repo = self._copy_sample(tmp_path, "repo_hist_cli")

        # 1. History empty initially
        code = main(["history", "--repo-root", repo])
        assert code == 0
        out_empty = capsys.readouterr().out
        assert "No refactor history recorded yet" in out_empty

        # 2. Add records
        append_record(
            repo,
            build_record(
                operation="rename",
                symbol="compute_total",
                params={"to": "sum_items"},
                outcome="rolled_back",
                static_files=["pkg/mathutils.py"],
                dynamic_risk_files=["pkg/dynamic_caller.py"],
                failure_symbols=["compute_total"],
                test_cmd="pytest -q",
                timestamp="2026-09-14T10:00:00+00:00",
            ),
        )
        append_record(
            repo,
            build_record(
                operation="rename",
                symbol="build_report",
                params={"to": "generate_report"},
                outcome="success",
                static_files=["pkg/mathutils.py"],
                dynamic_risk_files=[],
                test_cmd="pytest -q",
                timestamp="2026-09-15T12:00:00+00:00",
            ),
        )

        # 3. Read history
        code = main(["history", "--repo-root", repo])
        assert code == 0
        out = capsys.readouterr().out
        assert "Total records: 2" in out
        assert "rename 'compute_total' → 'sum_items'" in out
        assert "ROLLED_BACK" in out
        assert "rename 'build_report' → 'generate_report'" in out
        assert "SUCCESS" in out

        # 4. Filter by symbol
        code_sym = main(["history", "--repo-root", repo, "--symbol", "compute_total"])
        assert code_sym == 0
        out_sym = capsys.readouterr().out
        assert "Total records: 1" in out_sym
        assert "compute_total" in out_sym
        assert "build_report" not in out_sym

        # 5. JSON output
        code_json = main(["history", "--repo-root", repo, "--json"])
        assert code_json == 0
        out_json = capsys.readouterr().out
        data = json.loads(out_json)
        assert len(data) == 2
        assert data[0]["symbol"] == "compute_total"



