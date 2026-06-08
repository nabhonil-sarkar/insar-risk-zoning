import rasterio
import numpy as np

# Load cluster labels
with rasterio.open('data/output/clusters/clusters_kmeans_k5.tif') as src:
    labels = src.read(1)

# Load aligned velocity (single band)
with rasterio.open('data/processed/fused/velocity_aligned.tif') as src:
    vel = src.read(1)

print("Raw velocity statistics per cluster:\n")
for c in range(5):
    mask = (labels == c) & ~np.isnan(vel) & (vel != 0)
    vals = vel[mask]
    if len(vals) > 0:
        print(f"Cluster {c}: n={len(vals):,}")
        print(f"  Mean:   {vals.mean():.2f} mm/yr")
        print(f"  Median: {np.median(vals):.2f} mm/yr")
        print(f"  Min:    {vals.min():.2f} mm/yr")
        print(f"  Max:    {vals.max():.2f} mm/yr")
        print(f"  Below -10: {(vals < -10).sum()}")
        print(f"  Below -25: {(vals < -25).sum()}")
        print()