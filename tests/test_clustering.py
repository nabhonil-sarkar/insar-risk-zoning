"""
Tests for Module 4 — Clustering.
"""

import numpy as np
import pytest
from src.m4_clustering import run_kmeans, run_gmm
from src.utils.geo_utils import features_to_raster


def make_blobs(n_per_cluster=200, n_features=10, n_clusters=4, seed=42):
    """Generate simple clustered test data."""
    rng = np.random.RandomState(seed)
    centers = rng.randn(n_clusters, n_features) * 5
    data = []
    for c in centers:
        data.append(c + rng.randn(n_per_cluster, n_features) * 0.5)
    return np.vstack(data)


def test_kmeans_returns_correct_labels():
    features = make_blobs(n_clusters=4)
    labels, model = run_kmeans(features, n_clusters=4)
    assert len(labels) == len(features)
    assert len(np.unique(labels)) == 4


def test_gmm_returns_probabilities():
    features = make_blobs(n_clusters=3)
    labels, probs, model = run_gmm(features, n_components=3)
    assert probs.shape == (len(features), 3)
    assert np.allclose(probs.sum(axis=1), 1.0, atol=1e-6)


def test_features_to_raster_roundtrip():
    labels = np.array([0, 1, 2, 0, 1])
    valid_mask = np.array([
        [True, True, True],
        [True, True, False],
    ])
    raster = features_to_raster(labels, valid_mask, nodata_value=-1)
    assert raster.shape == (1, 2, 3)
    assert raster[0, 1, 2] == -1  # nodata pixel
    assert raster[0, 0, 0] == 0
