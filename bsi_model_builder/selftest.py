"""Bundled synthetic test frame (23 pieces, 7.64 T) used by `selftest` and the test suite."""
import os

_HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "selftest")


def sample_paths():
    return os.path.join(_HERE, "sample_job.json"), os.path.join(_HERE, "sample_geometry.csv")
