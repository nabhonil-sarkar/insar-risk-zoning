"""Diagnose why no v9 strict-mask pixels survive in North Jakarta."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import tarfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib
import numpy as np
import rasterio
from matplotlib.patches import Patch
from rasterio.features import rasterize

from scripts.build_v9_strict_mask import EXPECTED_ARCHIVE_SHA256

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


RESULT_PREFIX = "TS_GEOCml5clip_reunw_mp/results/"
LAYERS = ("vel", "vstd", "n_gap", "n_loop_err", "coh_avg", "n_unw", "n_ifg_noloop")
NORTH_NAME = "JAKARTA UTARA"

CATEGORY_OUTSIDE = 0
CATEGORY_MISSING_OUTPUT = 1
CATEGORY_GAP_ONLY = 2
CATEGORY_LOOP_ONLY = 3
CATEGORY_GAP_AND_LOOP = 4
CATEGORY_STRICT_PASS = 5
CATEGORY_INVALID_QUALITY_COUNTS = 6
CATEGORY_LABELS = {
    CATEGORY_MISSING_OUTPUT: "missing_velocity_or_uncertainty",
    CATEGORY_GAP_ONLY: "temporal_gap_only",
    CATEGORY_LOOP_ONLY: "loop_error_only",
    CATEGORY_GAP_AND_LOOP: "temporal_gap_and_loop_error",
    CATEGORY_STRICT_PASS: "strict_pass",
    CATEGORY_INVALID_QUALITY_COUNTS: "invalid_gap_or_loop_count",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_failure(
    inside: np.ndarray,
    velocity: np.ndarray,
    vstd: np.ndarray,
    n_gap: np.ndarray,
    n_loop_err: np.ndarray,
) -> np.ndarray:
    """Return mutually exclusive quality-state codes for pixels inside a boundary."""
    categories = np.full(inside.shape, CATEGORY_OUTSIDE, dtype="uint8")
    joint_finite = np.isfinite(velocity) & np.isfinite(vstd)
    quality_finite = np.isfinite(n_gap) & np.isfinite(n_loop_err)
    categories[inside & ~joint_finite] = CATEGORY_MISSING_OUTPUT
    categories[inside & joint_finite & ~quality_finite] = CATEGORY_INVALID_QUALITY_COUNTS
    eligible = inside & joint_finite & quality_finite
    gap = n_gap > 0
    loop = n_loop_err > 0
    categories[eligible & gap & ~loop] = CATEGORY_GAP_ONLY
    categories[eligible & ~gap & loop] = CATEGORY_LOOP_ONLY
    categories[eligible & gap & loop] = CATEGORY_GAP_AND_LOOP
    categories[eligible & ~gap & ~loop] = CATEGORY_STRICT_PASS
    return categories


def _read_layers(
    archive: Path, height: int, width: int
) -> dict[str, np.ndarray]:
    expected_values = height * width
    result: dict[str, np.ndarray] = {}
    with tarfile.open(archive, "r:gz") as bundle:
        members = {member.name: member for member in bundle.getmembers() if member.isfile()}
        for layer in LAYERS:
            member_name = RESULT_PREFIX + layer
            member = members.get(member_name)
            if member is None:
                raise ValueError(f"Archive is missing {member_name}")
            stream = bundle.extractfile(member)
            if stream is None:
                raise ValueError(f"Could not read {member_name}")
            values = np.frombuffer(stream.read(), dtype="<f4")
            if values.size != expected_values:
                raise ValueError(f"Unexpected {layer} size: {values.size} != {expected_values}")
            result[layer] = values.reshape(height, width).copy()
    return result


def _finite_statistics(values: np.ndarray) -> dict[str, float | int | None]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {"finite_count": 0, "min": None, "median": None, "max": None}
    return {
        "finite_count": int(finite.size),
        "min": float(finite.min()),
        "median": float(np.median(finite)),
        "max": float(finite.max()),
    }


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        raise ValueError(f"No records to write: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def _boundary_mask(
    geometry: Any, shape_value: tuple[int, int], transform: rasterio.Affine
) -> np.ndarray:
    return rasterize(
        [(geometry, 1)],
        out_shape=shape_value,
        transform=transform,
        fill=0,
        all_touched=False,
        dtype="uint8",
    ).astype(bool)


def _summarize_region(
    name: str,
    inside: np.ndarray,
    arrays: dict[str, np.ndarray],
) -> dict[str, Any]:
    categories = classify_failure(
        inside,
        arrays["vel"],
        arrays["vstd"],
        arrays["n_gap"],
        arrays["n_loop_err"],
    )
    total = int(inside.sum())
    category_counts = {
        CATEGORY_LABELS[code]: int((categories == code).sum())
        for code in CATEGORY_LABELS
    }
    return {
        "region": name,
        "pixel_centres_inside": total,
        **category_counts,
        "strict_fraction": category_counts["strict_pass"] / total if total else 0.0,
        "coherence": _finite_statistics(arrays["coh_avg"][inside]),
        "usable_interferograms": _finite_statistics(arrays["n_unw"][inside]),
        "n_gap": _finite_statistics(arrays["n_gap"][inside]),
        "n_loop_err": _finite_statistics(arrays["n_loop_err"][inside]),
        "n_ifg_noloop": _finite_statistics(arrays["n_ifg_noloop"][inside]),
    }


def _plot_north_diagnostic(
    path: Path,
    categories: np.ndarray,
    arrays: dict[str, np.ndarray],
    transform: rasterio.Affine,
    north_districts: gpd.GeoDataFrame,
) -> None:
    west, south, east, north = north_districts.total_bounds
    longitude_padding = 0.015
    latitude_padding = 0.015
    row_start, col_start = rasterio.transform.rowcol(
        transform, west - longitude_padding, north + latitude_padding
    )
    row_stop, col_stop = rasterio.transform.rowcol(
        transform, east + longitude_padding, south - latitude_padding
    )
    row_start = max(0, int(row_start))
    col_start = max(0, int(col_start))
    row_stop = min(categories.shape[0], int(row_stop) + 1)
    col_stop = min(categories.shape[1], int(col_stop) + 1)
    crop_transform = transform * rasterio.Affine.translation(col_start, row_start)
    crop_bounds = rasterio.transform.array_bounds(
        row_stop - row_start, col_stop - col_start, crop_transform
    )

    category_colours = [
        "#bdbdbd",
        "#fdae61",
        "#d7191c",
        "#7b3294",
        "#1a9641",
        "#636363",
    ]
    category_codes = list(CATEGORY_LABELS)
    figure, axes = plt.subplots(1, 2, figsize=(13.2, 6.2), constrained_layout=True)
    north_districts.plot(ax=axes[0], color="#f4f4f4", edgecolor="none", zorder=1)
    for index, code in enumerate(category_codes):
        rows, columns = np.where(categories == code)
        longitudes = transform.c + (columns + 0.5) * transform.a
        latitudes = transform.f + (rows + 0.5) * transform.e
        axes[0].scatter(
            longitudes,
            latitudes,
            marker="s",
            s=28,
            c=category_colours[index],
            linewidths=0,
            zorder=2,
        )
    north_districts.boundary.plot(ax=axes[0], color="#202020", linewidth=0.9, zorder=3)
    axes[0].set_title("Mutually exclusive strict-mask outcome")
    legend = [
        Patch(facecolor=category_colours[index], label=CATEGORY_LABELS[code].replace("_", " "))
        for index, code in enumerate(category_codes)
    ]
    axes[0].legend(handles=legend, loc="lower left", fontsize=8, framealpha=0.9)

    north_districts.plot(ax=axes[1], color="#f4f4f4", edgecolor="none", zorder=1)
    inside = categories != CATEGORY_OUTSIDE
    missing = categories == CATEGORY_MISSING_OUTPUT
    missing_rows, missing_columns = np.where(missing)
    axes[1].scatter(
        transform.c + (missing_columns + 0.5) * transform.a,
        transform.f + (missing_rows + 0.5) * transform.e,
        marker="s",
        s=28,
        c="#bdbdbd",
        linewidths=0,
        zorder=2,
    )
    loop_selected = inside & np.isfinite(arrays["n_loop_err"]) & ~missing
    loop_rows, loop_columns = np.where(loop_selected)
    loop_values = arrays["n_loop_err"][loop_selected]
    loop_image = axes[1].scatter(
        transform.c + (loop_columns + 0.5) * transform.a,
        transform.f + (loop_rows + 0.5) * transform.e,
        marker="s",
        s=28,
        c=loop_values,
        cmap="magma",
        vmin=0,
        vmax=float(np.nanpercentile(loop_values, 95)),
        linewidths=0,
        zorder=2,
    )
    north_districts.boundary.plot(ax=axes[1], color="#f2f2f2", linewidth=0.9, zorder=3)
    axes[1].set_title("Residual loop-error count (95th-percentile scale)")
    colorbar = figure.colorbar(loop_image, ax=axes[1], shrink=0.82, pad=0.02)
    colorbar.set_label("n_loop_err")

    for axis in axes:
        axis.set_xlim(crop_bounds[0], crop_bounds[2])
        axis.set_ylim(crop_bounds[1], crop_bounds[3])
        axis.set_xlabel("Longitude (degrees east)")
        axis.set_ylabel("Latitude (degrees north)")
        axis.grid(color="#777777", linewidth=0.3, alpha=0.3)
        for _, district in north_districts.iterrows():
            point = district.geometry.representative_point()
            axis.text(
                point.x,
                point.y,
                str(district["district"]).title(),
                fontsize=7,
                ha="center",
                va="center",
                color="#111111" if axis is axes[0] else "#ffffff",
                bbox={"facecolor": "white" if axis is axes[0] else "black", "edgecolor": "none", "alpha": 0.62, "pad": 1},
                zorder=4,
            )
    figure.suptitle("Why North Jakarta has no v9 strict-mask coverage")
    figure.text(
        0.01,
        0.005,
        "Pixel-centre classification; strict criteria unchanged. Official DKI Jakarta district boundaries. Diagnostic only.",
        fontsize=8,
        color="#333333",
    )
    figure.savefig(path, dpi=180, facecolor="white")
    plt.close(figure)


def run(
    archive_path: Path,
    qc_summary_path: Path,
    official_boundary_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    for path in (archive_path, qc_summary_path, official_boundary_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    archive_sha = sha256_file(archive_path)
    if archive_sha != EXPECTED_ARCHIVE_SHA256:
        raise ValueError(
            f"Results-archive SHA-256 mismatch: {archive_sha} != {EXPECTED_ARCHIVE_SHA256}"
        )
    qc = json.loads(qc_summary_path.read_text(encoding="utf-8"))
    layer_metadata = qc["layer_statistics"]["vel"]
    height, width = map(int, layer_metadata["shape"])
    transform = rasterio.Affine(*map(float, layer_metadata["transform"][:6]))
    if layer_metadata["crs"] != "EPSG:4326":
        raise ValueError(f"Expected EPSG:4326, found {layer_metadata['crs']}")
    arrays = _read_layers(archive_path, height, width)

    boundary_json = json.loads(official_boundary_path.read_text(encoding="utf-8"))
    kelurahan = gpd.GeoDataFrame.from_features(boundary_json["features"], crs="EPSG:4326")
    for field in ("wadmkk", "wadmkc", "wadmkd"):
        kelurahan[field] = kelurahan[field].astype(str).str.strip()
    kelurahan.geometry = kelurahan.geometry.make_valid()

    municipalities = kelurahan[["wadmkk", "geometry"]].dissolve(by="wadmkk").reset_index()
    municipality_records: list[dict[str, Any]] = []
    for _, municipality in municipalities.iterrows():
        if not str(municipality["wadmkk"]).startswith("JAKARTA "):
            continue
        inside = _boundary_mask(municipality.geometry, (height, width), transform)
        municipality_records.append(
            _summarize_region(municipality["wadmkk"], inside, arrays)
        )
    municipality_records.sort(key=lambda record: record["region"])

    north_kelurahan = kelurahan[kelurahan["wadmkk"] == NORTH_NAME].copy()
    if north_kelurahan.empty:
        raise ValueError("Official boundary contains no North Jakarta features")
    north_geometry = north_kelurahan.geometry.union_all()
    north_inside = _boundary_mask(north_geometry, (height, width), transform)
    north_categories = classify_failure(
        north_inside,
        arrays["vel"],
        arrays["vstd"],
        arrays["n_gap"],
        arrays["n_loop_err"],
    )
    north_summary = _summarize_region(NORTH_NAME, north_inside, arrays)

    north_districts = (
        north_kelurahan[["wadmkc", "geometry"]]
        .dissolve(by="wadmkc")
        .reset_index()
        .rename(columns={"wadmkc": "district"})
    )
    district_records: list[dict[str, Any]] = []
    for _, district in north_districts.iterrows():
        inside = _boundary_mask(district.geometry, (height, width), transform)
        district_records.append(_summarize_region(district["district"], inside, arrays))
    district_records.sort(key=lambda record: record["region"])

    class_records: list[dict[str, Any]] = []
    for code, label in CATEGORY_LABELS.items():
        selected = north_categories == code
        class_records.append(
            {
                "category": label,
                "pixels": int(selected.sum()),
                "fraction_of_north_pixel_centres": float(selected.sum() / north_inside.sum()),
                "coherence_finite_count": _finite_statistics(arrays["coh_avg"][selected])["finite_count"],
                "coherence_median": _finite_statistics(arrays["coh_avg"][selected])["median"],
                "n_unw_median": _finite_statistics(arrays["n_unw"][selected])["median"],
                "n_gap_median": _finite_statistics(arrays["n_gap"][selected])["median"],
                "n_loop_err_median": _finite_statistics(arrays["n_loop_err"][selected])["median"],
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    class_path = output_dir / "v9_north_failure_classes.csv"
    district_path = output_dir / "v9_north_failure_by_district.csv"
    municipality_path = output_dir / "v9_failure_by_municipality.csv"
    map_path = output_dir / "v9_north_failure_diagnostic.png"
    _write_csv(class_path, class_records)
    _write_csv(district_path, district_records)
    _write_csv(municipality_path, municipality_records)
    _plot_north_diagnostic(
        map_path, north_categories, arrays, transform, north_districts
    )

    summary: dict[str, Any] = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scientific_status": "diagnostic_north_jakarta_failure_audit",
        "source": {
            "archive": archive_path.name,
            "archive_sha256": archive_sha,
            "qc_summary": qc_summary_path.name,
            "qc_summary_sha256": sha256_file(qc_summary_path),
            "official_boundary": official_boundary_path.name,
            "official_boundary_sha256": sha256_file(official_boundary_path),
        },
        "method": {
            "boundary_assignment": "pixel centre inside official polygon",
            "categories_are_mutually_exclusive": True,
            "strict_criteria_changed": False,
            "strict_criteria": "finite velocity and vstd; n_gap=0; n_loop_err=0",
        },
        "north_jakarta": north_summary,
        "failure_classes": class_records,
        "districts": district_records,
        "mainland_municipality_comparison": municipality_records,
        "outputs": {
            "failure_classes": class_path.name,
            "failure_classes_sha256": sha256_file(class_path),
            "districts": district_path.name,
            "districts_sha256": sha256_file(district_path),
            "municipalities": municipality_path.name,
            "municipalities_sha256": sha256_file(municipality_path),
            "map": map_path.name,
            "map_sha256": sha256_file(map_path),
        },
    }
    summary_path = output_dir / "v9_north_failure_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    summary["outputs"].update(
        {"summary": summary_path.name, "summary_sha256": sha256_file(summary_path)}
    )
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--qc-summary", required=True, type=Path)
    parser.add_argument("--official-boundary", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    arguments = _parse_args()
    summary = run(
        archive_path=arguments.archive,
        qc_summary_path=arguments.qc_summary,
        official_boundary_path=arguments.official_boundary,
        output_dir=arguments.output_dir,
    )
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
