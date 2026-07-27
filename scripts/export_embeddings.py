"""
Export AlphaEarth Satellite Embeddings from Google Earth Engine to Google Drive.

Run this script standalone — it kicks off async export tasks on GEE's servers.
After completion, download the GeoTIFFs from Drive into data/raw/embeddings/.

Usage:
    python scripts/export_embeddings.py

Prerequisites:
    - Earth Engine account: https://earthengine.google.com
    - Run `earthengine authenticate` once from your terminal
"""

import ee
import sys
import os
import argparse
import json
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import (
    ACTIVE_ROI, EMBEDDING_COLLECTION_ID, EMBEDDING_YEARS,
    EXPORT_FOLDER, EXPORT_SCALE, EXPORT_CRS,
)


def main(years=None, roi_bounds=None, scale=None, crs=None, folder=None,
         project=None, manifest_path=None):
    years = list(years if years is not None else EMBEDDING_YEARS)
    roi_bounds = list(roi_bounds if roi_bounds is not None else ACTIVE_ROI)
    scale = scale if scale is not None else EXPORT_SCALE
    crs = crs if crs is not None else EXPORT_CRS
    folder = folder if folder is not None else EXPORT_FOLDER

    # Initialize Earth Engine
    try:
        if project:
            ee.Initialize(project=project)
        else:
            ee.Initialize()
        print("Earth Engine initialized successfully.")
    except Exception as e:
        print(f"Earth Engine init failed: {e}")
        print("Run `earthengine authenticate` in your terminal first.")
        sys.exit(1)

    # Define ROI
    roi = ee.Geometry.Rectangle(roi_bounds)
    print(f"ROI: {roi_bounds}")

    # Access the embedding collection
    collection = ee.ImageCollection(EMBEDDING_COLLECTION_ID)
    print(f"Collection: {EMBEDDING_COLLECTION_ID}")

    # Export each year
    records = []
    for year in years:
        print(f"\nProcessing year {year}...")

        # Filter to the target year
        embeddings = (collection
                      .filterBounds(roi)
                      .filterDate(f"{year}-01-01", f"{year + 1}-01-01"))

        # Check how many tiles cover our ROI
        count = embeddings.size().getInfo()
        print(f"  Found {count} tile(s) covering ROI")

        if count == 0:
            print(f"  WARNING: No embeddings found for {year}. Skipping.")
            continue

        # Mosaic tiles and clip to ROI
        mosaic = embeddings.mosaic().clip(roi)

        # Verify band count
        bands = mosaic.bandNames().getInfo()
        print(f"  Bands: {len(bands)} ({bands[0]}...{bands[-1]})")

        # Set up export
        description = f"AlphaEarth_Jakarta_{year}"
        task = ee.batch.Export.image.toDrive(
            image=mosaic,
            description=description,
            folder=folder,
            region=roi.getInfo()["coordinates"],
            scale=scale,
            crs=crs,
            maxPixels=1e13,
            fileFormat="GeoTIFF",
        )
        task.start()
        print(f"  Export task started: '{description}'")
        print(f"  Destination: Google Drive/{folder}/")
        records.append({
            "year": int(year),
            "description": description,
            "task_id": task.id,
            "collection": EMBEDDING_COLLECTION_ID,
            "roi": roi_bounds,
            "scale": scale,
            "crs": crs,
            "folder": folder,
            "band_count": len(bands),
            "tile_count": int(count),
        })

    if manifest_path:
        manifest = {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "earth_engine_project": project,
            "exports": records,
        }
        os.makedirs(
            os.path.dirname(os.path.abspath(manifest_path)), exist_ok=True
        )
        temp_path = manifest_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, allow_nan=False)
        os.replace(temp_path, manifest_path)
        print(f"Export request manifest: {os.path.abspath(manifest_path)}")

    print("\n" + "=" * 50)
    print("All export tasks submitted.")
    print("Monitor progress at: https://code.earthengine.google.com/tasks")
    print(f"When complete, download files to: data/raw/embeddings/")
    print("=" * 50)
    return records


def cli(argv=None):
    parser = argparse.ArgumentParser(
        description="Submit versioned AlphaEarth exports to Google Drive"
    )
    parser.add_argument(
        "--years", nargs="+", type=int, default=EMBEDDING_YEARS
    )
    parser.add_argument(
        "--roi", nargs=4, type=float, metavar=("MIN_LON", "MIN_LAT",
                                               "MAX_LON", "MAX_LAT"),
        default=ACTIVE_ROI,
    )
    parser.add_argument("--scale", type=float, default=EXPORT_SCALE)
    parser.add_argument("--crs", default=EXPORT_CRS)
    parser.add_argument("--folder", default=EXPORT_FOLDER)
    parser.add_argument(
        "--project",
        help="Earth Engine billing/project ID; otherwise use the authenticated default",
    )
    parser.add_argument(
        "--manifest",
        default=os.path.join("data", "output", "embedding_export_request.json"),
    )
    args = parser.parse_args(argv)
    return main(
        years=args.years,
        roi_bounds=args.roi,
        scale=args.scale,
        crs=args.crs,
        folder=args.folder,
        project=args.project,
        manifest_path=args.manifest,
    )


if __name__ == "__main__":
    cli()
