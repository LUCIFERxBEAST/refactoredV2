"""Re-capture raw logs with clean UTF-8 encoding for the test report.
Run from the project root:  python test_reports/_capture.py
"""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
PY = sys.executable

def capture(argv, outpath, extra_env=None):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("PYTHONUTF8", "1")
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [PY] + argv, cwd=ROOT, text=True, encoding="utf-8",
        errors="replace", env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    with open(outpath, "w", encoding="utf-8") as fh:
        fh.write(proc.stdout)
        fh.write(proc.stderr)
    print(f"captured -> {outpath} (exit {proc.returncode})")

capture(
    ["-m", "pytest", "tests/test_refactor_guard.py", "-v"],
    os.path.join(ROOT, "test_reports", "pytest_output.txt"),
)
capture(["demo_run.py"], os.path.join(ROOT, "test_reports", "demo_output.txt"))
capture(
    ["demo_run.py"],
    os.path.join(ROOT, "test_reports", "demo_output_nokey.txt"),
    {"GEMINI_API_KEY": ""},
)
print("capture complete")