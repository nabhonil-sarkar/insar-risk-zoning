"""
Tests for Module 3 — Feature Fusion.
"""

import numpy as np
import pytest
from src.m3_feature_fusion import normalize_features


def test_zscore_normalization():
    """Z-score normalized features should have ~zero mean and ~unit std."""
    rng = np.random.RandomState(42)
    features = rng.randn(1000, 5) * 10 + 50  # arbitrary scale
    names = ["emb_00", "emb_01", "emb_02", "emb_03", "insar_velocity_mm_yr"]

    normed = normalize_features(features, names, method="zscore", insar_weight=1.0)

    for i in range(5):
        assert abs(normed[:, i].mean()) < 0.01, f"Mean of col {i} not ~0"
        assert abs(normed[:, i].std() - 1.0) < 0.01, f"Std of col {i} not ~1"


def test_insar_weighting():
    """InSAR features should be scaled by the weight factor."""
    rng = np.random.RandomState(42)
    features = rng.randn(1000, 3)
    names = ["emb_00", "emb_01", "insar_velocity_mm_yr"]

    weight = 2.0
    normed = normalize_features(features, names, method="zscore", insar_weight=weight)

    # The InSAR column (index 2) should have std ≈ weight
    assert abs(normed[:, 2].std() - weight) < 0.1


def test_nan_handling():
    """NaN values should not cause crashes."""
    features = np.array([[1.0, 2.0], [np.nan, 3.0], [4.0, 5.0]])
    names = ["emb_00", "emb_01"]

    normed = normalize_features(features, names, method="zscore", insar_weight=1.0)
    assert np.isnan(normed[1, 0])  # NaN should remain NaN
    assert not np.isnan(normed[0, 0])
