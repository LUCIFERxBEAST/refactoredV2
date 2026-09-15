# Demo run for Refactor Guard — runs all 5 demo scenarios on fresh copies.
# Usage: python demo_run.py   (run from the project root)

import os
import shutil
import subprocess
import sys

# Console-safe output: Windows code pages can't represent →/⚠/✓/🔍/💡 glyphs.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
if not os.path.isfile(PY):
    PY = sys.executable

SAMPLE = os.path.join(ROOT, "tests", "sample_repo")
SAMPLE_JS = os.path.join(ROOT, "tests", "sample_repo_js")


def fresh_copy(name, src):
    dest = os.path.join(ROOT, name)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return dest


def run_label(label, argv, expect=0):
    print("\n" + "=" * 70)
    print(f"DEMO: {label}")
    print("=" * 70)
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run([PY, "-m", "src.main"] + argv, capture_output=True,
                          text=True, cwd=ROOT, encoding="utf-8", errors="replace",
                          env=env)
    out = proc.stdout + proc.stderr
    print(out)
    ok = proc.returncode == expect
    print(f"→ exit code {proc.returncode} (expected {expect}) {'✓' if ok else '✗'}")
    return ok


def main():
    results = []

    # 1. Python success rename (no dynamic risk)
    demo1 = fresh_copy("_demo1", SAMPLE)
    results.append(("demo1 rename build_report -> generate_report (success)",
                    run_label("rename: build_report → generate_report (should SUCCEED)", [
                        "rename",
                        "--repo-root", demo1,
                        "--symbol", "build_report",
                        "--to", "generate_report",
                        "--test-cmd", "pytest -q",
                    ])))

    # 2. Python rollback rename (dynamic risk)
    demo2 = fresh_copy("_demo2", SAMPLE)
    results.append(("demo2 rename compute_total -> sum_items (rollback)",
                    run_label("rename: compute_total → sum_items (should FAIL + rollback)",
                              ["rename",
                               "--repo-root", demo2,
                               "--symbol", "compute_total",
                               "--to", "sum_items",
                               "--test-cmd", "pytest -q"],
                              expect=1)))

    # 3. extract-function
    demo3 = fresh_copy("_demo3", SAMPLE)
    results.append(("demo3 extract-function",
                    run_label("extract-function: describe_items block → _build_summary_and_count", [
                        "extract-function",
                        "--repo-root", demo3,
                        "--file", "pkg/mathutils.py",
                        "--start-line", "30", "--end-line", "31",
                        "--name", "_build_summary_and_count",
                        "--test-cmd", "pytest -q",
                    ])))

    # 4. move-symbol
    demo4 = fresh_copy("_demo4", SAMPLE)
    results.append(("demo4 move-symbol build_report -> pkg/reportbuilder.py",
                    run_label("move-symbol: build_report → pkg/reportbuilder.py", [
                        "move-symbol",
                        "--repo-root", demo4,
                        "--symbol", "build_report",
                        "--source", "pkg/mathutils.py",
                        "--target", "pkg/reportbuilder.py",
                        "--test-cmd", "pytest -q",
                    ])))

    # 5. JavaScript rename with dynamic risk
    if os.path.isdir(SAMPLE_JS):
        demo5 = fresh_copy("_demo5_js", SAMPLE_JS)
        results.append(("demo5 js rename computeTotal -> sumItems (rollback)",
                        run_label("rename: computeTotal → sumItems in JS (should FAIL + rollback)",
                                  ["rename",
                                   "--repo-root", demo5,
                                   "--symbol", "computeTotal",
                                   "--to", "sumItems",
                                   "--test-cmd", "node --test tests/*.test.js"],
                                  expect=1)))
    else:
        print("Skipping demo5 (tests/sample_repo_js missing)")

    print("\n" + "=" * 70)
    print("DEMO SUMMARY")
    print("=" * 70)
    all_ok = True
    for label, ok in results:
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {status}  {label}")
        all_ok = all_ok and ok
    print()
    print("ALL DEMOS PASS" if all_ok else "SOME DEMOS FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())