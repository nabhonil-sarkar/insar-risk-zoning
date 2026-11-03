"""Measure spatial continuity and official-DKI coverage of the v9 strict mask."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib
import numpy as np
import rasterio
from matplotlib.colors import TwoSlopeNorm
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import box, shape
from shapely.ops import unary_union

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


OFFICIAL_BOUNDARY_SERVICE = (
    "https://gis-dpmptsp.jakarta.go.id/arcgis/rest/services/Hosted/"
    "Batas_Administrasi_Kelurahan_DKI_Jakarta/FeatureServer/85/query"
    "?where=1%3D1&outFields=wadmkd%2Cwadmkc%2Cwadmkk"
    "&returnGeometry=true&outSR=4326&f=geojson"
)
EQUAL_AREA_CRS = "EPSG:32748"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_official_boundary(url: str, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    downloaded = False
    if not destination.exists():
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Jakarta-InSAR-v9-spatial-audit/1.0"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
        parsed = json.loads(payload)
        if parsed.get("type") != "FeatureCollection" or not parsed.get("features"):
            raise ValueError("Official boundary endpoint did not return a FeatureCollection")
        temporary = destination.with_suffix(destination.suffix + ".partial")
        temporary.write_bytes(payload)
        temporary.replace(destination)
        downloaded = True

    parsed = json.loads(destination.read_text(encoding="utf-8"))
    features = parsed.get("features", [])
    if parsed.get("type") != "FeatureCollection" or len(features) < 260:
        raise ValueError(
            f"Official boundary census is incomplete: {len(features)} features"
        )
    required = {"wadmkd", "wadmkc", "wadmkk"}
    for feature in features:
        if not required.issubset(feature.get("properties", {})):
            raise ValueError("Official boundary feature is missing administrative fields")
    return {
        "url": url,
        "file": destination.name,
        "sha256": sha256_file(destination),
        "bytes": destination.stat().st_size,
        "feature_count": len(features),
        "downloaded_this_run": downloaded,
    }


def connected_component_records(
    strict: np.ndarray,
    velocity: np.ndarray,
    dki_center_mask: np.ndarray,
    transform: rasterio.Affine,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    labels, component_count = ndimage.label(
        strict, structure=np.ones((3, 3), dtype="uint8")
    )
    records: list[dict[str, Any]] = []
    for component_id in range(1, component_count + 1):
        rows, columns = np.where(labels == component_id)
        values = velocity[rows, columns]
        centre_longitudes = transform.c + (columns + 0.5) * transform.a
        centre_latitudes = transform.f + (rows + 0.5) * transform.e
        records.append(
            {
                "component_id": component_id,
                "pixels": int(rows.size),
                "fraction_of_strict_pixels": float(rows.size / strict.sum()),
                "dki_center_pixels": int(dki_center_mask[rows, columns].sum()),
                "centroid_lon": float(centre_longitudes.mean()),
                "centroid_lat": float(centre_latitudes.mean()),
                "west": float(centre_longitudes.min() - abs(transform.a) / 2),
                "east": float(centre_longitudes.max() + abs(transform.a) / 2),
                "south": float(centre_latitudes.min() - abs(transform.e) / 2),
                "north": float(centre_latitudes.max() + abs(transform.e) / 2),
                "velocity_min_mmyr": float(values.min()),
                "velocity_median_mmyr": float(np.median(values)),
                "velocity_max_mmyr": float(values.max()),
            }
        )
    records.sort(key=lambda item: (-item["pixels"], item["component_id"]))
    return labels, records


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        raise ValueError(f"No records to write: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def _plot_map(
    path: Path,
    strict: np.ndarray,
    velocity: np.ndarray,
    transform: rasterio.Affine,
    municipalities: gpd.GeoDataFrame,
) -> None:
    west, south, east, north = rasterio.transform.array_bounds(
        strict.shape[0], strict.shape[1], transform
    )
    displayed = np.where(strict, velocity, np.nan)
    maximum = float(np.nanmax(np.abs(displayed)))
    figure, axis = plt.subplots(figsize=(10.5, 7.2), constrained_layout=True)
    municipalities.plot(
        ax=axis,
        facecolor="#e8e8e8",
        edgecolor="#404040",
        linewidth=0.8,
        zorder=1,
    )
    image = axis.imshow(
        displayed,
        extent=(west, east, south, north),
        origin="upper",
        interpolation="nearest",
        cmap="RdBu_r",
        norm=TwoSlopeNorm(vmin=-maximum, vcenter=0.0, vmax=maximum),
        zorder=2,
    )
    municipalities.boundary.plot(ax=axis, color="#202020", linewidth=0.8, zorder=3)
    visible = municipalities[municipalities.intersects(box(west, south, east, north))]
    for _, row in visible.iterrows():
        point = row.geometry.intersection(box(west, south, east, north)).representative_point()
        label = str(row["municipality"]).replace("JAKARTA ", "").title()
        axis.text(
            point.x,
            point.y,
            label,
            ha="center",
            va="center",
            fontsize=8,
            color="#111111",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.72, "pad": 1.5},
            zorder=4,
        )
    axis.set_xlim(west, east)
    axis.set_ylim(south, north)
    axis.set_xlabel("Longitude (degrees east)")
    axis.set_ylabel("Latitude (degrees north)")
    axis.set_title("V9 strict-mask line-of-sight velocity candidate")
    axis.grid(color="#777777", linewidth=0.35, alpha=0.35)
    colorbar = figure.colorbar(image, ax=axis, shrink=0.82, pad=0.02)
    colorbar.set_label("Relative LOS velocity (mm/year)")
    figure.text(
        0.01,
        0.005,
        "Strict pixels: finite velocity/vstd, n_gap=0, n_loop_err=0. "
        "Boundary: DKI Jakarta government FeatureServer. Diagnostic only.",
        fontsize=8,
        color="#333333",
    )
    figure.savefig(path, dpi=180, facecolor="white")
    plt.close(figure)


def run(
    strict_mask_path: Path,
    strict_velocity_path: Path,
    output_dir: Path,
    boundary_url: str = OFFICIAL_BOUNDARY_SERVICE,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    boundary_path = output_dir / "dki_kelurahan_official.geojson"
    boundary_source = fetch_official_boundary(boundary_url, boundary_path)

    with rasterio.open(strict_mask_path) as mask_source:
        strict = mask_source.read(1) == 1
        transform = mask_source.transform
        crs = mask_source.crs
        shape_value = mask_source.shape
        bounds = mask_source.bounds
    with rasterio.open(strict_velocity_path) as velocity_source:
        if (
            velocity_source.shape != shape_value
            or velocity_source.transform != transform
            or velocity_source.crs != crs
        ):
            raise ValueError("Strict mask and velocity grids differ")
        velocity = velocity_source.read(1)
    if crs is None or crs.to_string() != "EPSG:4326":
        raise ValueError(f"Expected EPSG:4326 strict rasters, found {crs}")
    if int(strict.sum()) != int(np.isfinite(velocity).sum()):
        raise ValueError("Strict mask and finite velocity counts differ")
    if np.any(~np.isfinite(velocity[strict])) or np.any(np.isfinite(velocity[~strict])):
        raise ValueError("Strict velocity nodata footprint does not match the mask")

    boundary_json = json.loads(boundary_path.read_text(encoding="utf-8"))
    kelurahan = gpd.GeoDataFrame.from_features(boundary_json["features"], crs="EPSG:4326")
    kelurahan["wadmkk"] = kelurahan["wadmkk"].astype(str).str.strip()
    kelurahan.geometry = kelurahan.geometry.make_valid()
    municipalities = kelurahan[["wadmkk", "geometry"]].dissolve(by="wadmkk").reset_index()
    municipalities = municipalities.rename(columns={"wadmkk": "municipality"})

    strict_polygons = [
        shape(geometry)
        for geometry, value in shapes(
            strict.astype("uint8"), mask=strict, transform=transform, connectivity=8
        )
        if int(value) == 1
    ]
    strict_geometry = unary_union(strict_polygons)
    roi_geometry = box(bounds.left, bounds.bottom, bounds.right, bounds.top)
    dki_geometry = municipalities.geometry.union_all()

    dki_center_mask = rasterio.features.rasterize(
        [(dki_geometry, 1)],
        out_shape=shape_value,
        transform=transform,
        fill=0,
        all_touched=False,
        dtype="uint8",
    ).astype(bool)
    _, component_records = connected_component_records(
        strict, velocity, dki_center_mask, transform
    )

    strict_utm = gpd.GeoSeries([strict_geometry], crs="EPSG:4326").to_crs(EQUAL_AREA_CRS).iloc[0]
    roi_utm = gpd.GeoSeries([roi_geometry], crs="EPSG:4326").to_crs(EQUAL_AREA_CRS).iloc[0]
    municipality_utm = municipalities.to_crs(EQUAL_AREA_CRS)
    coverage_records: list[dict[str, Any]] = []
    for _, row in municipality_utm.iterrows():
        geometry = row.geometry
        within_roi = geometry.intersection(roi_utm)
        strict_overlap = geometry.intersection(strict_utm)
        total_area = geometry.area / 1_000_000.0
        roi_area = within_roi.area / 1_000_000.0
        strict_area = strict_overlap.area / 1_000_000.0
        coverage_records.append(
            {
                "municipality": row["municipality"],
                "official_area_km2": float(total_area),
                "area_inside_raster_roi_km2": float(roi_area),
                "strict_overlap_km2": float(strict_area),
                "strict_fraction_of_area_inside_roi": float(strict_area / roi_area)
                if roi_area
                else 0.0,
                "strict_fraction_of_full_official_area": float(strict_area / total_area)
                if total_area
                else 0.0,
            }
        )
    coverage_records.sort(key=lambda item: item["municipality"])

    total_dki_utm = municipality_utm.geometry.union_all()
    dki_inside_roi = total_dki_utm.intersection(roi_utm)
    strict_inside_dki = strict_utm.intersection(total_dki_utm)
    mainland_utm = municipality_utm[
        municipality_utm["municipality"].str.startswith("JAKARTA ")
    ]
    if len(mainland_utm) != 5:
        raise ValueError(
            f"Expected five mainland Jakarta municipalities, found {len(mainland_utm)}"
        )
    mainland_union_utm = mainland_utm.geometry.union_all()
    mainland_inside_roi = mainland_union_utm.intersection(roi_utm)
    strict_inside_mainland = strict_utm.intersection(mainland_union_utm)
    strict_area_km2 = strict_utm.area / 1_000_000.0
    strict_inside_dki_km2 = strict_inside_dki.area / 1_000_000.0
    dki_inside_roi_km2 = dki_inside_roi.area / 1_000_000.0

    component_path = output_dir / "v9_strict_connected_components.csv"
    coverage_path = output_dir / "v9_strict_municipality_coverage.csv"
    map_path = output_dir / "v9_strict_spatial_coverage.png"
    _write_csv(component_path, component_records)
    _write_csv(coverage_path, coverage_records)
    mainland_municipalities = municipalities[
        municipalities["municipality"].str.startswith("JAKARTA ")
    ].copy()
    _plot_map(map_path, strict, velocity, transform, mainland_municipalities)

    summary: dict[str, Any] = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scientific_status": "diagnostic_spatial_coverage_pending_sensitivity_and_external_validation",
        "inputs": {
            "strict_mask": strict_mask_path.name,
            "strict_mask_sha256": sha256_file(strict_mask_path),
            "strict_velocity": strict_velocity_path.name,
            "strict_velocity_sha256": sha256_file(strict_velocity_path),
        },
        "official_boundary": boundary_source,
        "method": {
            "raster_connectivity": 8,
            "administrative_intersection_crs": EQUAL_AREA_CRS,
            "administrative_area_method": "exact polygon intersection of strict raster cells",
            "quality_mask_resampled": False,
        },
        "strict_mask": {
            "pixels": int(strict.sum()),
            "area_km2_equal_area_projection": float(strict_area_km2),
            "area_inside_dki_km2": float(strict_inside_dki_km2),
            "fraction_of_strict_area_inside_dki": float(
                strict_inside_dki_km2 / strict_area_km2
            ),
            "dki_area_inside_raster_roi_km2": float(dki_inside_roi_km2),
            "fraction_of_dki_inside_roi_covered_by_strict_mask": float(
                strict_inside_dki_km2 / dki_inside_roi_km2
            ),
            "strict_pixels_whose_centres_fall_inside_dki": int(
                (strict & dki_center_mask).sum()
            ),
            "mainland_dki": {
                "definition": "five municipalities whose official name starts with JAKARTA; excludes the marine/island regency KAB.ADM.KEP.SERIBU",
                "area_inside_raster_roi_km2": float(
                    mainland_inside_roi.area / 1_000_000.0
                ),
                "strict_overlap_km2": float(
                    strict_inside_mainland.area / 1_000_000.0
                ),
                "strict_fraction_covered": float(
                    strict_inside_mainland.area / mainland_inside_roi.area
                ),
            },
        },
        "connected_components": {
            "count": len(component_records),
            "components_at_least_4_pixels": sum(
                item["pixels"] >= 4 for item in component_records
            ),
            "components_at_least_10_pixels": sum(
                item["pixels"] >= 10 for item in component_records
            ),
            "largest": component_records[0],
            "top_10": component_records[:10],
        },
        "municipality_coverage": coverage_records,
        "outputs": {
            "official_boundary": boundary_path.name,
            "connected_components": component_path.name,
            "municipality_coverage": coverage_path.name,
            "map": map_path.name,
        },
    }
    summary_path = output_dir / "v9_strict_spatial_coverage_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    summary["outputs"].update(
        {
            "connected_components_sha256": sha256_file(component_path),
            "municipality_coverage_sha256": sha256_file(coverage_path),
            "map_sha256": sha256_file(map_path),
            "summary": summary_path.name,
            "summary_sha256": sha256_file(summary_path),
        }
    )
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-mask", required=True, type=Path)
    parser.add_argument("--strict-velocity", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--boundary-url", default=OFFICIAL_BOUNDARY_SERVICE)
    return parser.parse_args()


def main() -> None:
    arguments = _parse_args()
    summary = run(
        strict_mask_path=arguments.strict_mask,
        strict_velocity_path=arguments.strict_velocity,
        output_dir=arguments.output_dir,
        boundary_url=arguments.boundary_url,
    )
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
