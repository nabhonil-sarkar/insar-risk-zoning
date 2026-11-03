"""Build the preregistered strict pixel mask from the verified LiCSBAS v9 archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tarfile
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import Affine, array_bounds


EXPECTED_ARCHIVE_SHA256 = (
    "99f38ec03233f900a6c28ee629e279df8aed427e18c70c8101a9e4f094bbd23d"
)
RESULT_PREFIX = "TS_GEOCml5clip_reunw_mp/results/"
REQUIRED_LAYERS = ("vel", "vstd", "n_gap", "n_loop_err")
EARTH_MEAN_RADIUS_METRES = 6_371_008.8


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _validate_metadata(
    qc: dict[str, Any], manifest: dict[str, Any]
) -> tuple[int, int, Affine, str]:
    identity_fields = ("frame", "start", "end", "multilook", "run_tag", "run_role")
    for field in identity_fields:
        if qc.get(field) != manifest.get(field):
            raise ValueError(f"QC/manifest mismatch for {field}: {qc.get(field)!r} != {manifest.get(field)!r}")

    qc_gate = qc.get("network_survival_gate", {})
    manifest_gate = manifest.get("network_survival_gate", {})
    if qc_gate != manifest_gate or qc_gate.get("passed") is not True:
        raise ValueError("QC and manifest must contain the same passed v9 network gate")

    qc_layers = qc.get("layer_statistics", {})
    manifest_layers = manifest.get("layers", {})
    for layer in ("vel", "vstd"):
        if layer not in qc_layers or layer not in manifest_layers:
            raise ValueError(f"Missing {layer} metadata")
        if qc_layers[layer] != manifest_layers[layer]:
            raise ValueError(f"QC/manifest layer metadata mismatch for {layer}")

    shape = qc_layers["vel"].get("shape")
    if not isinstance(shape, list) or len(shape) != 2:
        raise ValueError("Velocity metadata has no valid two-dimensional shape")
    height, width = (int(shape[0]), int(shape[1]))

    transform_values = qc_layers["vel"].get("transform")
    if not isinstance(transform_values, list) or len(transform_values) < 6:
        raise ValueError("Velocity metadata has no valid affine transform")
    transform = Affine(*map(float, transform_values[:6]))
    crs = str(qc_layers["vel"].get("crs"))
    if crs != "EPSG:4326":
        raise ValueError(f"Expected EPSG:4326 v9 output, found {crs}")

    for layer, metadata in qc_layers.items():
        if metadata.get("shape") != shape:
            raise ValueError(f"Output-grid shape mismatch for {layer}")
        if metadata.get("transform") != transform_values or str(metadata.get("crs")) != crs:
            raise ValueError(f"Output-grid georeferencing mismatch for {layer}")
    return height, width, transform, crs


def _read_archive_layers(
    archive: Path, height: int, width: int
) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    expected_values = height * width
    with tarfile.open(archive, "r:gz") as bundle:
        members = {member.name: member for member in bundle.getmembers() if member.isfile()}
        for layer in REQUIRED_LAYERS:
            member_name = RESULT_PREFIX + layer
            if member_name not in members:
                raise ValueError(f"Verified archive is missing {member_name}")
            stream = bundle.extractfile(members[member_name])
            if stream is None:
                raise ValueError(f"Could not read {member_name}")
            values = np.frombuffer(stream.read(), dtype="<f4")
            if values.size != expected_values:
                raise ValueError(
                    f"Unexpected {layer} cell count: {values.size} != {expected_values}"
                )
            arrays[layer] = values.reshape(height, width).copy()
    return arrays


def build_strict_mask(arrays: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Return the joint finite mask and the preregistered strict mask."""
    joint_finite = np.isfinite(arrays["vel"]) & np.isfinite(arrays["vstd"])
    quality_counts_finite = np.isfinite(arrays["n_gap"]) & np.isfinite(arrays["n_loop_err"])
    strict = (
        joint_finite
        & quality_counts_finite
        & (arrays["n_gap"] == 0)
        & (arrays["n_loop_err"] == 0)
    )
    return joint_finite, strict


