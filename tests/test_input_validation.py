"""Tests for raw InSAR role discovery and matched-grid validation."""

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from src.utils.input_validation import (
    discover_insar_inputs,
    validate_insar_value_domains,
    validate_matched_insar_grids,
)


def write_tif(path, width=3, height=2, pixel_size=30, value=1.0):
    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:32748",
        "transform": from_origin(0, height * pixel_size,
                                 pixel_size, pixel_size),
        "nodata": np.nan,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.full(
            (1, height, width), value, dtype=np.float32
        ))
    return str(path)


def test_discovers_one_matched_quality_stack(tmp_path):
    for name in (
        "jakarta_vel_2020_2023.tif",
        "jakarta_vstd_2020_2023.tif",
        "jakarta_coh_avg_2020_2023.tif",
        "jakarta_n_unw_2020_2023.tif",
    ):
        write_tif(tmp_path / name)

    inputs = discover_insar_inputs(str(tmp_path))
    assert all(inputs.values())
    assert inputs["velocity"].endswith("jakarta_vel_2020_2023.tif")
    validate_matched_insar_grids(inputs)


def test_rejects_processed_product_name(tmp_path):
    write_tif(tmp_path / "jakarta_velocity_calibrated.tif")
    with pytest.raises(ValueError, match="Processed-product"):
        discover_insar_inputs(str(tmp_path))


def test_rejects_multiple_quality_candidates(tmp_path):
    write_tif(tmp_path / "jakarta_vel.tif")
    write_tif(tmp_path / "jakarta_vstd_a.tif")
    write_tif(tmp_path / "jakarta_vstd_b.tif")
    with pytest.raises(ValueError, match="at most one quality"):
        discover_insar_inputs(str(tmp_path))


def test_rejects_mismatched_period_tokens(tmp_path):
    write_tif(tmp_path / "jakarta_vel_2020_2023.tif")
    write_tif(tmp_path / "jakarta_vstd_2021_2023.tif")
    with pytest.raises(ValueError, match="mismatched period"):
        discover_insar_inputs(str(tmp_path))


def test_rejects_partial_period_labeling(tmp_path):
    write_tif(tmp_path / "jakarta_vel_2020_2023.tif")
    write_tif(tmp_path / "jakarta_vstd.tif")
    with pytest.raises(ValueError, match="omit the period token"):
        discover_insar_inputs(str(tmp_path))


def test_rejects_mismatched_native_grid(tmp_path):
    write_tif(tmp_path / "jakarta_vel.tif")
    write_tif(tmp_path / "jakarta_vstd.tif", width=4)
    inputs = discover_insar_inputs(str(tmp_path))
    with pytest.raises(ValueError, match="native velocity grid"):
        validate_matched_insar_grids(inputs)


def test_rejects_negative_vstd(tmp_path):
    write_tif(tmp_path / "jakarta_vel.tif")
    write_tif(tmp_path / "jakarta_vstd.tif", value=-1.0)
    inputs = discover_insar_inputs(str(tmp_path))
    with pytest.raises(ValueError, match="negative values"):
        validate_insar_value_domains(inputs)
