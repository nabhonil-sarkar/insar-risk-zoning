from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from scripts.export_embeddings import reference_grid
from src.m2_embedding_extraction import EMBEDDING_BANDS


def _write_reference(path: Path, count: int = 64) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=3,
        count=count,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(106.45, -6.01, 0.001, 0.001),
    ) as dataset:
        dataset.write(np.ones((count, 3, 4), dtype=np.float32))
        dataset.descriptions = tuple(EMBEDDING_BANDS[:count])


def test_reference_grid_freezes_dimensions_transform_and_bands(tmp_path: Path):
    path = tmp_path / "reference.tif"
    _write_reference(path)

    grid = reference_grid(path)

    assert grid["width"] == 4
    assert grid["height"] == 3
    assert grid["crs"] == "EPSG:4326"
    assert grid["crs_transform"] == [0.001, 0, 106.45, 0, -0.001, -6.01]
    assert grid["band_names"] == EMBEDDING_BANDS


def test_reference_grid_rejects_incomplete_embedding(tmp_path: Path):
    path = tmp_path / "incomplete.tif"
    _write_reference(path, count=63)
    with pytest.raises(ValueError, match="A00 through A63"):
        reference_grid(path)
