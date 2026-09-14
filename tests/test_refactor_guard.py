"""
Unit tests for dependency_graph.py (MAP), refactor_ops.py (ACT),
extract_function.py, move_symbol.py, snapshot.py, and test_runner.py.
"""

import os
import shutil
import subprocess
import sys
import pytest

from src.dependency_graph import scan_repo, scan_source
from src.refactor_ops import rename_symbol_in_file, rename_in_files
from src.snapshot import create_snapshot, restore_snapshot, cleanup_snapshot
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

    def test_js_unrelated_error_ignored(self):
        out = "TypeError: otherThing.foo is not a function"
        assert find_missing_symbols(out, "computeTotal") == []