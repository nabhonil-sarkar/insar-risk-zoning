"""
Module 5 — Risk Interpretation & Visualization (Option B: Two-Stage)

Creates risk zones from the combination of:
  - Land cover type (from embedding clustering)
  - Subsidence severity (from InSAR overlay)

Risk is context-dependent: dense urban sinking at -30 mm/yr is higher risk
than empty land sinking at -30 mm/yr. The two-stage approach captures this.
"""

import os
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.features import shapes as rio_shapes
from shapely.geometry import shape

from src.utils.geo_utils import load_raster, save_raster, features_to_raster
from config.settings import (
    OUT_RISK_MAPS_DIR, OUT_FIGURES_DIR, OUT_CLUSTERS_DIR,
    SUBSIDENCE_THRESHOLDS,
    CLUSTER_EXPOSURE, DEFAULT_EXPOSURE, EXPOSURE_RISK_MATRIX,
)


def create_risk_zones(labels, severity, severity_names, valid_mask, profile,
                      output_dir=None):
    """
    Create a risk raster from subsidence severity weighted by land cover
    exposure.

    Risk = EXPOSURE_RISK_MATRIX[severity][exposure], where each cluster's
    exposure level (low/medium/high) is assigned by the analyst in
    config.settings.CLUSTER_EXPOSURE after inspecting the cluster map.
    Unassigned clusters use DEFAULT_EXPOSURE; with everything at "medium"
    this reproduces the plain severity -> risk mapping (1, 2, 3, 4).

    Parameters
    ----------
    labels : np.ndarray
        Land cover cluster labels (n_valid_pixels,).
    severity : np.ndarray
        Subsidence severity labels (n_valid_pixels,).
    severity_names : dict
    valid_mask : np.ndarray
    profile : dict
    output_dir : str, optional

    Returns
    -------
    risk_raster_path : str
    """
    if output_dir is None:
        output_dir = OUT_RISK_MAPS_DIR
    os.makedirs(output_dir, exist_ok=True)

    # Risk = f(subsidence severity, land cover exposure).
    exposure_codes = {"low": 0, "medium": 1, "high": 2}

    if not CLUSTER_EXPOSURE:
        print(
            "WARNING: CLUSTER_EXPOSURE is empty — all clusters treated as "
            f"'{DEFAULT_EXPOSURE}' exposure (severity-only risk). Inspect "
            "figures/landcover_clusters.png, assign exposure levels in "
            "config/settings.py, then rerun with --force-from m4b for "
            "land-cover-aware risk zoning."
        )

    risk_labels = np.full_like(severity, -1, dtype=np.int8)
    valid = (labels >= 0) & (severity >= 0)

    exposure_used = {}
    for c in np.unique(labels[valid]):
        exp_name = CLUSTER_EXPOSURE.get(int(c), DEFAULT_EXPOSURE)
        if exp_name not in exposure_codes:
            raise ValueError(
                f"Cluster {int(c)}: unknown exposure '{exp_name}' — "
                f"must be one of {sorted(exposure_codes)}."
            )
        exposure_used[int(c)] = exp_name
        e = exposure_codes[exp_name]
        c_mask = valid & (labels == c)
        for sev_code in range(len(EXPOSURE_RISK_MATRIX)):
            m = c_mask & (severity == sev_code)
            risk_labels[m] = EXPOSURE_RISK_MATRIX[sev_code][e]

    print("  Exposure per cluster: " + ", ".join(
        f"{c}={e}" for c, e in sorted(exposure_used.items())))

    risk_raster = features_to_raster(risk_labels, valid_mask, nodata_value=-1)
    risk_path = os.path.join(output_dir, "risk_zones.tif")
    save_raster(risk_path, risk_raster, profile, nodata=-1)

    print(f"\nRisk zone raster saved: {risk_path}")
    print("  Encoding: 1=low, 2=moderate, 3=high, 4=very_high "
          "(severity x exposure weighted)")

    return risk_path, risk_labels


def vectorize_risk_zones(risk_raster_path, output_dir=None):
    """Convert risk raster to vector polygons."""
    if output_dir is None:
        output_dir = OUT_RISK_MAPS_DIR
    os.makedirs(output_dir, exist_ok=True)

    risk_names = {1: "low", 2: "moderate", 3: "high", 4: "very_high"}

    with rasterio.open(risk_raster_path) as src:
        data = src.read(1)
        transform = src.transform
        crs = src.crs

    polygons = []
    values = []
    for geom, value in rio_shapes(data, transform=transform):
        if value > 0:
            polygons.append(geom)
            values.append(value)

    geometries = [shape(g) for g in polygons]
    gdf = gpd.GeoDataFrame({
        "risk_code": values,
        "risk_level": [risk_names.get(int(v), "unknown") for v in values],
        "geometry": geometries,
    }, crs=crs)

    gdf_dissolved = gdf.dissolve(by="risk_level", as_index=False)

    output_path = os.path.join(output_dir, "risk_zones.gpkg")
    gdf_dissolved.to_file(output_path, driver="GPKG")
    print(f"Vectorized risk zones: {output_path}")
    print(f"  {len(gdf_dissolved)} risk zone polygons")

    return gdf_dissolved, output_path