def _approximate_area_km2(mask: np.ndarray, transform: Affine) -> float:
    if not math.isclose(transform.b, 0.0, abs_tol=1e-12) or not math.isclose(
        transform.d, 0.0, abs_tol=1e-12
    ):
        raise ValueError("Area calculation requires a north-up geographic grid")
    longitude_width = abs(transform.a) * math.pi / 180.0
    total_square_metres = 0.0
    for row, selected in enumerate(mask.sum(axis=1)):
        if selected == 0:
            continue
        latitude_top = transform.f + row * transform.e
        latitude_bottom = latitude_top + transform.e
        strip_cell_area = (
            EARTH_MEAN_RADIUS_METRES**2
            * longitude_width
            * abs(
                math.sin(math.radians(latitude_top))
                - math.sin(math.radians(latitude_bottom))
            )
        )
        total_square_metres += int(selected) * strip_cell_area
    return total_square_metres / 1_000_000.0


def _write_rasters(
    output_dir: Path,
    strict: np.ndarray,
    velocity: np.ndarray,
    transform: Affine,
    crs: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    mask_path = output_dir / "v9_strict_quality_mask.tif"
    velocity_path = output_dir / "v9_velocity_strict_masked_mmyr.tif"

    mask_profile = {
        "driver": "GTiff",
        "height": strict.shape[0],
        "width": strict.shape[1],
        "count": 1,
        "dtype": "uint8",
        "crs": crs,
        "transform": transform,
        "compress": "deflate",
        "predictor": 1,
    }
    with rasterio.open(mask_path, "w", **mask_profile) as destination:
        destination.write(strict.astype("uint8"), 1)
        destination.set_band_description(1, "strict_quality_mask_1_pass_0_fail")
        destination.update_tags(
            criteria="finite(vel,vstd) AND n_gap=0 AND n_loop_err=0",
            scientific_status="diagnostic_candidate_mask_pending_spatial_and_external_validation",
        )

    strict_velocity = np.where(strict, velocity, np.nan).astype("float32")
    velocity_profile = mask_profile | {
        "dtype": "float32",
        "nodata": np.nan,
        "predictor": 3,
    }
    with rasterio.open(velocity_path, "w", **velocity_profile) as destination:
        destination.write(strict_velocity, 1)
        destination.set_band_description(1, "strict_masked_line_of_sight_velocity_mm_per_year")
        destination.update_tags(
            units="mm/year",
            direction="Sentinel-1 line_of_sight_relative_velocity",
            criteria="finite(vel,vstd) AND n_gap=0 AND n_loop_err=0",
            scientific_status="diagnostic_candidate_pending_spatial_and_external_validation",
        )
    return mask_path, velocity_path


def run(
    archive: Path,
    qc_summary: Path,
    manifest_path: Path,
    output_dir: Path,
    expected_archive_sha256: str = EXPECTED_ARCHIVE_SHA256,
) -> dict[str, Any]:
    inputs = (archive, qc_summary, manifest_path)
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)

    archive_sha = sha256_file(archive)
    if archive_sha != expected_archive_sha256.lower():
        raise ValueError(
            f"Results-archive SHA-256 mismatch: {archive_sha} != {expected_archive_sha256}"
        )
    qc = _read_json(qc_summary)
    manifest = _read_json(manifest_path)
    height, width, transform, crs = _validate_metadata(qc, manifest)
    arrays = _read_archive_layers(archive, height, width)

    expected_velocity = qc["layer_statistics"]["vel"]
    finite_velocity = arrays["vel"][np.isfinite(arrays["vel"])]
    observed_velocity = {
        "finite_fraction": float(finite_velocity.size / arrays["vel"].size),
        "min": float(finite_velocity.min()),
        "median": float(np.median(finite_velocity)),
        "max": float(finite_velocity.max()),
    }
    for statistic, value in observed_velocity.items():
        if not math.isclose(value, float(expected_velocity[statistic]), rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError(
                f"Archive velocity {statistic} does not match QC summary: "
                f"{value} != {expected_velocity[statistic]}"
            )

    joint_finite, strict = build_strict_mask(arrays)
    strict_count = int(strict.sum())
    joint_count = int(joint_finite.sum())
    if strict_count == 0:
        raise ValueError("The strict quality mask is empty")

    mask_path, velocity_path = _write_rasters(
        output_dir, strict, arrays["vel"], transform, crs
    )
    strict_velocity = arrays["vel"][strict]
    strict_vstd = arrays["vstd"][strict]
    west, south, east, north = array_bounds(height, width, transform)
    summary: dict[str, Any] = {
        "scientific_status": "diagnostic_candidate_mask_pending_spatial_and_external_validation",
        "source": {
            "archive": archive.name,
            "archive_sha256": archive_sha,
            "qc_summary": qc_summary.name,
            "qc_summary_sha256": sha256_file(qc_summary),
            "manifest": manifest_path.name,
            "manifest_sha256": sha256_file(manifest_path),
        },
        "criteria": [
            "velocity is finite",
            "velocity uncertainty is finite",
            "n_gap equals 0",
            "n_loop_err equals 0",
        ],
        "grid": {
            "shape": [height, width],
            "total_pixels": height * width,
            "crs": crs,
            "transform": list(transform),
            "bounds_wsen": [west, south, east, north],
        },
        "counts": {
            "joint_finite_velocity_vstd": joint_count,
            "joint_finite_fraction": joint_count / strict.size,
            "joint_finite_with_n_gap_zero": int(
                (joint_finite & np.isfinite(arrays["n_gap"]) & (arrays["n_gap"] == 0)).sum()
            ),
            "joint_finite_with_n_loop_err_zero": int(
                (
                    joint_finite
                    & np.isfinite(arrays["n_loop_err"])
                    & (arrays["n_loop_err"] == 0)
                ).sum()
            ),
            "strict_pixels": strict_count,
            "strict_fraction_of_grid": strict_count / strict.size,
            "strict_fraction_of_joint_finite": strict_count / joint_count,
        },
        "strict_mask_statistics": {
            "approximate_area_km2_spherical_wgs84_grid": _approximate_area_km2(
                strict, transform
            ),
            "velocity_mmyr": {
                "min": float(strict_velocity.min()),
                "median": float(np.median(strict_velocity)),
                "max": float(strict_velocity.max()),
            },
            "vstd_mmyr": {
                "min": float(strict_vstd.min()),
                "median": float(np.median(strict_vstd)),
                "max": float(strict_vstd.max()),
            },
        },
        "outputs": {
            "strict_quality_mask": mask_path.name,
            "strict_quality_mask_sha256": sha256_file(mask_path),
            "strict_masked_velocity": velocity_path.name,
            "strict_masked_velocity_sha256": sha256_file(velocity_path),
        },
    }
    summary_path = output_dir / "v9_strict_mask_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    summary["outputs"]["summary"] = summary_path.name
    summary["outputs"]["summary_sha256"] = sha256_file(summary_path)
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--qc-summary", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--expected-archive-sha256",
        default=EXPECTED_ARCHIVE_SHA256,
        help="Refuse any archive whose SHA-256 differs from this value",
    )
    return parser.parse_args()


def main() -> None:
    arguments = _parse_args()
    summary = run(
        archive=arguments.archive,
        qc_summary=arguments.qc_summary,
        manifest_path=arguments.manifest,
        output_dir=arguments.output_dir,
        expected_archive_sha256=arguments.expected_archive_sha256,
    )
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
