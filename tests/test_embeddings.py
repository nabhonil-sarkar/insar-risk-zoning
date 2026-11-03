"""Tests for embedding normalization and provenance."""

import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import src.m2_embedding_extraction as m2


def write_embedding(path, bands=64):
    values = np.arange(bands * 4, dtype=np.float64).reshape(bands, 2, 2)
    profile = {
        "driver": "GTiff",
        "width": 2,
        "height": 2,
        "count": bands,
        "dtype": "float64",
        "crs": "EPSG:32748",
        "transform": from_origin(0, 60, 30, 30),
        "nodata": np.nan,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(values)
    return str(path)


def test_normalization_can_return_reproducible_parameters():
    data = np.array([
        [[1.0, 2.0], [3.0, 4.0]],
        [[5.0, 5.0], [5.0, 5.0]],
    ])
    normalized, params = m2.normalize_embeddings(
        data, method="zscore", return_params=True
    )
    assert normalized.dtype == np.float32
    assert params["method"] == "zscore"
    assert len(params["bands"]) == 2
    assert params["bands"][0]["mean"] == pytest.approx(2.5)
    assert params["bands"][1]["std"] == 0.0
    assert np.all(normalized[1] == 0)


def test_preprocess_writes_float32_and_normalization_tags(
        tmp_path, monkeypatch):
    monkeypatch.setattr(m2, "COMMON_CRS", "EPSG:32748")
    monkeypatch.setattr(m2, "COMMON_RESOLUTION", 30)
    monkeypatch.setattr(m2, "NORMALIZATION_METHOD", "zscore")
    source = write_embedding(tmp_path / "embedding_2023.tif")

    output = m2.preprocess_embeddings(
        source, output_dir=str(tmp_path / "processed")
    )
    with rasterio.open(output) as dataset:
        assert dataset.dtypes == ("float32",) * 64
        tags = dataset.tags()
    params = json.loads(tags["normalization_parameters"])
    assert tags["normalization_method"] == "zscore"
    assert tags["embedding_dimensions"] == "64"
    assert len(params["bands"]) == 64


def test_preprocess_rejects_wrong_band_count(tmp_path, monkeypatch):
    monkeypatch.setattr(m2, "COMMON_CRS", "EPSG:32748")
    monkeypatch.setattr(m2, "COMMON_RESOLUTION", 30)
    source = write_embedding(tmp_path / "bad.tif", bands=3)
    with pytest.raises(ValueError, match="Expected 64 embedding bands"):
        m2.preprocess_embeddings(
            source, output_dir=str(tmp_path / "processed")
        )


def test_official_embedding_band_order_is_a00_through_a63():
    assert m2.EMBEDDING_BANDS == [f"A{i:02d}" for i in range(64)]


def test_embedding_change_preserves_invalid_and_zero_vector_mask():
    first = np.ones((2, 2, 2), dtype=np.float32)
    second = first.copy()
    first[:, 0, 1] = 0
    second[:, 1, 0] = np.nan
    second[:, 1, 1] = -1

    change = m2.compute_embedding_change(first, second, metric="cosine")

    assert change.shape == (1, 2, 2)
    assert change[0, 0, 0] == pytest.approx(0)
    assert np.isnan(change[0, 0, 1])
    assert np.isnan(change[0, 1, 0])
    assert change[0, 1, 1] == pytest.approx(2)