def generate_report(cluster_stats, risk_matrix, risk_summary, metrics,
                    severity_names, output_dir=None):
    """Generate a comprehensive analysis report."""
    if output_dir is None:
        output_dir = OUT_RISK_MAPS_DIR
    os.makedirs(output_dir, exist_ok=True)

    lines = [
        "=" * 70,
        "InSAR-INFORMED SUBSIDENCE RISK ZONING — ANALYSIS REPORT",
        "Two-Stage Approach: Land Cover Clustering + InSAR Overlay",
        "=" * 70,
        "",
        "METHODOLOGY",
        "-" * 40,
        "Stage 1: Unsupervised clustering on AlphaEarth satellite embeddings",
        "         to discover land cover types. No InSAR data used.",
        "Stage 2: InSAR velocity analysis overlaid per land cover cluster.",
        "         Each pixel classified by subsidence severity independently.",
        "Risk:    Severity x exposure lookup (EXPOSURE_RISK_MATRIX).",
        f"         Cluster exposure: {CLUSTER_EXPOSURE if CLUSTER_EXPOSURE else f'none assigned — all {DEFAULT_EXPOSURE}'}",
        "",
        "LAND COVER CLUSTERING METRICS (Stage 1)",
        "-" * 40,
    ]
    for k, v in metrics.items():
        lines.append(f"  {k}: {v}")

    lines += [
        "",
        "SUBSIDENCE SEVERITY DEFINITIONS",
        "-" * 40,
    ]
    for name, (lo, hi) in SUBSIDENCE_THRESHOLDS.items():
        lines.append(f"  {name}: {lo} to {hi} mm/yr")

    lines += [
        "",
        "InSAR VELOCITY PER LAND COVER CLUSTER (Stage 2)",
        "-" * 40,
        "",
    ]

    for _, row in cluster_stats.iterrows():
        lines.append(f"  Cluster {int(row['cluster'])} ({int(row['pixel_count']):,} pixels):")
        lines.append(f"    Mean velocity:  {row['vel_mean']} mm/yr")
        lines.append(f"    Median velocity: {row['vel_median']} mm/yr")
        lines.append(f"    Range: [{row['vel_min']}, {row['vel_max']}] mm/yr")
        lines.append(f"    10th/90th percentile: [{row['vel_p10']}, {row['vel_p90']}]")
        lines.append(f"    Below -10 mm/yr: {int(row['n_below_neg10']):,} ({row['pct_below_neg10']}%)")
        lines.append(f"    Below -25 mm/yr: {int(row['n_below_neg25']):,} ({row['pct_below_neg25']}%)")
        lines.append("")

    lines += [
        "RISK SUMMARY",
        "-" * 40,
        "",
    ]
    for _, row in risk_summary.iterrows():
        lines.append(f"  Cluster {int(row['cluster'])}: {row['cluster_risk'].upper()} RISK")
        lines.append(f"    Moderate+ subsidence: {row['pct_moderate_or_worse']}% of pixels")
        lines.append(f"    Rapid subsidence: {row['pct_rapid']}% of pixels")
        lines.append("")

    lines += ["=" * 70]

    report_text = "\n".join(lines)
    report_path = os.path.join(output_dir, "analysis_report.txt")
    with open(report_path, "w") as f:
        f.write(report_text)

    print(f"\nReport saved: {report_path}")
    return report_path


