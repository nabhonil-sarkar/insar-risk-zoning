import json
from pathlib import Path

import numpy as np
import pytest

from scripts.export_v13_strict_footprint_geojson import export_strict_footprint


def _write_sources(root: Path) -> dict[str, Path]:
    paths = {
        "dem": root / "EQA.dem_par",
        "ledger": root / "ledger.json",
        "post_gate": root / "post_gate.json",
        "vel": root / "vel",
        "vstd": root / "vstd",
        "n_gap": root / "n_gap",
        "n_loop_err": root / "n_loop_err",
        "boundary": root / "boundary.geojson",
    }
    paths["dem"].write_text(
        "\n".join(
            [
                "width: 2",
                "nlines: 2",
                "corner_lat: -6.005",
                "corner_lon: 106.005",
                "post_lat: -0.01",
                "post_lon: 0.01",
            ]
        ),
        encoding="utf-8",
    )
    paths["ledger"].write_text(
        json.dumps(
            [
                {"row": 0, "col": 0, "qualifies": True},
                {"row": 1, "col": 0, "qualifies": True},
            ]
        ),
        encoding="utf-8",
    )
    paths["post_gate"].write_text(
        json.dumps(
            {
                "frame": "047D_09652_111009",
                "candidate_interval": ["20200110", "20230611"],
                "passed": True,
                "strict_qualifying_cells": 2,
            }
        ),
        encoding="utf-8",
    )
    for role in ("vel", "vstd", "n_gap", "n_loop_err"):
        values = np.zeros((2, 2), dtype="<f4")
        if role in {"vel", "vstd"}:
            values[:] = 1.0
        values.tofile(paths[role])
    paths["boundary"].write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "wadmkd": "TEST",
                            "wadmkc": "TEST DISTRICT",
                            "wadmkk": "JAKARTA UTARA",
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [106.0, -6.02],
                                    [106.01, -6.02],
                                    [106.01, -6.0],
                                    [106.0, -6.0],
                                    [106.0, -6.02],
                                ]
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return paths


def _export_synthetic(paths: dict[str, Path], output: Path):
    return export_strict_footprint(
        dem_parameters_path=paths["dem"],
        ledger_path=paths["ledger"],
        post_gate_path=paths["post_gate"],
        velocity_path=paths["vel"],
        velocity_std_path=paths["vstd"],
        n_gap_path=paths["n_gap"],
        n_loop_err_path=paths["n_loop_err"],
        boundary_path=paths["boundary"],
        output_path=output,
        expected_boundary_sha256=None,
        expected_dem_parameters_sha256=None,
        expected_ledger_sha256=None,
        expected_post_gate_sha256=None,
        expected_array_sha256=None,
        expected_shape=(2, 2),
        expected_north_cells=2,
        expected_strict_cells=2,
        expected_frozen_area_m2=None,
        expected_dissolved_area_m2=None,
        expected_north_total_area_m2=None,
        expected_part_count=1,
        expected_bounds=None,
        expected_north_districts=1,
    )


def test_export_contains_exact_geometry_and_no_rate_values(tmp_path):
    paths = _write_sources(tmp_path)
    output = tmp_path / "footprint.geojson"
    summary = _export_synthetic(paths, output)

    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["metadata"]["quality_mask_resampled"] is False
    assert value["metadata"]["rate_values_included"] is False
    assert value["metadata"]["not_a_deformation_hazard_or_risk_map"] is True
    assert value["features"][0]["properties"]["velocity_values_included"] is False
    assert value["features"][0]["geometry"]["type"] == "MultiPolygon"
    assert summary["strict_cells"] == 2


def test_export_rejects_a_changed_source_hash(tmp_path):
    paths = _write_sources(tmp_path)
    with pytest.raises(ValueError, match="ledger SHA-256 mismatch"):
        export_strict_footprint(
            dem_parameters_path=paths["dem"],
            ledger_path=paths["ledger"],
            post_gate_path=paths["post_gate"],
            velocity_path=paths["vel"],
            velocity_std_path=paths["vstd"],
            n_gap_path=paths["n_gap"],
            n_loop_err_path=paths["n_loop_err"],
            boundary_path=paths["boundary"],
            output_path=tmp_path / "footprint.geojson",
            expected_boundary_sha256=None,
            expected_dem_parameters_sha256=None,
            expected_ledger_sha256="0" * 64,
            expected_post_gate_sha256=None,
            expected_array_sha256=None,
        )


def test_real_v13_sources_reproduce_the_frozen_380_cell_footprint(tmp_path):
    root = Path("data/output/v13_audit")
    if not root.exists():
        pytest.skip("Local v13 audit bundle is not distributed with the repository")
    ts = root / "TS_GEOCml5clip_desc47_short_reunw_mp"
    output = tmp_path / "v13.geojson"
    summary = export_strict_footprint(
        dem_parameters_path=ts / "info/EQA.dem_par",
        ledger_path=ts / "info/desc47_short_reunw_unfiltered_roi_ml5_mp_north_pixel_ledger.json",
        post_gate_path=ts / "info/desc47_short_reunw_unfiltered_roi_ml5_mp_post_inversion_gate.json",
        velocity_path=ts / "results/vel",
        velocity_std_path=ts / "results/vstd",
        n_gap_path=ts / "results/n_gap",
        n_loop_err_path=ts / "results/n_loop_err",
        boundary_path=root / "dki_kelurahan_official.geojson",
        output_path=output,
    )

    assert summary["strict_cells"] == 380
    assert summary["multipolygon_parts"] == 21
    assert summary["rate_values_included"] is False
    assert summary["north_area_fraction"] == pytest.approx(0.6839029554861039)
