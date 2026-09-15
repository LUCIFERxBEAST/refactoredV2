"""Calls compute_total ONLY via getattr -- a 'dynamic-risk' reference.

Because the name is passed as a string, a plain rename of the function
definition can never update this code automatically.
"""


def call_compute_total(items):
    from . import mathutils
    fn = getattr(mathutils, "compute_total")
    return fn(items)