"""
Phase 1: Calibrate the InSAR velocity field.

Find a stable reference area, compute its mean velocity,
and shift the entire field so stable = ~0 mm/yr.
"""

import rasterio
import numpy as np
import matplotlib.pyplot as plt
import os


def find_stable_reference(label_path, velocity_path):
    """
    Identify the most stable pixels using:
    1. Land cover cluster with highest median velocity (most stable/uplifting)
    2. Within that cluster, pixels closest to the cluster median
    """
    with rasterio.open(label_path) as src:
        labels = src.read(1)
    with rasterio.open(velocity_path) as src:
        vel = src.read(1)

    print("=== Finding Stable Reference Area ===\n")

    # Analyze each cluster
    for c in sorted(np.unique(labels[labels >= 0])):
        mask = (labels == c) & ~np.isnan(vel) & (vel != 0)
        vals = vel[mask]
        if len(vals) > 0:
            print(f"  Cluster {c}: median={np.median(vals):.2f}, "
                  f"mean={vals.mean():.2f}, std={vals.std():.2f}, "
                  f"n={len(vals):,}")

    # Use cluster with tightest distribution (lowest std) as reference
    # This is more reliable than highest median
    best_cluster = None
    best_std = float("inf")
    for c in sorted(np.unique(labels[labels >= 0])):
        mask = (labels == c) & ~np.isnan(vel) & (vel != 0)
        vals = vel[mask]
        if len(vals) > 100 and vals.std() < best_std:
            best_std = vals.std()
            best_cluster = c

    print(f"\n  Most stable cluster: {best_cluster} (std={best_std:.2f})")

    # Get reference velocity from the stable cluster
    ref_mask = (labels == best_cluster) & ~np.isnan(vel) & (vel != 0)
    ref_vals = vel[ref_mask]
    ref_velocity = np.median(ref_vals)

    print(f"  Reference velocity (median): {ref_velocity:.2f} mm/yr")
    print(f"  This value will be subtracted from all pixels.\n")

    return ref_velocity, best_cluster


def calibrate(velocity_path, ref_velocity, output_path):
    """Shift the velocity field by the reference value."""
    with rasterio.open(velocity_path) as src:
        vel = src.read(1).astype(np.float32)
        profile = src.profile.copy()

    # Apply calibration
    valid = ~np.isnan(vel) & (vel != 0)
    vel_calibrated = vel.copy()
    vel_calibrated[valid] = vel[valid] - ref_velocity

    print("=== Calibration Results ===\n")
    cal_vals = vel_calibrated[valid]
    print(f"  Before: mean={vel[valid].mean():.2f}, "
          f"range=[{vel[valid].min():.1f}, {vel[valid].max():.1f}]")
    print(f"  After:  mean={cal_vals.mean():.2f}, "
          f"range=[{cal_vals.min():.1f}, {cal_vals.max():.1f}]")
    print(f"  Shift applied: {ref_velocity:.2f} mm/yr")
    print(f"  Pixels below -10: {(cal_vals < -10).sum():,}")
    print(f"  Pixels below -25: {(cal_vals < -25).sum():,}")

    # Save
    profile.update(dtype="float32", nodata=np.nan)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(vel_calibrated[np.newaxis, :, :])

    print(f"\n  Saved calibrated velocity: {output_path}")
    return vel_calibrated


def plot_before_after(vel_original_path, vel_calibrated, output_dir):
    """Visualize the calibration effect."""
    with rasterio.open(vel_original_path) as src:
        vel_orig = src.read(1)

    os.makedirs(output_dir, exist_ok=True)

    valid_orig = vel_orig[~np.isnan(vel_orig) & (vel_orig != 0)]
    valid_cal = vel_calibrated[~np.isnan(vel_calibrated) & (vel_calibrated != 0)]

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    axes[0].hist(valid_orig, bins=100, color="steelblue", alpha=0.7, edgecolor="none")
    axes[0].axvline(x=0, color="black", linestyle="--", linewidth=1)
    axes[0].set_title("Before Calibration", fontsize=13, fontweight="bold")
    axes[0].set_xlabel("Velocity (mm/yr)")
    axes[0].set_ylabel("Pixel count")

    axes[1].hist(valid_cal, bins=100, color="coral", alpha=0.7, edgecolor="none")
    axes[1].axvline(x=0, color="black", linestyle="--", linewidth=1)
    axes[1].axvline(x=-10, color="orange", linestyle="--", linewidth=1, label="Moderate (-10)")
    axes[1].axvline(x=-25, color="red", linestyle="--", linewidth=1, label="Rapid (-25)")
    axes[1].set_title("After Calibration", fontsize=13, fontweight="bold")
    axes[1].set_xlabel("Velocity (mm/yr)")
    axes[1].legend()

    plt.suptitle("Velocity Calibration", fontsize=15, fontweight="bold")
    plt.tight_layout()
    save_path = os.path.join(output_dir, "calibration_comparison.png")
    plt.savefig(save_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {save_path}")


if __name__ == "__main__":
    label_path = "data/output/clusters/landcover_clusters_kmeans_k4.tif"
    velocity_path = "data/processed/fused/velocity_aligned.tif"
    calibrated_path = "data/raw/insar/jakarta_velocity_calibrated.tif"
    figures_dir = "data/output/figures"

    # Step 1: Find stable reference
    ref_velocity, ref_cluster = find_stable_reference(label_path, velocity_path)

    # Step 2: Calibrate
    vel_calibrated = calibrate(velocity_path, ref_velocity, calibrated_path)

    # Step 3: Visualize
    plot_before_after(velocity_path, vel_calibrated, figures_dir)

    print("\n=== Phase 1 Complete ===")
    print(f"Calibrated velocity saved to: {calibrated_path}")
    print(f"\nNext: Replace the raw velocity file and rerun the pipeline:")
    print(f"  1. Copy {calibrated_path} to data/raw/insar/")
    print(f"  2. Delete data/processed/insar/* and data/processed/fused/*")
    print(f"  3. Rerun: python scripts/run_full_pipeline.py")