def generate_all_figures(labels, velocity_flat, severity, severity_names,
                         label_raster, profile, risk_summary,
                         output_dir=None):
    """Generate all visualization figures for the two-stage analysis."""
    import matplotlib.pyplot as plt

    if output_dir is None:
        output_dir = OUT_FIGURES_DIR
    os.makedirs(output_dir, exist_ok=True)

    n_clusters = len(np.unique(labels[labels >= 0]))

    # 1. Land cover cluster map
    if label_raster.ndim == 3:
        label_2d = label_raster[0]
    else:
        label_2d = label_raster
    masked = np.ma.masked_where(label_2d == -1, label_2d)

    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(masked, cmap="tab10", interpolation="nearest")
    ax.set_title("Stage 1: Land Cover Clusters (Embeddings Only)", fontsize=14, fontweight="bold")
    plt.colorbar(im, ax=ax, shrink=0.7, label="Cluster ID")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "landcover_clusters.png"), dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved: landcover_clusters.png")

    # 2. Velocity distribution per cluster (box plot)
    fig, ax = plt.subplots(figsize=(14, 7))
    data_by_cluster = []
    tick_labels = []
    valid_vel = ~np.isnan(velocity_flat) & (velocity_flat != 0)

    for c in range(n_clusters):
        mask = (labels == c) & valid_vel
        vals = velocity_flat[mask]
        data_by_cluster.append(vals)
        risk = risk_summary.loc[risk_summary["cluster"] == c, "cluster_risk"].values
        risk_str = risk[0].upper() if len(risk) > 0 else "?"
        tick_labels.append(f"C{c}\n{risk_str}\n(n={len(vals):,})")

    bp = ax.boxplot(data_by_cluster, labels=tick_labels, patch_artist=True,
                    showfliers=False, medianprops=dict(color="black", linewidth=2))

    colors = plt.cm.tab10(np.linspace(0, 1, n_clusters))
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    ax.set_ylabel("Velocity (mm/year)", fontsize=12)
    ax.set_xlabel("Land Cover Cluster", fontsize=12)
    ax.set_title("Stage 2: Subsidence Velocity per Land Cover Type", fontsize=14, fontweight="bold")
    ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.8)
    ax.axhline(y=-10, color="orange", linestyle="--", linewidth=0.8, alpha=0.7, label="Moderate (-10)")
    ax.axhline(y=-25, color="red", linestyle="--", linewidth=0.8, alpha=0.7, label="Rapid (-25)")
    ax.legend(loc="lower left")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "velocity_per_cluster.png"), dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved: velocity_per_cluster.png")

    # 3. Subsidence severity histogram per cluster
    fig, axes = plt.subplots(2, (n_clusters + 1) // 2, figsize=(16, 10))
    axes = axes.flatten()

    for c in range(n_clusters):
        ax = axes[c]
        mask = (labels == c) & valid_vel
        vals = velocity_flat[mask]

        ax.hist(vals, bins=80, color=plt.cm.tab10(c / n_clusters), alpha=0.7, edgecolor="none")
        ax.axvline(x=-10, color="orange", linestyle="--", linewidth=1.5, label="-10")
        ax.axvline(x=-25, color="red", linestyle="--", linewidth=1.5, label="-25")
        ax.axvline(x=0, color="gray", linestyle="--", linewidth=0.8)

        risk = risk_summary.loc[risk_summary["cluster"] == c, "cluster_risk"].values
        risk_str = risk[0].upper() if len(risk) > 0 else "?"
        ax.set_title(f"Cluster {c} ({risk_str})", fontsize=11, fontweight="bold")
        ax.set_xlabel("mm/yr")
        ax.set_ylabel("Pixel count")
        if c == 0:
            ax.legend(fontsize=8)

    # Hide unused subplots
    for i in range(n_clusters, len(axes)):
        axes[i].set_visible(False)

    plt.suptitle("Velocity Histograms per Land Cover Cluster", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "velocity_histograms.png"), dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved: velocity_histograms.png")

    # 4. Risk matrix heatmap
    fig, ax = plt.subplots(figsize=(10, 6))

    sev_names = list(severity_names.values())
    matrix_pct = np.zeros((n_clusters, len(sev_names)))
    for c in range(n_clusters):
        total = (labels == c).sum()
        if total == 0:
            continue
        for s, sname in enumerate(sev_names):
            count = ((labels == c) & (severity == s)).sum()
            matrix_pct[c, s] = count / total * 100

    im = ax.imshow(matrix_pct, cmap="YlOrRd", aspect="auto")
    ax.set_xticks(range(len(sev_names)))
    ax.set_xticklabels([s.capitalize() for s in sev_names], fontsize=11)
    ax.set_yticks(range(n_clusters))
    ax.set_yticklabels([f"Cluster {c}" for c in range(n_clusters)], fontsize=11)
    ax.set_xlabel("Subsidence Severity", fontsize=12)
    ax.set_ylabel("Land Cover Type", fontsize=12)
    ax.set_title("Risk Matrix: % of Pixels per Severity Level", fontsize=14, fontweight="bold")

    for c in range(n_clusters):
        for s in range(len(sev_names)):
            val = matrix_pct[c, s]
            color = "white" if val > 40 else "black"
            ax.text(s, c, f"{val:.1f}%", ha="center", va="center", fontsize=10,
                    fontweight="bold", color=color)

    plt.colorbar(im, ax=ax, label="% of pixels", shrink=0.8)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "risk_matrix_heatmap.png"), dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved: risk_matrix_heatmap.png")

    # 5. Elbow/silhouette plot was already saved by Module 4
    print(f"\nAll figures saved to: {output_dir}")
