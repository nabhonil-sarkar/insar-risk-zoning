import numpy as np
import pytest
from scripts.alphaearth_overview_check import compare, CachedTIFF


def test_strict_all_axis_and_mask_gate():
    a = np.ones(64)
    b = a.copy()
    assert compare(a, b)["passed"]
    b[-1] += 1e-6
    assert not compare(a, b)["passed"]
    assert not compare(a, np.zeros(64))["passed"]
    assert compare(np.zeros(64), np.full(64, np.nan))["passed"]
    b[-1] = np.nan
    assert not compare(b, b)["passed"]


def test_cache_never_fills_absent_bytes():
    cache = CachedTIFF({0: b"abc", 98: b"xy"}, 100)
    assert cache.read(3) == b"abc"
    with pytest.raises(IOError):
        cache.read(3)
    cache.seek(-2, 2)
    assert cache.read(5) == b"xy"
