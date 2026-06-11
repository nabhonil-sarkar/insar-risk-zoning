"""
Tests for subsidence severity classification (Module 4B).

These tests exist because of a v0.2.0 bug: severity was initialized to 0
("stable") and the threshold bins did not cover the full velocity range, so
pixels subsiding faster than -100 mm/yr — the fastest-sinking pixels in the
study area — were silently classified as stable.
"""

import numpy as np
import pytest

from src.m4b_insar_overlay import classify_subsidence_severity
from config.settings import SUBSIDENCE_THRESHOLDS

STABLE, SLOW, MODERATE, RAPID = 0, 1, 2, 3


def classify(values):
    severity, names = classify_subsidence_severity(
        np.asarray(values, dtype=np.float64)
    )
    return severity, names


def test_extreme_subsidence_is_rapid_not_stable():
    """THE regression test: -150 mm/yr must be rapid, never stable."""
    severity, _ = classify([-150.0, -300.0, -100.0, -101.0])
    assert (severity == RAPID).all(), (
        "Velocities beyond -100 mm/yr must classify as rapid; in v0.2.0 "
        "they silently defaulted to stable."
    )


def test_uplift_is_stable_not_unclassified():
    """Uplift (> +2 mm/yr) is deliberately folded into stable."""
    severity, _ = classify([5.0, 2.0, 50.0])
    assert (severity == STABLE).all()


def test_canonical_bin_assignments():
    severity, names = classify([0.0, -5.0, -15.0, -30.0])
    assert list(severity) == [STABLE, SLOW, MODERATE, RAPID]
    assert names == {0: "stable", 1: "slow", 2: "moderate", 3: "rapid"}


def test_bin_boundaries_are_half_open():
    """
    Bins are [lo, hi): a boundary value belongs to the bin whose LOWER
    bound it is — i.e., the milder class. -10 is slow, not moderate.
    """
    severity, _ = classify([-2.0, -10.0, -25.0])
    assert list(severity) == [STABLE, SLOW, MODERATE]


def test_nan_is_invalid():
    severity, _ = classify([np.nan, -5.0, np.nan])
    assert severity[0] == -1
    assert severity[1] == SLOW
    assert severity[2] == -1


def test_every_finite_velocity_is_classified():
    """Bins must jointly cover the entire real line — no silent gaps."""
    rng = np.random.RandomState(42)
    values = np.concatenate([
        rng.uniform(-500, 500, size=10_000),
        [-1e9, 1e9, -25.0, -10.0, -2.0, 0.0],
    ])
    severity, _ = classify(values)
    assert (severity >= 0).all(), "A finite velocity escaped classification."


def test_thresholds_config_covers_real_line():
    """Guard the config itself: bins must tile (-inf, +inf) with no gaps."""
    bins = sorted(SUBSIDENCE_THRESHOLDS.values())  # sort by lower bound
    assert bins[0][0] == float("-inf")
    assert bins[-1][1] == float("inf")
    for (_, hi), (lo, _) in zip(bins[:-1], bins[1:]):
        assert hi == lo, f"Gap or overlap between bins at {hi} / {lo}"


def test_gappy_thresholds_raise():
    """The classifier must fail loudly, not silently, on a gappy config."""
    gappy = {
        "stable": (-2, 2),
        "rapid": (-100, -25),  # gap: (-25, -2) and (-inf, -100) and (2, inf)
    }
    with pytest.raises(ValueError):
        classify_subsidence_severity(
            np.array([-150.0]), thresholds=gappy
        )
