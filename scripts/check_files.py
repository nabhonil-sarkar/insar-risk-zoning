import rasterio

# Check embedding bounds
with rasterio.open('data/raw/embeddings/AlphaEarth_Jakarta_2023_merged.tif') as src:
    print("EMBEDDINGS:")
    print(f"  Shape: {src.width} x {src.height}")
    print(f"  Bounds: {src.bounds}")

# Check processed embedding if it exists
import os
proc = 'data/processed/embeddings/AlphaEarth_Jakarta_2023_merged_norm.tif'
if os.path.exists(proc):
    with rasterio.open(proc) as src:
        print(f"\nPROCESSED EMBEDDINGS:")
        print(f"  Shape: {src.width} x {src.height}")
        print(f"  Bounds: {src.bounds}")

# Check InSAR
with rasterio.open('data/raw/insar/jakarta_velocity_mmyr.tif') as src:
    print(f"\nINSAR:")
    print(f"  Shape: {src.width} x {src.height}")
    print(f"  Bounds: {src.bounds}")