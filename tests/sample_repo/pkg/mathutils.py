"""Math helpers for the demo package.

Contains:
  - compute_total(items)  -> summed total (renamed in the rollback demo)
  - build_report(items)   -> a text report (renamed in the success demo)
  - describe_items(items) -> describes items (extract-function demo target)
"""
from statistics import mean


def compute_total(items):
    """Sum a list of numbers."""
    return sum(items)


def compute_average(items):
    """Return the average of a list of numbers."""
    return mean(items)


def build_report(items):
    """Build a short text report about a list of numbers."""
    total = compute_total(items)
    average = compute_average(items)
    return f"Total: {total} | Average: {average:.2f}"


def describe_items(items):
    """Describe items; the middle block is the extract demo target."""
    summary = build_report(items)
    count = compute_total(items)
    return f"{summary} | counted: {count}"