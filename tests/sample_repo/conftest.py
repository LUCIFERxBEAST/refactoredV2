"""Ensure the demo repo root is on sys.path so tests can import the pkg."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))