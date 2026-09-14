import pytest
from src.self_heal import _SYSTEM_PROMPT, _check_for_hardcoding, format_diagnosis

def test_system_prompt_contains_hardcoding_guard():
    """Verify that the system prompt explicitly warns against hardcoding."""
    guard_text = "Do not suggest hardcoding a specific value"
    assert guard_text in _SYSTEM_PROMPT
    assert "address the underlying general behavior" in _SYSTEM_PROMPT

def test_hardcoding_warning_check():
    """Verify that the warning check fires for suspicious patterns."""
    # This should trigger the warning
    suspicious_text = "Suggested fix: Just return 42 for this specific test case."
    
    # The check itself
    assert _check_for_hardcoding(suspicious_text) is True
    
    # The formatting logic
    formatted = format_diagnosis(suspicious_text)
    assert "⚠ This suggested fix may be overly specific" in formatted

def test_no_hardcoding_warning_for_general_fix():
    """Verify that general fixes do not trigger the warning."""
    general_text = "Suggested fix: Update the loop range to include the final index."
    assert _check_for_hardcoding(general_text) is False
    formatted = format_diagnosis(general_text)
    assert "⚠ This suggested fix may be overly specific" not in formatted
