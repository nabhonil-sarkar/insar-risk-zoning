"""Freeze and locally audit the 2020-2025 AlphaEarth annual-change contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

import rasterio

from config.settings import (
    EMBEDDING_COLLECTION_ID,
    EMBEDDING_REFERENCE_RASTER,
    EMBEDDING_REFERENCE_YEAR,
    EMBEDDING_YEARS,
    RAW_EMBEDDINGS_DIR,
)
from src.m2_embedding_extraction import EMBEDDING_BANDS


OFFICIAL_CATALOG_URL = (
    "https://developers.google.com/earth-engine/datasets/catalog/"
    "GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL"
)
EXPECTED_REFERENCE_SHA256 = (
    "19a8f04bdb71e9be0cd7dd9a2a033e513dea69f6860541ef2c2ab5315be472c7"
)
DEFAULT_OUTPUT = Path(
    "data/output/alphaearth_annual_change/alphaearth_annual_change_contract.json"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _reference_grid(path: Path, expected_sha256: str | None) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    observed_sha256 = sha256_file(path)
    if expected_sha256 and observed_sha256 != expected_sha256.lower():
        raise ValueError(f"Reference raster SHA-256 mismatch: {observed_sha256}")
    with rasterio.open(path) as dataset:
        descriptions = list(dataset.descriptions)
        if dataset.count != 64:
            raise ValueError(f"Expected 64 reference bands, found {dataset.count}")
        if descriptions != EMBEDDING_BANDS:
            raise ValueError(
                "Reference band order must be exactly A00 through A63"
            )
        if dataset.crs is None:
            raise ValueError("Reference raster has no CRS")
        transform = list(dataset.transform)[:6]
        return {
            "path": _portable_path(path),
            "sha256": observed_sha256,
            "bytes": path.stat().st_size,
            "driver": dataset.driver,
            "width": dataset.width,
            "height": dataset.height,
            "band_count": dataset.count,
            "band_names": descriptions,
            "dtype": dataset.dtypes[0],
            "crs": dataset.crs.to_string(),
            "transform": transform,
            "bounds": list(dataset.bounds),
            "nodata": dataset.nodata,
            "block_shapes": [list(value) for value in dataset.block_shapes],
            "compression": (
                dataset.compression.value if dataset.compression else None
            ),
        }


def _filename(year: int) -> str:
    return f"AlphaEarth_Jakarta_Wide_30m_{year}.tif"


def build_contract(
    reference_path: Path,
    input_dir: Path,
    output_path: Path,
    years: Iterable[int] = EMBEDDING_YEARS,
    catalog_latest_year: int = 2024,
    verified_on: str = "2026-08-10",
    expected_reference_sha256: str | None = EXPECTED_REFERENCE_SHA256,
) -> dict[str, Any]:
    years = [int(year) for year in years]
    if not years or years != list(range(min(years), max(years) + 1)):
        raise ValueError("Annual-change years must be one contiguous sequence")
    if EMBEDDING_REFERENCE_YEAR not in years:
        raise ValueError("The reference year must be included")
    reference = _reference_grid(reference_path, expected_reference_sha256)

    inventory = []
    for year in years:
        path = input_dir / _filename(year)
        inventory.append(
            {
                "year": year,
                "expected_path": _portable_path(path),
                "present": path.is_file(),
                "bytes": path.stat().st_size if path.is_file() else None,
                "sha256": sha256_file(path) if path.is_file() else None,
                "catalog_status": (
                    "available" if year <= catalog_latest_year else "not_yet_listed"
                ),
            }
        )

    adjacent = [
        {"start_year": year, "end_year": year + 1}
        for year in years[:-1]
    ]
    cumulative = [
        {"start_year": years[0], "end_year": EMBEDDING_REFERENCE_YEAR},
        {"start_year": years[0], "end_year": years[-1]},
    ]
    missing_local = [item["year"] for item in inventory if not item["present"]]
    not_listed = [
        item["year"]
        for item in inventory
        if item["catalog_status"] == "not_yet_listed"
    ]
    estimated_total_bytes = reference["bytes"] * len(years)
    payload = {
        "schema_version": 1,
        "experiment": "alphaearth_jakarta_annual_change_2020_2025",
        "scientific_role": "citywide_land_surface_context_not_deformation",
        "approval_scope": "all_calendar_years_2020_through_2025",
        "desired_years": years,
        "official_catalog": {
            "collection": EMBEDDING_COLLECTION_ID,
            "url": OFFICIAL_CATALOG_URL,
            "verified_on": verified_on,
            "latest_calendar_year_listed": catalog_latest_year,
            "requested_years_not_yet_listed": not_listed,
            "bands": EMBEDDING_BANDS,
            "native_pixel_size_m": 10,
            "licence": "CC-BY-4.0",
            "required_attribution": (
                "The AlphaEarth Foundations Satellite Embedding dataset is "
                "produced by Google and Google DeepMind."
            ),
        },
        "reference_year": EMBEDDING_REFERENCE_YEAR,
        "frozen_reference_grid": reference,
        "local_inventory": inventory,
        "missing_local_years": missing_local,
        "planned_comparisons": {
            "adjacent_year": adjacent,
            "cumulative": cumulative,
        },
        "export_contract": {
            "destination_pattern": _filename("{year}"),
            "crs": reference["crs"],
            "crs_transform": reference["transform"],
            "width": reference["width"],
            "height": reference["height"],
            "bounds": reference["bounds"],
            "band_order": EMBEDDING_BANDS,
            "grid_rule": (
                "Every downloaded annual raster must exactly match the 2023 "
                "reference CRS, transform, dimensions, bounds, and band order."
            ),
            "normalization_rule": (
                "Do not independently z-score or min-max scale annual layers. "
                "Cosine change uses each pixel vector direction and joint support."
            ),
        },
        "analysis_rules": [
            "Use all available annual layers; never interpolate or extrapolate a missing year.",
            "Compute adjacent-year changes before interpreting cumulative endpoints.",
            "Mask a comparison unless both annual vectors are finite and non-zero.",
            "Use all 64 axes together; individual axes have no physical interpretation.",
            "Keep 2020-2023 and post-2023 changes distinguishable from one another.",
            "Test cluster matching and change-score sensitivity before assigning labels.",
            "Require an ablation against ordinary predictors before claiming added value.",
            "Do not describe embedding change as deformation, subsidence, hazard, or risk.",
        ],
        "storage_planning": {
            "reference_file_bytes": reference["bytes"],
            "linear_six_year_estimate_bytes": estimated_total_bytes,
            "note": (
                "Estimate scales the existing compressed 30 m file and is not an "
                "export-size guarantee. Intermediate products require additional space."
            ),
        },
        "preflight": {
            "ready_for_complete_2020_2025_analysis": not missing_local,
            "remote_export_requires_earth_engine_authentication": True,
            "earth_engine_credentials_found_locally": (
                Path.home() / ".config/earthengine/credentials"
            ).is_file(),
            "earthengine_api_installed_locally": False,
            "blocking_conditions": [
                *(
                    ["2025 is not yet listed in the official catalogue"]
                    if 2025 in not_listed
                    else []
                ),
                *(
                    ["Earth Engine credentials are not configured locally"]
                    if not (Path.home() / ".config/earthengine/credentials").is_file()
                    else []
                ),
                *(
                    [f"Local annual rasters are missing: {missing_local}"]
                    if missing_local
                    else []
                ),
            ],
        },
    }
    try:
        import ee  # noqa: F401
    except ImportError:
        pass
    else:
        payload["preflight"]["earthengine_api_installed_locally"] = True
        payload["preflight"]["blocking_conditions"] = [
            condition
            for condition in payload["preflight"]["blocking_conditions"]
            if condition != "Earth Engine Python API is not installed locally"
        ]
    if not payload["preflight"]["earthengine_api_installed_locally"]:
        payload["preflight"]["blocking_conditions"].insert(
            1, "Earth Engine Python API is not installed locally"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output_path)
    return payload


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=Path(EMBEDDING_REFERENCE_RASTER))
    parser.add_argument("--input-dir", type=Path, default=Path(RAW_EMBEDDINGS_DIR))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--catalog-latest-year", type=int, default=2024)
    args = parser.parse_args()
    payload = build_contract(
        args.reference,
        args.input_dir,
        args.output,
        catalog_latest_year=args.catalog_latest_year,
    )
    print(json.dumps(payload["preflight"], indent=2))


if __name__ == "__main__":
    cli()
