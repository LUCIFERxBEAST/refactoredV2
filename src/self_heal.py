"""
self_heal.py — optional AI diagnosis + bounded retry for failed refactors.

Flow inside VERIFY:
  1. the test suite fails after a change
  2. print the clearly labelled "=== Self-Heal: AI Diagnosis ===" section
  3. if GEMINI_API_KEY is configured, ask Google Gemini for a root-cause /
     suggested-fix diagnosis and print it, then re-run the test suite
     exactly once more ("bounded retry")
  4. keep the change if the retry passes; roll back otherwise

The step is fully optional and must never block a run:  without an API key
it simply reports that the step was skipped and the caller rolls back right
away (pre-existing behaviour).
"""

import os
import warnings

# Google's `google.generativeai` namespace shim emits a FutureWarning on import
# directing users to the newer `google.genai` SDK.  The package still works
# fine, so silence that one known message (it would otherwise print at the top
# of every run).  See: https://github.com/google-gemini/deprecated-generative-ai-python
with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        category=FutureWarning,
        message=r"\s+All support for the `google\.generativeai` package has ended",
    )
    import google.generativeai as genai

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is an optional extra
    def load_dotenv():
        pass

# Load .env from the project root (never overrides an already-set env var).
load_dotenv()

# Free-tier model — usable without a paid plan or billing account
# (see https://ai.google.dev/gemini-api/docs/models).  gemini-2.0-flash was
# retired by Google (404 on the live API); gemini-3.6-flash is the current
# replacement advertised by the API error message.
_MODEL = "gemini-3.6-flash"

_SYSTEM_PROMPT = (
    "You are a code reliability diagnostic assistant. Given a failed "
    "refactor's test output, the symbol that was renamed, and any "
    "dynamic-risk references flagged before the refactor, explain in 2-3 "
    "sentences: (a) the most likely root cause, and (b) a specific one-line "
    "fix the developer should apply manually before retrying.\n\n"
    "IMPORTANT: Do not suggest hardcoding a specific value, special-casing this "
    "one instance, or any fix that would only work for this particular failing "
    "test. Your suggested fix must address the underlying general behavior of the "
    "code — the same class of problem should be fixed for any similar case, not "
    "just this exact one. If you cannot identify a general fix, say so explicitly "
    "instead of proposing a narrow workaround."
)


def has_api_key() -> bool:
    """True when GEMINI_API_KEY is present and non-empty."""
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


def build_diagnosis_prompt(
    symbol: str, test_output: str, dynamic_risk_files
) -> str:
    """Compose the user-side context sent to the model."""
    dynamic_text = ", ".join(dynamic_risk_files) if dynamic_risk_files else "(none)"
    # Keep the payload bounded — only the tail of the test output matters.
    trimmed = test_output[-6000:] if test_output else "(no test output)"
    return (
        f"Symbol that was renamed: {symbol}\n"
        f"Dynamic-risk references flagged before the refactor: {dynamic_text}\n"
        f"--- test output (truncated to the tail) ---\n{trimmed}"
    )


def request_ai_diagnosis(
    symbol: str, test_output: str, dynamic_risk_files
) -> str:
    """Call the Google Gemini API and return the model's text response.

    Uses the free-tier ``gemini-3.6-flash`` model.  Raises on any failure
    (network error, bad key, ...); the caller wraps this and keeps the
    pipeline non-blocking.
    """
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel(_MODEL)
    prompt = _SYSTEM_PROMPT + "\n\n" + build_diagnosis_prompt(
        symbol, test_output, dynamic_risk_files
    )
    response = model.generate_content(prompt)
    return response.text


def _check_for_hardcoding(text: str) -> bool:
    """Return True if the text looks like it suggests a hardcoded/narrow fix."""
    patterns = [
        "just return",
        "hardcode",
        "special case",
        "for this specific",
        "only for this test",
    ]
    low = text.lower()
    return any(p in low for p in patterns)


def format_diagnosis(raw: str) -> str:
    """Post-process the model reply into 🔍/💡 formatted lines.

    Lines the model marks as a root cause or a suggested fix get the emoji
    prefix.  If neither marker shows up, the reply is printed as-is.
    """
    lines = []
    root_found = False
    fix_found = False
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        low = stripped.lower()
        if low.startswith("root cause"):
            root_found = True
            lines.append("  🔍 Root cause: " + stripped.split(":", 1)[-1].strip())
        elif low.startswith("suggested fix"):
            fix_found = True
            lines.append("  💡 Suggested fix: " + stripped.split(":", 1)[-1].strip())
            if _check_for_hardcoding(raw):
                lines.append("  ⚠ This suggested fix may be overly specific to this one case — review it "
                             "carefully before applying, and consider whether the general logic needs "
                             "fixing instead.")
        else:
            lines.append(f"  {stripped}")
    if not root_found and not fix_found:
        # no markers — dump the whole reply verbatim
        res = "\n".join(
            f"  {l}" for l in raw.splitlines() if l.strip()
        )
        if _check_for_hardcoding(raw):
            res += ("\n  ⚠ This suggested fix may be overly specific to this one case — review it "
                    "carefully before applying, and consider whether the general logic needs "
                    "fixing instead.")
        return res
    return "\n".join(lines)



def get_diagnosis(symbol: str, test_output: str, dynamic_risk_files):
    """Return the formatted AI diagnosis text.

    Returns ``None`` when the step should be skipped (no API key configured)
    or ``""`` when an API request failed (the caller still performs the
    bounded retry).  Never raises.
    """
    if not has_api_key():
        return None
    try:
        raw = request_ai_diagnosis(symbol, test_output, dynamic_risk_files)
    except Exception as exc:
        print(f"  ⚠ AI diagnosis request failed: {exc}")
        return ""
    return format_diagnosis(raw)