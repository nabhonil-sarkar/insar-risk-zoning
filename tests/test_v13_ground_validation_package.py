import csv
import hashlib
import json
from pathlib import Path

import pytest

from scripts.build_v13_ground_validation_package import (
    MANIFEST_NAME,
    PROTOCOL_NAME,
    REQUEST_NAME,
    TEMPLATE_NAME,
    build_package,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sources(root: Path) -> tuple[Path, Path, dict[str, str]]:
    output = root / "package"
    output.mkdir()
    footprint = output / "v13_strict_candidate_footprint_north_jakarta.geojson"
    summary = output / "v13_strict_candidate_footprint_north_jakarta.summary.json"
    v13_audit = root / "v13_results_audit.json"
    v14_audit = root / "v14_reference_sensitivity_audit.json"
    polygons = []
    for index in range(21):
        west = 106.70 + index * 0.002
        polygons.append(
            [[
                [west, -6.18],
                [west + 0.001, -6.18],
                [west + 0.001, -6.179],
                [west, -6.18],
            ]]
        )
    footprint.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "candidate_interval": "2020-01-10/2023-06-11",
                            "frame": "047D_09652_111009",
                            "orbit": "descending",
                            "strict_cells": 380,
                            "velocity_values_included": False,
                            "absolute_zero_level_validated": False,
                            "vertical_subsidence_validated": False,
                            "hazard_or_risk_map": False,
                        },
                        "geometry": {
                            "type": "MultiPolygon",
                            "coordinates": polygons,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    summary.write_text(
        json.dumps(
            {
                "geometry_type": "MultiPolygon",
                "multipolygon_parts": 21,
                "strict_cells": 380,
                "rate_values_included": False,
                "frozen_gate_area_m2": 100456701.0359861,
                "north_area_fraction": 0.6839029554861018,
            }
        ),
        encoding="utf-8",
    )
    v13_audit.write_text('{"audit_status":"passed"}', encoding="utf-8")
    v14_audit.write_text(
        '{"terminal_decision":"relative_pattern_only"}', encoding="utf-8"
    )
    expected = {
        path.name: _sha256(path)
        for path in (footprint, summary, v13_audit, v14_audit)
    }
    return v13_audit, v14_audit, expected


def test_builds_review_only_package_with_frozen_sources(tmp_path: Path) -> None:
    v13_audit, v14_audit, expected = _sources(tmp_path)
    output = tmp_path / "package"
    manifest = build_package(output, v13_audit, v14_audit, expected)

    assert manifest["authorization_status"] == (
        "review_only_not_authorized_for_external_send"
    )
    protocol = json.loads((output / PROTOCOL_NAME).read_text(encoding="utf-8"))
    assert protocol["scientific_status"] == "relative_pattern_only"
    assert protocol["candidate"]["velocity_values_in_attachment"] is False
    assert "after inspecting comparison results" in " ".join(
        protocol["prohibited_actions"]
    )
    request = (output / REQUEST_NAME).read_text(encoding="utf-8")
    assert "Not approved or authorized for external transmission" in request
    assert "Data Mounting" in request
    assert "[nama lengkap]" in request
    with (output / TEMPLATE_NAME).open(encoding="utf-8", newline="") as stream:
        header = next(csv.reader(stream))
    assert {"observation_start", "reference_frame", "uncertainty"}.issubset(header)
    saved_manifest = json.loads((output / MANIFEST_NAME).read_text(encoding="utf-8"))
    for item in saved_manifest["package_files"]:
        assert _sha256(Path(item["path"])) == item["sha256"]


def test_rejects_changed_source_before_writing_package(tmp_path: Path) -> None:
    v13_audit, v14_audit, expected = _sources(tmp_path)
    expected[v13_audit.name] = "0" * 64
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        build_package(tmp_path / "package", v13_audit, v14_audit, expected)
    assert not (tmp_path / "package" / PROTOCOL_NAME).exists()
