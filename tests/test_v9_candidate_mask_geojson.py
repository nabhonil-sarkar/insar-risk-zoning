import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from scripts.export_v9_candidate_mask_geojson import export_candidate_mask


def _write_mask(path: Path) -> None:
    profile = {
        "driver": "GTiff",
        "height": 2,
        "width": 2,
        "count": 1,
        "dtype": "uint8",
        "crs": "EPSG:4326",
        "transform": from_origin(106.0, -6.0, 0.01, 0.01),
    }
    with rasterio.open(path, "w", **profile) as destination:
        destination.write(np.array([[1, 0], [1, 0]], dtype="uint8"), 1)


def _write_boundary(path: Path) -> None:
    features = []
    names = [
        "JAKARTA BARAT",
        "JAKARTA PUSAT",
        "JAKARTA SELATAN",
        "JAKARTA TIMUR",
        "JAKARTA UTARA",
        "KAB.ADM.KEP.SERIBU",
    ]
    for index, name in enumerate(names):
        west = 106.0 + index * 0.002
        east = west + 0.002
        features.append(
            {
                "type": "Feature",
                "properties": {"wadmkd": f"V{index}", "wadmkc": f"D{index}", "wadmkk": name},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[west, -6.02], [east, -6.02], [east, -6.0], [west, -6.0], [west, -6.02]]],
                },
            }
        )
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")


def test_export_is_exact_diagnostic_footprint_without_velocity(tmp_path):
    mask = tmp_path / "mask.tif"
    boundary = tmp_path / "boundary.geojson"
    output = tmp_path / "candidate.geojson"
    _write_mask(mask)
    _write_boundary(boundary)

    summary = export_candidate_mask(
        mask,
        boundary,
        output,
        expected_mask_sha256=None,
        expected_boundary_sha256=None,
        expected_strict_pixels=2,
        expected_overlap_km2=None,
        expected_shape=None,
        expected_transform=None,
        expected_intersecting_cells=None,
        expected_centre_cells=None,
        expected_part_count=None,
        expected_bounds=None,
    )

    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["metadata"]["quality_mask_resampled"] is False
    assert value["metadata"]["not_a_deformation_hazard_or_risk_map"] is True
    assert summary["feature_count"] > 0
    assert value["features"][0]["properties"]["velocity_values_included"] is False
    assert all(
        not any(
            key.startswith("velocity_") and key != "velocity_values_included"
            for key in feature["properties"]
        )
        for feature in value["features"]
    )


def test_export_rejects_unexpected_mask_hash(tmp_path):
    mask = tmp_path / "mask.tif"
    boundary = tmp_path / "boundary.geojson"
    _write_mask(mask)
    _write_boundary(boundary)

    with pytest.raises(ValueError, match="Strict-mask SHA-256 mismatch"):
        export_candidate_mask(
            mask,
            boundary,
            tmp_path / "candidate.geojson",
            expected_mask_sha256="0" * 64,
            expected_boundary_sha256=None,
            expected_strict_pixels=None,
            expected_overlap_km2=None,
            expected_shape=None,
            expected_transform=None,
            expected_intersecting_cells=None,
            expected_centre_cells=None,
            expected_part_count=None,
            expected_bounds=None,
        )
