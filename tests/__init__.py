"""Test package marker.

Present so mypy names these modules `tests.test_x`, which is what a per-module
override pattern can match -- a bare `test_*` is rejected as not fully qualified.
"""
