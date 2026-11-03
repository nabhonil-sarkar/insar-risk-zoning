"""Inventory and export annual AlphaEarth embeddings to an exact reference grid.

The default annual-change branch requests every calendar year from 2020 through
2025 and uses the authenticated local 2023 30 m raster as its grid contract.
Inventory-only mode never submits an export task. A missing requested year
prevents submission unless ``--allow-missing-years`` is explicit.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import rasterio

from config.settings import (
    EMBEDDING_COLLECTION_ID,
    EMBEDDING_REFERENCE_RASTER,
    EMBEDDING_YEARS,
    EXPORT_FOLDER,
)
from src.m2_embedding_extraction import EMBEDDING_BANDS


def _earth_engine_module():
    try:
        import ee
    except ImportError as exc:
        raise RuntimeError(
            "Earth Engine Python API is not installed. Install the project "
            "earth-engine optional dependencies before authenticating."
        ) from exc
    return ee


def reference_grid(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with rasterio.open(path) as dataset:
        if dataset.count != 64 or list(dataset.descriptions) != EMBEDDING_BANDS:
            raise ValueError("Reference raster must contain A00 through A63 in order")
        if dataset.crs is None:
            raise ValueError("Reference raster has no CRS")
        return {
            "path": path.as_posix(),
            "crs": dataset.crs.to_string(),
            "crs_transform": list(dataset.transform)[:6],
            "width": dataset.width,
            "height": dataset.height,
            "bounds": list(dataset.bounds),
            "band_names": list(dataset.descriptions),
        }


def _write_manifest(path: str | Path | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def main(
    years=None,
    folder=None,
    project=None,
    manifest_path=None,
    reference_raster=EMBEDDING_REFERENCE_RASTER,
    inventory_only=False,
    allow_missing_years=False,
):
    years = list(years if years is not None else EMBEDDING_YEARS)
    folder = folder if folder is not None else EXPORT_FOLDER
    grid = reference_grid(reference_raster)
    ee = _earth_engine_module()
    try:
        if project:
            ee.Initialize(project=project)
        else:
            ee.Initialize()
    except Exception as exc:
        raise RuntimeError(
            "Earth Engine initialization failed. Authenticate first and supply "
            "the approved Cloud project ID if the account requires one."
        ) from exc

    roi = ee.Geometry.Rectangle(grid["bounds"], proj=grid["crs"], geodesic=False)
    collection = ee.ImageCollection(EMBEDDING_COLLECTION_ID)
    inventory = []
    available = {}
    for year in years:
        annual = (
            collection.filterBounds(roi)
            .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
            .select(EMBEDDING_BANDS)
        )
        count = int(annual.size().getInfo())
        record = {"year": int(year), "tile_count": count, "available": count > 0}
        if count:
            observed_bands = annual.first().bandNames().getInfo()
            if observed_bands != EMBEDDING_BANDS:
                raise RuntimeError(f"Band order changed for {year}: {observed_bands}")
            record.update(
                {
                    "band_names": observed_bands,
                    "dataset_versions": annual.aggregate_array("DATASET_VERSION")
                    .distinct()
                    .getInfo(),
                    "model_versions": annual.aggregate_array("MODEL_VERSION")
                    .distinct()
                    .getInfo(),
                    "processing_software_versions": annual.aggregate_array(
                        "PROCESSING_SOFTWARE_VERSION"
                    )
                    .distinct()
                    .getInfo(),
                    "utm_zones": annual.aggregate_array("UTM_ZONE")
                    .distinct()
                    .getInfo(),
                }
            )
            available[year] = annual
        inventory.append(record)

    missing = [record["year"] for record in inventory if not record["available"]]
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "inventory_only" if inventory_only else "export_submission",
        "earth_engine_project": project,
        "collection": EMBEDDING_COLLECTION_ID,
        "requested_years": years,
        "missing_years": missing,
        "reference_grid": grid,
        "sampling_policy": (
            "Earth Engine default nearest-neighbour sampling onto the exact "
            "authenticated 2023 30 m grid; no independent annual normalization"
        ),
        "inventory": inventory,
        "exports": [],
    }
    if inventory_only:
        _write_manifest(manifest_path, manifest)
        return manifest
    if missing and not allow_missing_years:
        manifest["submission_blocked"] = (
            "Requested years are missing; rerun inventory later or explicitly "
            "authorize a partial available-year submission."
        )
        _write_manifest(manifest_path, manifest)
        raise RuntimeError(f"No tasks submitted; requested years unavailable: {missing}")

    for year in years:
        if year not in available:
            continue
        image = available[year].mosaic().clip(roi)
        description = f"AlphaEarth_Jakarta_Wide_30m_{year}"
        task = ee.batch.Export.image.toDrive(
            image=image,
            description=description,
            fileNamePrefix=description,
            folder=folder,
            region=roi.getInfo()["coordinates"],
            crs=grid["crs"],
            crsTransform=grid["crs_transform"],
            maxPixels=1e13,
            fileFormat="GeoTIFF",
            formatOptions={"cloudOptimized": True},
        )
        task.start()
        manifest["exports"].append(
            {
                "year": int(year),
                "description": description,
                "task_id": task.id,
                "folder": folder,
                "expected_width": grid["width"],
                "expected_height": grid["height"],
            }
        )
    _write_manifest(manifest_path, manifest)
    return manifest


def cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="+", type=int, default=EMBEDDING_YEARS)
    parser.add_argument("--folder", default=EXPORT_FOLDER)
    parser.add_argument(
        "--project",
        help="Earth Engine billing/project ID; otherwise use the authenticated default",
    )
    parser.add_argument(
        "--reference-raster", default=EMBEDDING_REFERENCE_RASTER
    )
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--allow-missing-years", action="store_true")
    parser.add_argument(
        "--manifest",
        default=os.path.join(
            "data", "output", "alphaearth_annual_change", "earth_engine_inventory.json"
        ),
    )
    args = parser.parse_args(argv)
    return main(
        years=args.years,
        folder=args.folder,
        project=args.project,
        manifest_path=args.manifest,
        reference_raster=args.reference_raster,
        inventory_only=args.inventory_only,
        allow_missing_years=args.allow_missing_years,
    )


if __name__ == "__main__":
    cli()
