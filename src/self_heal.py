"""
self_heal.py — optional AI diagnosis + bounded retry for failed refactors.

Flow inside VERIFY:
  1. the test suite fails after a change
  2. print the clearly labelled "=== Self-Heal: AI Diagnosis ===" section
  3. if ANTHROPIC_API_KEY is configured, ask the LLM for a root-cause /
     suggested-fix diagnosis and print it, then re-run the test suite
     exactly once more ("bounded retry")
  4. keep the change if the retry passes; roll back otherwise

The step is fully optional and must never block a run:  without an API key
it simply reports that the step was skipped and the caller rolls back right
away (pre-existing behaviour).
"""

import os

from anthropic import Anthropic

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is an optional extra
    def load_dotenv():
        pass

# Load .env from the project root (never overrides an already-set env var).
load_dotenv()

_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = (
    "You are a code reliability diagnostic assistant. Given a failed "
    "refactor's test output, the symbol that was renamed, and any "
    "dynamic-risk references flagged before the refactor, explain in 2-3 "
    "sentences: (a) the most likely root cause, and (b) a specific one-line "
    "fix the developer should apply manually before retrying."
)


def has_api_key() -> bool:
    """True when ANTHROPIC_API_KEY is present and non-empty."""
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


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
    """Call the Anthropic API and return the model's text response.

    Raises on any failure (network error, bad key, ...); the caller wraps
    this and keeps the pipeline non-blocking.
    """
    client = Anthropic()
    message = client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": build_diagnosis_prompt(
                    symbol, test_output, dynamic_risk_files
                ),
            }
        ],
    )
    return "".join(
        block.text
        for block in message.content
        if getattr(block, "type", None) == "text"
    )


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
        else:
            lines.append(f"  {stripped}")
    if not root_found and not fix_found:
        # no markers — dump the whole reply verbatim
        return "\n".join(
            f"  {l}" for l in raw.splitlines() if l.strip()
        )
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