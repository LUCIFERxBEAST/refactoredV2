import pytest
from pkg.dynamic_caller import call_compute_total


def test_call_compute_total():
    assert call_compute_total([1, 2, 3]) == 6


def test_call_compute_total_empty():
    assert call_compute_total([]) == 0