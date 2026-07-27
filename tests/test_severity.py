"""
Tests for subsidence severity classification (Module 4B).

These tests exist because of a v0.2.0 bug: severity was initialized to 0
("stable") and the threshold bins did not cover the full velocity range, so
pixels subsiding faster than -100 mm/yr — the fastest-sinking pixels in the
study area — were silently classified as stable.
"""

import numpy as np
import pandas as pd
import pytest

from src.m4b_insar_overlay import (
    build_risk_matrix,
    classify_subsidence_severity,
)
from src.m5_risk_interpretation import generate_report
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


def test_low_coverage_cluster_is_insufficient_evidence():
    labels = np.repeat([0, 1], 50)
    severity = np.full(100, -1, dtype=np.int8)
    severity[:5] = RAPID       # 10% coverage in cluster 0
    severity[50:] = STABLE     # 100% coverage in cluster 1
    velocity = np.full(100, np.nan)
    velocity[:5] = -30.0
    velocity[50:] = 0.0        # valid stable velocities must be retained

    _, summary = build_risk_matrix(
        labels,
        severity,
        velocity,
        {0: "stable", 1: "slow", 2: "moderate", 3: "rapid"},
        n_clusters=2,
    )
    c0 = summary.loc[summary["cluster"] == 0].iloc[0]
    c1 = summary.loc[summary["cluster"] == 1].iloc[0]
    assert c0["cluster_risk"] == "insufficient_evidence"
    assert c0["pct_velocity_coverage"] == 10.0
    assert c1["cluster_risk"] == "low"
    assert c1["vel_mean"] == 0.0


def test_report_does_not_call_insufficient_evidence_a_risk(tmp_path):
    cluster_stats = pd.DataFrame([{
        "cluster": 0, "pixel_count": 5, "vel_mean": -30.0,
        "vel_median": -30.0, "vel_min": -30.0, "vel_max": -30.0,
        "vel_p10": -30.0, "vel_p90": -30.0,
        "n_below_neg10": 5, "pct_below_neg10": 100.0,
        "n_below_neg25": 5, "pct_below_neg25": 100.0,
    }])
    risk_summary = pd.DataFrame([{
        "cluster": 0, "cluster_risk": "insufficient_evidence",
        "pct_moderate_or_worse": 100.0, "pct_rapid": 100.0,
        "pct_velocity_coverage": 10.0,
        "classified_pixels": 5, "total_pixels": 50,
    }])
    report_path = generate_report(
        cluster_stats,
        risk_matrix=pd.DataFrame(),
        risk_summary=risk_summary,
        metrics={"n_clusters": 1},
        severity_names={0: "stable", 1: "slow", 2: "moderate", 3: "rapid"},
        output_dir=str(tmp_path),
    )
    text = open(report_path, encoding="utf-8").read()
    assert "INSUFFICIENT EVIDENCE — NO CLUSTER RISK ASSIGNED" in text
    assert "INSUFFICIENT_EVIDENCE RISK" not in text
