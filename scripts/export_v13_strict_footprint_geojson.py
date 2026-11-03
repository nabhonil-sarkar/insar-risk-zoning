"""Export the exact v13 strict North-Jakarta footprint without rate values."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from affine import Affine
from pyproj import Transformer
from shapely.geometry import MultiPolygon, box, mapping, shape
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union


EXPECTED_BOUNDARY_SHA256 = (
    "7bb4dd0589cec8bd64e8930c94b1835116701b6148f7b7de183e61196593c540"
)
EXPECTED_DEM_PARAMETERS_SHA256 = (
    "f8ec4cb779cda6978ea5bd48c958cc917669cda957a5a570c8a3d7d012b4a30b"
)
EXPECTED_LEDGER_SHA256 = (
    "e6e4aceb4370e33562aa13bbde908d02eb9ce537754bddf00abc4da62e5ffa87"
)
EXPECTED_POST_GATE_SHA256 = (
    "dec555a09c9ef48d022d9b00485269f96c2a5eb5b2aa1128e04e0b14c89cf880"
)
EXPECTED_ARRAY_SHA256 = {
    "vel": "943279ec2a8aa17ba7d8d6db5cf9a6eae5552c8ccf89f27ab9b63ba13df87895",
    "vstd": "03572b2cc175cca5f9a029d720a9a72628753a5984406172386320822f8c4285",
    "n_gap": "045329a24a8ad2622dc17888a2cebbe96435c8cf975ef442219634bbf66cde14",
    "n_loop_err": "eeff1bc65a94049b6375fe47c1aa6066bfa410143de90feb9add4decdf6880e4",
}
EXPECTED_SHAPE = (106, 154)
EXPECTED_NORTH_CELLS = 618
EXPECTED_STRICT_CELLS = 380
EXPECTED_FROZEN_AREA_M2 = 100_456_701.03598632
EXPECTED_DISSOLVED_AREA_M2 = 100_456_701.01055965
EXPECTED_NORTH_TOTAL_AREA_M2 = 146_887_362.05940768
EXPECTED_PART_COUNT = 21
EXPECTED_BOUNDS = (
    106.71050724172345,
    -6.183094328197304,
    106.97085449374364,
    -6.0852219999999955,
)
PROJECTED_AREA_CRS = "EPSG:32748"
SOURCE_CRS = "EPSG:4326"
FRAME = "047D_09652_111009"
DATE_SPAN = "2020-01-10/2023-06-11"
SCIENTIFIC_STATUS = "relative_pattern_only_pending_independent_ground_anchoring"
OFFICIAL_BOUNDARY_URL = (
    "https://gis-dpmptsp.jakarta.go.id/arcgis/rest/services/Hosted/"
    "Batas_Administrasi_Kelurahan_DKI_Jakarta/FeatureServer/85/query"
    "?where=1%3D1&outFields=wadmkd%2Cwadmkc%2Cwadmkk"
    "&returnGeometry=true&outSR=4326&f=geojson"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_hash(path: Path, expected: str | None, label: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    observed = sha256_file(path)
    if expected is not None and observed != expected.lower():
        raise ValueError(f"{label} SHA-256 mismatch: {observed}")
    return observed


def _dem_grid(path: Path) -> tuple[tuple[int, int], Affine]:
    parameters: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if value.strip():
            parameters[key.strip()] = value.strip().split()[0]
    required = {"width", "nlines", "corner_lon", "corner_lat", "post_lon", "post_lat"}
    if not required.issubset(parameters):
        raise ValueError("DEM parameter file is missing required grid fields")
    width, length = int(parameters["width"]), int(parameters["nlines"])
    post_lon, post_lat = float(parameters["post_lon"]), float(parameters["post_lat"])
    corner_lon, corner_lat = float(parameters["corner_lon"]), float(parameters["corner_lat"])
    if width <= 0 or length <= 0 or post_lon <= 0 or post_lat >= 0:
        raise ValueError("DEM parameters do not describe a positive-width north-up grid")
    transform = Affine(
        post_lon,
        0.0,
        corner_lon - post_lon / 2.0,
        0.0,
        post_lat,
        corner_lat - post_lat / 2.0,
    )
    return (length, width), transform


def _north_districts(path: Path, expected_count: int | None) -> dict[str, Any]:
    collection = json.loads(path.read_text(encoding="utf-8"))
    features = collection.get("features", [])
    if collection.get("type") != "FeatureCollection" or not features:
        raise ValueError("Boundary is not a non-empty GeoJSON FeatureCollection")
    grouped: defaultdict[str, list[Any]] = defaultdict(list)
    for feature in features:
        properties = feature.get("properties", {})
        if not {"wadmkd", "wadmkc", "wadmkk"}.issubset(properties):
            raise ValueError("Official boundary is missing administrative fields")
        if "UTARA" not in str(properties["wadmkk"]).upper():
            continue
        geometry = shape(feature["geometry"])
        if geometry.is_empty:
            raise ValueError("Official North-Jakarta boundary contains empty geometry")
        grouped[str(properties["wadmkc"]).strip()].append(geometry)
    districts = {name: unary_union(parts) for name, parts in grouped.items()}
    if expected_count is not None and len(districts) != expected_count:
        raise ValueError(
            f"Expected {expected_count} North-Jakarta districts, found {len(districts)}"
        )
    if not districts:
        raise ValueError("No North-Jakarta districts were found")
    if any(geometry.is_empty or not geometry.is_valid for geometry in districts.values()):
        raise ValueError("Official North-Jakarta district union contains invalid geometry")
    return districts


def _read_grid(path: Path, grid_shape: tuple[int, int], label: str) -> np.ndarray:
    values = np.fromfile(path, dtype="<f4")
    expected_values = math.prod(grid_shape)
    if values.size != expected_values:
        raise ValueError(f"Unexpected {label} size: {values.size} != {expected_values}")
    return values.reshape(grid_shape)


def export_strict_footprint(
    *,
    dem_parameters_path: Path,
    ledger_path: Path,
    post_gate_path: Path,
    velocity_path: Path,
    velocity_std_path: Path,
    n_gap_path: Path,
    n_loop_err_path: Path,
    boundary_path: Path,
    output_path: Path,
    expected_boundary_sha256: str | None = EXPECTED_BOUNDARY_SHA256,
    expected_dem_parameters_sha256: str | None = EXPECTED_DEM_PARAMETERS_SHA256,
    expected_ledger_sha256: str | None = EXPECTED_LEDGER_SHA256,
    expected_post_gate_sha256: str | None = EXPECTED_POST_GATE_SHA256,
    expected_array_sha256: dict[str, str] | None = EXPECTED_ARRAY_SHA256,
    expected_shape: tuple[int, int] | None = EXPECTED_SHAPE,
    expected_north_cells: int | None = EXPECTED_NORTH_CELLS,
    expected_strict_cells: int | None = EXPECTED_STRICT_CELLS,
    expected_frozen_area_m2: float | None = EXPECTED_FROZEN_AREA_M2,
    expected_dissolved_area_m2: float | None = EXPECTED_DISSOLVED_AREA_M2,
    expected_north_total_area_m2: float | None = EXPECTED_NORTH_TOTAL_AREA_M2,
    expected_part_count: int | None = EXPECTED_PART_COUNT,
    expected_bounds: tuple[float, float, float, float] | None = EXPECTED_BOUNDS,
    expected_north_districts: int | None = 6,
) -> dict[str, Any]:
    """Reconstruct, clip, verify, and serialize the frozen 380-cell footprint."""
    source_hashes = {
        "dem_parameters": _require_hash(
            dem_parameters_path, expected_dem_parameters_sha256, "DEM parameters"
        ),
        "north_pixel_ledger": _require_hash(ledger_path, expected_ledger_sha256, "ledger"),
        "post_inversion_gate": _require_hash(
            post_gate_path, expected_post_gate_sha256, "post-inversion gate"
        ),
        "official_boundary": _require_hash(
            boundary_path, expected_boundary_sha256, "official boundary"
        ),
    }
    array_paths = {
        "vel": velocity_path,
        "vstd": velocity_std_path,
        "n_gap": n_gap_path,
        "n_loop_err": n_loop_err_path,
    }
    for role, path in array_paths.items():
        expected_hash = expected_array_sha256.get(role) if expected_array_sha256 else None
        source_hashes[role] = _require_hash(path, expected_hash, role)

    grid_shape, grid_transform = _dem_grid(dem_parameters_path)
    if expected_shape is not None and grid_shape != expected_shape:
        raise ValueError(f"Grid shape mismatch: {grid_shape} != {expected_shape}")
    arrays = {
        role: _read_grid(path, grid_shape, role) for role, path in array_paths.items()
    }

    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not isinstance(ledger, list):
        raise ValueError("North-pixel ledger must be a JSON list")
    eligible = np.zeros(grid_shape, dtype=bool)
    north_cells: set[tuple[int, int]] = set()
    for record in ledger:
        row, column = int(record["row"]), int(record["col"])
        cell = (row, column)
        if not (0 <= row < grid_shape[0] and 0 <= column < grid_shape[1]):
            raise ValueError(f"Ledger cell is outside the grid: {cell}")
        if cell in north_cells:
            raise ValueError(f"Duplicate ledger cell: {cell}")
        north_cells.add(cell)
        eligible[cell] = bool(record["qualifies"])
    if expected_north_cells is not None and len(north_cells) != expected_north_cells:
        raise ValueError(f"North cell count mismatch: {len(north_cells)} != {expected_north_cells}")

    strict = (
        eligible
        & np.isfinite(arrays["vel"])
        & np.isfinite(arrays["vstd"])
        & (arrays["n_gap"] == 0)
        & (arrays["n_loop_err"] == 0)
    )
    strict_cells = {(int(row), int(column)) for row, column in zip(*np.where(strict))}
    if expected_strict_cells is not None and len(strict_cells) != expected_strict_cells:
        raise ValueError(
            f"Strict-cell count mismatch: {len(strict_cells)} != {expected_strict_cells}"
        )

    post_gate = json.loads(post_gate_path.read_text(encoding="utf-8"))
    if post_gate.get("frame") != FRAME or post_gate.get("candidate_interval") != ["20200110", "20230611"]:
        raise ValueError("Post-inversion gate does not identify the frozen v13 experiment")
    if not post_gate.get("passed"):
        raise ValueError("The frozen v13 post-inversion gate is not passed")
    if int(post_gate.get("strict_qualifying_cells", -1)) != len(strict_cells):
        raise ValueError("Post-inversion gate strict-cell count does not match reconstruction")

    districts_wgs84 = _north_districts(boundary_path, expected_north_districts)
    to_utm = Transformer.from_crs(SOURCE_CRS, PROJECTED_AREA_CRS, always_xy=True).transform
    to_wgs84 = Transformer.from_crs(PROJECTED_AREA_CRS, SOURCE_CRS, always_xy=True).transform
    districts_utm = {
        name: shapely_transform(to_utm, geometry)
        for name, geometry in districts_wgs84.items()
    }

    frozen_area_m2 = 0.0
    north_total_area_m2 = 0.0
    strict_pieces = []
    for row, column in sorted(north_cells):
        left, top = grid_transform * (column, row)
        right, bottom = grid_transform * (column + 1, row + 1)
        cell_wgs84 = box(
            min(left, right), min(bottom, top), max(left, right), max(bottom, top)
        )
        cell_utm = shapely_transform(to_utm, cell_wgs84)
        pieces = [
            cell_utm.intersection(district)
            for district in districts_utm.values()
        ]
        pieces = [piece for piece in pieces if not piece.is_empty and piece.area > 0]
        cell_area = sum(piece.area for piece in pieces)
        north_total_area_m2 += cell_area
        if (row, column) in strict_cells:
            frozen_area_m2 += cell_area
            strict_pieces.extend(pieces)

    if expected_north_total_area_m2 is not None and not math.isclose(
        north_total_area_m2, expected_north_total_area_m2, rel_tol=0.0, abs_tol=1e-3
    ):
        raise ValueError(
            f"North denominator area changed: {north_total_area_m2} != "
            f"{expected_north_total_area_m2} m2"
        )
    if expected_frozen_area_m2 is not None and not math.isclose(
        frozen_area_m2, expected_frozen_area_m2, rel_tol=0.0, abs_tol=1e-3
    ):
        raise ValueError(
            f"Frozen strict area changed: {frozen_area_m2} != {expected_frozen_area_m2} m2"
        )
    if not strict_pieces:
        raise ValueError("The reconstructed strict mask has no North-Jakarta intersection")

    dissolved_utm = unary_union(strict_pieces)
    if dissolved_utm.is_empty or not dissolved_utm.is_valid:
        raise ValueError("Dissolved strict footprint is empty or invalid")
    dissolved_area_m2 = float(dissolved_utm.area)
    if expected_dissolved_area_m2 is not None and not math.isclose(
        dissolved_area_m2, expected_dissolved_area_m2, rel_tol=0.0, abs_tol=1e-3
    ):
        raise ValueError(
            f"Dissolved strict area changed: {dissolved_area_m2} != "
            f"{expected_dissolved_area_m2} m2"
        )
    dissolved_wgs84 = shapely_transform(to_wgs84, dissolved_utm)
    if dissolved_wgs84.geom_type == "Polygon":
        dissolved_wgs84 = MultiPolygon([dissolved_wgs84])
    if dissolved_wgs84.geom_type != "MultiPolygon" or not dissolved_wgs84.is_valid:
        raise ValueError(f"Expected a valid MultiPolygon, found {dissolved_wgs84.geom_type}")
    part_count = len(dissolved_wgs84.geoms)
    if expected_part_count is not None and part_count != expected_part_count:
        raise ValueError(f"Footprint part count mismatch: {part_count} != {expected_part_count}")
    if expected_bounds is not None and not all(
        math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-9)
        for observed, expected in zip(dissolved_wgs84.bounds, expected_bounds)
    ):
        raise ValueError(f"Footprint bounds changed: {dissolved_wgs84.bounds}")

    area_overlap_delta_m2 = dissolved_area_m2 - frozen_area_m2
    feature = {
        "type": "Feature",
        "properties": {
            "artifact_name": "jakarta_v13_strict_candidate_footprint_north_jakarta",
            "scientific_status": SCIENTIFIC_STATUS,
            "purpose": (
                "Locate date-compatible independent GNSS, levelling, or benchmark "
                "observations within the exact v13 strict footprint."
            ),
            "candidate_interval": DATE_SPAN,
            "frame": FRAME,
            "orbit": "descending",
            "strict_cells": len(strict_cells),
            "velocity_values_included": False,
            "absolute_zero_level_validated": False,
            "vertical_subsidence_validated": False,
            "hazard_or_risk_map": False,
        },
        "geometry": mapping(dissolved_wgs84),
    }
    collection = {
        "type": "FeatureCollection",
        "name": "v13_strict_candidate_footprint_north_jakarta",
        "metadata": {
            "scientific_status": SCIENTIFIC_STATUS,
            "terminal_v14_outcome": "relative_pattern_only",
            "purpose": "Ground-observation colocation attachment only",
            "not_a_deformation_hazard_or_risk_map": True,
            "rate_values_included": False,
            "quality_mask_resampled": False,
            "grid_crs": SOURCE_CRS,
            "output_crs": SOURCE_CRS,
            "geojson_axis_order": "longitude,latitude",
            "area_calculation_crs": PROJECTED_AREA_CRS,
            "strict_criteria": [
                "passes unchanged v11 local network gate",
                "finite velocity and vstd in the authenticated source arrays",
                "n_gap=0",
                "n_loop_err=0",
            ],
            "geometry_method": (
                "Reconstruct the native 380-cell mask; project each native cell and "
                "each official North-Jakarta district to EPSG:32748; calculate exact "
                "intersections; dissolve; transform to EPSG:4326; no resampling, "
                "buffering, or simplification."
            ),
            "official_boundary_url": OFFICIAL_BOUNDARY_URL,
            "source_hashes_sha256": source_hashes,
            "north_candidate_cells": len(north_cells),
            "strict_cells": len(strict_cells),
            "strict_cells_intersecting_north_jakarta": len(strict_cells),
            "frozen_gate_area_m2": frozen_area_m2,
            "dissolved_geometry_area_m2": dissolved_area_m2,
            "dissolved_minus_frozen_area_m2": area_overlap_delta_m2,
            "north_total_area_m2": north_total_area_m2,
            "north_area_fraction": frozen_area_m2 / north_total_area_m2,
            "multipolygon_parts": part_count,
            "bounds_wsen": list(dissolved_wgs84.bounds),
            "administrative_overlap_note": (
                "The dissolved valid geometry removes only sub-square-metre overlap "
                "slivers between official district polygons; the frozen gate area is "
                "retained separately and reproduced within 0.001 m2."
            ),
        },
        "features": [feature],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".partial")
    temporary.write_text(
        json.dumps(collection, separators=(",", ":"), allow_nan=False), encoding="utf-8"
    )
    temporary.replace(output_path)

    serialized = json.loads(output_path.read_text(encoding="utf-8"))
    serialized_geometry = shape(serialized["features"][0]["geometry"])
    if (
        serialized_geometry.geom_type != "MultiPolygon"
        or serialized_geometry.is_empty
        or not serialized_geometry.is_valid
        or serialized_geometry.has_z
    ):
        raise ValueError("Serialized GeoJSON geometry failed validity checks")
    serialized_area_m2 = float(shapely_transform(to_utm, serialized_geometry).area)
    if not math.isclose(
        serialized_area_m2, dissolved_area_m2, rel_tol=0.0, abs_tol=0.1
    ):
        raise ValueError("Serialized GeoJSON area changed during round trip")

    summary = {
        "output": output_path.name,
        "output_sha256": sha256_file(output_path),
        "output_bytes": output_path.stat().st_size,
        "feature_count": 1,
        "geometry_type": "MultiPolygon",
        "multipolygon_parts": part_count,
        "strict_cells": len(strict_cells),
        "frozen_gate_area_m2": frozen_area_m2,
        "dissolved_geometry_area_m2": dissolved_area_m2,
        "dissolved_minus_frozen_area_m2": area_overlap_delta_m2,
        "north_total_area_m2": north_total_area_m2,
        "north_area_fraction": frozen_area_m2 / north_total_area_m2,
        "rate_values_included": False,
        "scientific_status": SCIENTIFIC_STATUS,
    }
    summary_path = output_path.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8"
    )
    summary["summary"] = summary_path.name
    summary["summary_sha256"] = sha256_file(summary_path)
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem-parameters", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--post-gate", required=True, type=Path)
    parser.add_argument("--velocity", required=True, type=Path)
    parser.add_argument("--velocity-std", required=True, type=Path)
    parser.add_argument("--n-gap", required=True, type=Path)
    parser.add_argument("--n-loop-err", required=True, type=Path)
    parser.add_argument("--boundary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    arguments = _parse_args()
    result = export_strict_footprint(
        dem_parameters_path=arguments.dem_parameters,
        ledger_path=arguments.ledger,
        post_gate_path=arguments.post_gate,
        velocity_path=arguments.velocity,
        velocity_std_path=arguments.velocity_std,
        n_gap_path=arguments.n_gap,
        n_loop_err_path=arguments.n_loop_err,
        boundary_path=arguments.boundary,
        output_path=arguments.output,
    )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
