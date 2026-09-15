"""Verification probe: self-heal AI diagnosis with a valid key.
Uses the model the API recommends (gemini-3.6-flash) since the code's
hardcoded gemini-2.0-flash returns 404.
"""
import os, sys, warnings
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=FutureWarning)
    import google.generativeai as genai

from dotenv import load_dotenv
load_dotenv()

if not os.environ.get("GEMINI_API_KEY", "").strip():
    print("No GEMINI_API_KEY available — cannot run live probe.")
    sys.exit(2)

_SYSTEM_PROMPT = (
    "You are a code reliability diagnostic assistant. Given a failed "
    "refactor's test output, the symbol that was renamed, and any "
    "dynamic-risk references flagged before the refactor, explain in 2-3 "
    "sentences: (a) the most likely root cause, and (b) a specific one-line "
    "fix the developer should apply manually before retrying."
)

FAIL_CONTEXT = (
    "Symbol that was renamed: compute_total\n"
    "Dynamic-risk references flagged before the refactor: pkg/dynamic_caller.py\n"
    "--- test output (truncated to the tail) ---\n"
    "tests/test_dynamic.py:6: assert call_compute_total([1, 2, 3]) == 6\n"
    "E AttributeError: module 'pkg.mathutils' has no attribute 'compute_total'\n"
    "pkg/dynamic_caller.py:10: fn = getattr(mathutils, \"compute_total\")\n"
    "2 failed, 4 passed\n"
)

print("=== SELF-HEAL LIVE PROBE (gemini-3.6-flash) ===")
for model_name in ("gemini-3.6-flash", "gemini-2.0-flash"):
    try:
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        model = genai.GenerativeModel(model_name)
        resp = model.generate_content(_SYSTEM_PROMPT + "\n\n" + FAIL_CONTEXT)
        print(f"\nmodel={model_name!r}:")
        print(resp.text)
    except Exception as exc:
        print(f"\nmodel={model_name!r} -> ERROR: {exc}")
print("\n=== END LIVE PROBE ===")