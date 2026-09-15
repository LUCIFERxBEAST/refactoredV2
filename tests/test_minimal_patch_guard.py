import json
import os
import shutil
import pytest
from src.main import do_review_patch
from src.minimal_patch_guard import review_patch, models, reporter


def test_review_patch_clean(tmp_path):
    base = tmp_path / "base"
    cand = tmp_path / "cand"
    base.mkdir()
    (base / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (base / "test_calc.py").write_text("from calc import add\ndef test_add():\n    assert add(1, 2) == 3\n")

    shutil.copytree(base, cand)

    review = review_patch(repo_root=str(cand), base_ref=str(base), test_cmd="")
    assert review.score >= 80
    assert review.decision in (models.DECISION_ACCEPT, models.DECISION_WARN)
    assert len(review.findings) == 0


def test_review_patch_detects_hardcoding(tmp_path):
    base = tmp_path / "base"
    cand = tmp_path / "cand"
    base.mkdir()
    (base / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (base / "test_calc.py").write_text("from calc import add\ndef test_add():\n    assert add(1, 2) == 3\n")

    shutil.copytree(base, cand)
    # Introduce hardcoded test-specific branch
    (cand / "calc.py").write_text(
        "def add(a, b):\n"
        "    if a == 1 and b == 2:\n"
        "        return 3\n"
        "    return a + b\n"
    )

    review = review_patch(repo_root=str(cand), base_ref=str(base), test_cmd="")
    # Should flag test-specific branching or suspicious constants
    hardcode_findings = [
        f for f in review.findings
        if f.classification in (
            models.CLASS_TEST_SPECIFIC_HARDCODING,
            models.CLASS_SPECIAL_CASE_BRANCH,
            models.CLASS_SUSPICIOUS_CONSTANT,
        )
    ]
    assert len(hardcode_findings) > 0


def test_review_patch_detects_test_weakening(tmp_path):
    base = tmp_path / "base"
    cand = tmp_path / "cand"
    base.mkdir()
    (base / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (base / "test_calc.py").write_text(
        "from calc import add\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n"
        "    assert add(2, 3) == 5\n"
    )

    shutil.copytree(base, cand)
    # Weaken test by deleting an assertion
    (cand / "test_calc.py").write_text(
        "from calc import add\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n"
    )

    review = review_patch(repo_root=str(cand), base_ref=str(base), test_cmd="")
    weakening_findings = [
        f for f in review.findings
        if f.classification == models.CLASS_TEST_WEAKENING
    ]
    assert len(weakening_findings) > 0


def test_review_patch_scope_expansion_strict(tmp_path):
    base = tmp_path / "base"
    cand = tmp_path / "cand"
    base.mkdir()
    (base / "calc.py").write_text("x = 1\n")
    (base / "other.py").write_text("y = 1\n")

    shutil.copytree(base, cand)
    (cand / "calc.py").write_text("x = 2\n")
    (cand / "other.py").write_text("y = 2\n")

    review = review_patch(
        repo_root=str(cand),
        base_ref=str(base),
        test_cmd="",
        strict_minimality=True,
        max_files_changed=1,
    )
    assert review.decision in (models.DECISION_REQUIRE_APPROVAL, models.DECISION_REJECT)


def test_do_review_patch_cli(tmp_path, capsys):
    base = tmp_path / "base"
    cand = tmp_path / "cand"
    base.mkdir()
    (base / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    shutil.copytree(base, cand)

    code = do_review_patch(
        repo_root=str(cand),
        base_ref=str(base),
        test_cmd="",
        output_format="text",
    )
    captured = capsys.readouterr().out
    assert code in (0, 1)
    assert "MINIMAL PATCH GUARD" in captured

    code_json = do_review_patch(
        repo_root=str(cand),
        base_ref=str(base),
        test_cmd="",
        output_format="json",
    )
    captured_json = capsys.readouterr().out
    assert code_json in (0, 1)
    start_idx = captured_json.find("{")
    end_idx = captured_json.rfind("}") + 1
    assert start_idx != -1 and end_idx > start_idx
    parsed = json.loads(captured_json[start_idx:end_idx])
    assert "score" in parsed
    assert "decision" in parsed
