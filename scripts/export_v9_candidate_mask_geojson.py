"""Export the exact official-DKI intersection of the v9 strict candidate mask."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.windows import Window
from shapely.geometry import MultiPolygon, Point, box, mapping, shape
from shapely.ops import unary_union


EXPECTED_MASK_SHA256 = (
    "850cd07c62963758fe4a8a2a7eed2d6463ad8e9eb68dbb33060bc761918454a9"
)
EXPECTED_BOUNDARY_SHA256 = (
    "7bb4dd0589cec8bd64e8930c94b1835116701b6148f7b7de183e61196593c540"
)
EXPECTED_STRICT_PIXELS = 2477
EXPECTED_MAINLAND_DKI_OVERLAP_KM2 = 193.90855568253448
EXPECTED_MASK_SHAPE = (106, 154)
EXPECTED_MASK_TRANSFORM = (0.005, 0.0, 106.449778, 0.0, -0.005, -6.010389)
EXPECTED_INTERSECTING_CELLS = 670
EXPECTED_CENTRE_CELLS = 633
EXPECTED_MULTIPOLYGON_PARTS = 19
EXPECTED_BOUNDS = (
    106.68580472244946,
    -6.360389005922638,
    106.92224449590249,
    -6.105389,
)
PROJECTED_AREA_CRS = "EPSG:32748"
STRICT_CRITERIA = "finite velocity and vstd; n_gap=0; n_loop_err=0"
SCIENTIFIC_STATUS = "diagnostic_candidate_footprint_pending_independent_validation"
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


def _validated_boundary(path: Path) -> gpd.GeoDataFrame:
    value = json.loads(path.read_text(encoding="utf-8"))
    features = value.get("features", [])
    if value.get("type") != "FeatureCollection" or not features:
        raise ValueError("Boundary is not a non-empty GeoJSON FeatureCollection")
    required = {"wadmkd", "wadmkc", "wadmkk"}
    if any(not required.issubset(feature.get("properties", {})) for feature in features):
        raise ValueError("Official boundary is missing administrative fields")
    frame = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    frame["wadmkk"] = frame["wadmkk"].astype(str).str.strip()
    frame.geometry = frame.geometry.make_valid()
    if frame["wadmkk"].nunique() != 6:
        raise ValueError("Expected six official DKI municipalities/regencies")
    mainland = frame[frame["wadmkk"].str.startswith("JAKARTA ")].copy()
    if mainland["wadmkk"].nunique() != 5:
        raise ValueError("Expected five mainland DKI municipalities")
    return mainland


def export_candidate_mask(
    strict_mask_path: Path,
    boundary_path: Path,
    output_path: Path,
    *,
    expected_mask_sha256: str | None = EXPECTED_MASK_SHA256,
    expected_boundary_sha256: str | None = EXPECTED_BOUNDARY_SHA256,
    expected_strict_pixels: int | None = EXPECTED_STRICT_PIXELS,
    expected_overlap_km2: float | None = EXPECTED_MAINLAND_DKI_OVERLAP_KM2,
    expected_shape: tuple[int, int] | None = EXPECTED_MASK_SHAPE,
    expected_transform: tuple[float, ...] | None = EXPECTED_MASK_TRANSFORM,
    expected_intersecting_cells: int | None = EXPECTED_INTERSECTING_CELLS,
    expected_centre_cells: int | None = EXPECTED_CENTRE_CELLS,
    expected_part_count: int | None = EXPECTED_MULTIPOLYGON_PARTS,
    expected_bounds: tuple[float, float, float, float] | None = EXPECTED_BOUNDS,
) -> dict[str, Any]:
    """Write an exact, unresampled mainland-DKI footprint with provenance."""
    for path in (strict_mask_path, boundary_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    mask_sha = sha256_file(strict_mask_path)
    boundary_sha = sha256_file(boundary_path)
    if expected_mask_sha256 and mask_sha != expected_mask_sha256.lower():
        raise ValueError(f"Strict-mask SHA-256 mismatch: {mask_sha}")
    if expected_boundary_sha256 and boundary_sha != expected_boundary_sha256.lower():
        raise ValueError(f"Boundary SHA-256 mismatch: {boundary_sha}")

    with rasterio.open(strict_mask_path) as source:
        if source.count != 1 or source.crs is None or source.crs.to_string() != "EPSG:4326":
            raise ValueError("Strict mask must be a single-band EPSG:4326 raster")
        if expected_shape is not None and source.shape != expected_shape:
            raise ValueError(f"Strict-mask shape mismatch: {source.shape} != {expected_shape}")
        transform = source.transform
        if expected_transform is not None and not all(
            math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-12)
            for observed, expected in zip(tuple(transform)[:6], expected_transform)
        ):
            raise ValueError(f"Strict-mask transform mismatch: {tuple(transform)[:6]}")
        if source.tags().get("AREA_OR_POINT", "Area") != "Area":
            raise ValueError("Strict mask must use pixel-area semantics")
        values = source.read(1)
        strict = values == 1
        if np.any((values != 0) & (values != 1)):
            raise ValueError("Strict mask contains values other than zero and one")
        strict_pixels = int(strict.sum())
        if expected_strict_pixels is not None and strict_pixels != expected_strict_pixels:
            raise ValueError(
                f"Strict pixel count mismatch: {strict_pixels} != {expected_strict_pixels}"
            )
        strict_rows, strict_columns = np.where(strict)
        polygons = [
            shape(geometry)
            for geometry, value in shapes(
                strict.astype("uint8"),
                mask=strict,
                transform=source.transform,
                connectivity=8,
            )
            if int(value) == 1
        ]
    if not polygons:
        raise ValueError("Strict mask has no polygonizable cells")
    strict_geometry = unary_union(polygons)

    mainland = _validated_boundary(boundary_path)
    municipalities = mainland[["wadmkk", "geometry"]].dissolve(by="wadmkk").reset_index()
    mainland_geometry = municipalities.geometry.union_all()
    strict_utm = gpd.GeoSeries([strict_geometry], crs="EPSG:4326").to_crs(PROJECTED_AREA_CRS).iloc[0]
    mainland_utm = (
        gpd.GeoSeries([mainland_geometry], crs="EPSG:4326")
        .to_crs(PROJECTED_AREA_CRS)
        .iloc[0]
    )
    clipped_utm = strict_utm.intersection(mainland_utm)
    if not clipped_utm.is_valid:
        clipped_utm = clipped_utm.buffer(0)
    if clipped_utm.is_empty:
        raise ValueError("Strict mask has no mainland-DKI overlap")
    overlap_area_km2 = float(clipped_utm.area / 1_000_000.0)
    if expected_overlap_km2 is not None and not math.isclose(
        overlap_area_km2, expected_overlap_km2, rel_tol=0.0, abs_tol=1e-6
    ):
        raise ValueError(
            f"Mainland-DKI overlap changed: {overlap_area_km2} != {expected_overlap_km2} km2"
        )

    clipped = (
        gpd.GeoSeries([clipped_utm], crs=PROJECTED_AREA_CRS)
        .to_crs("EPSG:4326")
        .iloc[0]
    )
    if clipped.geom_type == "Polygon":
        clipped = MultiPolygon([clipped])
    if clipped.geom_type != "MultiPolygon" or not clipped.is_valid or clipped.is_empty:
        raise ValueError(f"Expected a valid non-empty MultiPolygon, found {clipped.geom_type}")
    part_count = len(clipped.geoms)
    if expected_part_count is not None and part_count != expected_part_count:
        raise ValueError(f"MultiPolygon part count mismatch: {part_count} != {expected_part_count}")
    if expected_bounds is not None and not all(
        math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-9)
        for observed, expected in zip(clipped.bounds, expected_bounds)
    ):
        raise ValueError(f"Candidate bounds changed: {clipped.bounds} != {expected_bounds}")

    intersecting_cells = 0
    centre_cells = 0
    for row, column in zip(strict_rows, strict_columns):
        left, bottom, right, top = rasterio.windows.bounds(
            Window(int(column), int(row), 1, 1), transform
        )
        cell = box(left, bottom, right, top)
        if cell.intersection(mainland_geometry).area > 0:
            intersecting_cells += 1
        centre_x, centre_y = rasterio.transform.xy(
            transform, int(row), int(column), offset="center"
        )
        if mainland_geometry.covers(Point(centre_x, centre_y)):
            centre_cells += 1
    if expected_intersecting_cells is not None and intersecting_cells != expected_intersecting_cells:
        raise ValueError(
            f"Intersecting strict-cell count changed: {intersecting_cells} != {expected_intersecting_cells}"
        )
    if expected_centre_cells is not None and centre_cells != expected_centre_cells:
        raise ValueError(f"Centre-in-DKI count changed: {centre_cells} != {expected_centre_cells}")

    feature = {
        "type": "Feature",
        "properties": {
            "artifact_name": "jakarta_v9_strict_candidate_mask_mainland_dki",
            "scientific_status": SCIENTIFIC_STATUS,
            "purpose": "Prioritise independent ground-observation locations for possible colocation; not a validated subsidence, hazard, or risk map.",
            "source_quantity": "Sentinel-1 relative line-of-sight velocity candidate",
            "criteria_code": "finite(velocity,vstd) AND n_gap=0 AND n_loop_err=0",
            "insar_acquisition_span": "2020-01-02/2023-12-24",
            "requested_ground_window": "2020-01-01/2023-12-31",
            "grid_crs": "EPSG:4326",
            "geojson_axis_order": "longitude,latitude",
            "grid_cell_size_degrees": [abs(transform.a), abs(transform.e)],
            "clip_scope": "five mainland DKI municipalities; KAB.ADM.KEP.SERIBU excluded",
            "clip_method": "project both layers to EPSG:32748; exact intersection; transform to CRS84; no resampling, buffer, or simplification",
            "source_mask_sha256": mask_sha,
            "official_boundary_url": OFFICIAL_BOUNDARY_URL,
            "official_boundary_sha256": boundary_sha,
            "strict_pixels_full_roi": strict_pixels,
            "strict_cells_intersecting_mainland_dki": intersecting_cells,
            "strict_cell_centres_in_mainland_dki": centre_cells,
            "mainland_overlap_km2": overlap_area_km2,
            "velocity_values_included": False,
            "comparison_note": "Ground vertical displacement is not automatically identical to radar LOS; projection and colocation rules will be preregistered after data availability is known.",
        },
        "geometry": mapping(clipped),
    }

    collection = {
        "type": "FeatureCollection",
        "name": "v9_strict_candidate_mask_mainland_dki",
        "metadata": {
            "scientific_status": SCIENTIFIC_STATUS,
            "purpose": "Identify independent ground observations overlapping the v9 strict candidate footprint",
            "not_a_deformation_hazard_or_risk_map": True,
            "quality_mask_resampled": False,
            "geometry_method": "exact intersection of native strict raster-cell polygons with official mainland DKI municipality polygons",
            "output_crs": "EPSG:4326",
            "area_calculation_crs": PROJECTED_AREA_CRS,
            "strict_criteria": STRICT_CRITERIA,
            "strict_source_pixels_full_roi": strict_pixels,
            "mainland_dki_overlap_km2": overlap_area_km2,
            "strict_cells_intersecting_mainland_dki": intersecting_cells,
            "strict_cell_centres_in_mainland_dki": centre_cells,
            "multipolygon_parts": part_count,
            "bounds_wsen": list(clipped.bounds),
            "municipalities_with_zero_overlap": ["JAKARTA UTARA"],
            "source_strict_mask": strict_mask_path.name,
            "source_strict_mask_sha256": mask_sha,
            "official_boundary": boundary_path.name,
            "official_boundary_sha256": boundary_sha,
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
    serialized_utm = (
        gpd.GeoSeries([serialized_geometry], crs="EPSG:4326")
        .to_crs(PROJECTED_AREA_CRS)
        .iloc[0]
    )
    if not math.isclose(serialized_utm.area / 1_000_000.0, overlap_area_km2, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError("Serialized GeoJSON area changed during round trip")
    if any(not math.isfinite(value) for value in serialized_geometry.bounds):
        raise ValueError("Serialized GeoJSON contains non-finite bounds")
    if not (-180 <= serialized_geometry.bounds[0] <= serialized_geometry.bounds[2] <= 180):
        raise ValueError("Serialized GeoJSON longitude bounds are invalid")
    if not (-90 <= serialized_geometry.bounds[1] <= serialized_geometry.bounds[3] <= 90):
        raise ValueError("Serialized GeoJSON latitude bounds are invalid")

    summary = {
        "output": output_path.name,
        "output_sha256": sha256_file(output_path),
        "output_bytes": output_path.stat().st_size,
        "feature_count": 1,
        "multipolygon_parts": part_count,
        "municipalities_with_zero_overlap": ["JAKARTA UTARA"],
        "mainland_dki_overlap_km2": overlap_area_km2,
        "strict_source_pixels_full_roi": strict_pixels,
        "strict_cells_intersecting_mainland_dki": intersecting_cells,
        "strict_cell_centres_in_mainland_dki": centre_cells,
        "source_strict_mask_sha256": mask_sha,
        "official_boundary_sha256": boundary_sha,
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
    parser.add_argument("--strict-mask", required=True, type=Path)
    parser.add_argument("--boundary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    arguments = _parse_args()
    result = export_candidate_mask(
        strict_mask_path=arguments.strict_mask,
        boundary_path=arguments.boundary,
        output_path=arguments.output,
    )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
