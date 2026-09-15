"""Imports and calls compute_total normally -- a 'static' reference."""
from .mathutils import compute_total


def report_total(items):
    """Return a friendly one-line report of the total."""
    result = compute_total(items)
    return f"The sum of your items is {result}"