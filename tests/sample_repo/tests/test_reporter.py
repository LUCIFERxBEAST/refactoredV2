import pytest
from pkg import mathutils
from pkg.reporter import report_total


def test_report_total():
    assert report_total([1, 2, 3]) == "The sum of your items is 6"


def test_build_report():
    report = mathutils.build_report([1, 2, 3])
    assert report == "Total: 6 | Average: 2.00"


def test_compute_total():
    assert mathutils.compute_total([1, 2, 3, 4]) == 10


def test_describe_items():
    assert mathutils.describe_items([1, 2, 3]) == "Total: 6 | Average: 2.00 | counted: 6"