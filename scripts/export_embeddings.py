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

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import (
    ACTIVE_ROI, EMBEDDING_COLLECTION_ID, EMBEDDING_YEARS,
    EXPORT_FOLDER, EXPORT_SCALE, EXPORT_CRS,
)


def main():
    # Initialize Earth Engine
    try:
        ee.Initialize()
        print("Earth Engine initialized successfully.")
    except Exception as e:
        print(f"Earth Engine init failed: {e}")
        print("Run `earthengine authenticate` in your terminal first.")
        sys.exit(1)

    # Define ROI
    roi = ee.Geometry.Rectangle(ACTIVE_ROI)
    print(f"ROI: {ACTIVE_ROI}")

    # Access the embedding collection
    collection = ee.ImageCollection(EMBEDDING_COLLECTION_ID)
    print(f"Collection: {EMBEDDING_COLLECTION_ID}")

    # Export each year
    for year in EMBEDDING_YEARS:
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
            folder=EXPORT_FOLDER,
            region=roi.getInfo()["coordinates"],
            scale=EXPORT_SCALE,
            crs=EXPORT_CRS,
            maxPixels=1e13,
            fileFormat="GeoTIFF",
        )
        task.start()
        print(f"  Export task started: '{description}'")
        print(f"  Destination: Google Drive/{EXPORT_FOLDER}/")

    print("\n" + "=" * 50)
    print("All export tasks submitted.")
    print("Monitor progress at: https://code.earthengine.google.com/tasks")
    print(f"When complete, download files to: data/raw/embeddings/")
    print("=" * 50)


if __name__ == "__main__":
    main()
