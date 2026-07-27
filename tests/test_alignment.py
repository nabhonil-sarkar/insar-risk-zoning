"""
Tests for Module 3 — Data Alignment.

Replaces the former test_fusion.py, which tested the fusion-era
`normalize_features(..., insar_weight=...)` API. That API was removed in
v0.2.0 when the project moved to the two-stage design (M2 is the single
normalization authority; M3 only aligns and flattens — no fusion, no
weighting).
"""

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import src.m3_feature_fusion as m3
from src.m3_feature_fusion import prepare_embedding_features
from src.utils.geo_utils import _resolve_resampling


@pytest.fixture
def clean_embedding_tif(tmp_path):
    """A small 4-band float32 GeoTIFF with no NaNs (every pixel valid)."""
    h, w, bands = 10, 10, 4
    rng = np.random.RandomState(42)
    data = rng.randn(bands, h, w).astype("float32")

    path = tmp_path / "embeddings_norm.tif"
    profile = {
        "driver": "GTiff", "height": h, "width": w, "count": bands,
        "dtype": "float32", "crs": "EPSG:32748",
        "transform": from_origin(700000, 9300000, 30, 30),
        "nodata": np.nan,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data)
    return str(path), data


def test_feature_matrix_shape(clean_embedding_tif):
    """Flattened features: one row per valid pixel, one column per band."""
    path, data = clean_embedding_tif
    bands, h, w = data.shape

    features, valid_mask, full_features, profile = \
        prepare_embedding_features(path, sample=False)

    assert full_features.shape == (int(valid_mask.sum()), bands)
    assert valid_mask.shape == (h, w)
    # With no NaNs in the input, every pixel is valid
    assert valid_mask.all()
    assert full_features.shape[0] == h * w


def test_no_nans_in_features(clean_embedding_tif):
    """M3 must hand the clustering stage a finite feature matrix."""
    path, _ = clean_embedding_tif
    _, _, full_features, _ = prepare_embedding_features(path, sample=False)
    assert np.isfinite(full_features).all()


def test_no_normalization_reapplied(clean_embedding_tif):
    """
    M2 is the single normalization authority — M3 must return the raster
    values as-is (modulo NaN replacement), not re-normalize them.
    """
    path, data = clean_embedding_tif
    _, valid_mask, full_features, _ = \
        prepare_embedding_features(path, sample=False)

    expected = data.reshape(data.shape[0], -1).T  # (H*W, bands)
    np.testing.assert_allclose(full_features, expected, rtol=1e-6)


def test_sampling_respects_cap(clean_embedding_tif, monkeypatch):
    """With sample=True, the training subset honors the configured cap."""
    path, data = clean_embedding_tif
    n_valid = data.shape[1] * data.shape[2]  # 100

    monkeypatch.setattr(m3, "MAX_CLUSTERING_SAMPLES", 10)
    monkeypatch.setattr(m3, "SAMPLE_FRACTION", 0.1)

    features, _, full_features, _ = prepare_embedding_features(
        path, sample=True
    )

    assert full_features.shape[0] == n_valid       # full set untouched
    assert features.shape[0] == 10                 # min(10, 100 * 0.1)
    assert features.shape[1] == full_features.shape[1]


def test_invalid_resampling_name_fails_clearly():
    with pytest.raises(ValueError, match="Unknown resampling method"):
        _resolve_resampling("invented-gradient")
