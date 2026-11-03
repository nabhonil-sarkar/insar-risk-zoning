import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from scripts.prepare_alphaearth_annual_change import build_contract, sha256_file
from src.m2_embedding_extraction import EMBEDDING_BANDS


def _write_reference(path: Path, descriptions=EMBEDDING_BANDS) -> Path:
    profile = {
        "driver": "GTiff",
        "width": 3,
        "height": 2,
        "count": 64,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": from_origin(106.45, -6.01, 0.001, 0.001),
        "nodata": None,
    }
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(np.ones((64, 2, 3), dtype=np.float32))
        dataset.descriptions = tuple(descriptions)
    return path


def test_contract_preserves_all_years_and_marks_2025_pending(tmp_path: Path):
    input_dir = tmp_path / "raw"
    input_dir.mkdir()
    reference = _write_reference(
        input_dir / "AlphaEarth_Jakarta_Wide_30m_2023.tif"
    )
    output = tmp_path / "contract.json"

    contract = build_contract(
        reference,
        input_dir,
        output,
        years=range(2020, 2026),
        catalog_latest_year=2024,
        expected_reference_sha256=sha256_file(reference),
    )

    assert contract["desired_years"] == [2020, 2021, 2022, 2023, 2024, 2025]
    assert contract["official_catalog"]["requested_years_not_yet_listed"] == [2025]
    assert contract["missing_local_years"] == [2020, 2021, 2022, 2024, 2025]
    assert contract["frozen_reference_grid"]["band_names"] == EMBEDDING_BANDS
    assert contract["export_contract"]["crs_transform"] == [
        0.001,
        0.0,
        106.45,
        0.0,
        -0.001,
        -6.01,
    ]
    assert len(contract["planned_comparisons"]["adjacent_year"]) == 5
    assert json.loads(output.read_text(encoding="utf-8")) == contract


def test_contract_rejects_wrong_band_order(tmp_path: Path):
    input_dir = tmp_path / "raw"
    input_dir.mkdir()
    reference = _write_reference(
        input_dir / "AlphaEarth_Jakarta_Wide_30m_2023.tif",
        descriptions=[f"wrong_{index}" for index in range(64)],
    )
    with pytest.raises(ValueError, match="A00 through A63"):
        build_contract(
            reference,
            input_dir,
            tmp_path / "contract.json",
            expected_reference_sha256=sha256_file(reference),
        )
