"""
Module 4B — InSAR Overlay Analysis (Stage 2 of Option B)

For each land cover cluster discovered in Stage 1, this module:
1. Extracts the InSAR velocity distribution
2. Computes per-cluster subsidence statistics
3. Sub-classifies pixels within each cluster by subsidence severity
4. Produces a combined land-cover × subsidence-severity label for every pixel

This keeps the two data sources analytically separate while combining
their information for risk assessment.
"""

import os
import numpy as np
import pandas as pd
from src.utils.geo_utils import load_raster, save_raster, features_to_raster
from config.settings import (
    OUT_CLUSTERS_DIR, SUBSIDENCE_THRESHOLDS, UPLIFT_REPORT_THRESHOLD,
    MIN_CLUSTER_VELOCITY_COVERAGE_PCT,
)


def load_aligned_velocity(velocity_path, valid_mask):
    """
    Load the aligned velocity raster and extract valid pixels.

    Parameters
    ----------
    velocity_path : str
        Path to the aligned velocity GeoTIFF (single band).
    valid_mask : np.ndarray
        Boolean (H, W) — same mask used for embeddings.

    Returns
    -------
    velocity_flat : np.ndarray
        Shape (n_valid_pixels,) — raw velocity in mm/yr.
    velocity_raster : np.ndarray
        Shape (H, W) — full raster.
    """
    data, _ = load_raster(velocity_path)
    velocity_raster = data[0]  # single band

    velocity_flat = velocity_raster[valid_mask]
    print(f"Loaded velocity: {velocity_flat.shape[0]:,} valid pixels")
    print(f"  Range: [{np.nanmin(velocity_flat):.1f}, {np.nanmax(velocity_flat):.1f}] mm/yr")
    print(f"  Mean: {np.nanmean(velocity_flat):.2f} mm/yr")

    return velocity_flat, velocity_raster


def analyze_velocity_per_cluster(labels, velocity_flat):
    """
    Compute InSAR velocity statistics for each land cover cluster.

    Parameters
    ----------
    labels : np.ndarray
        Shape (n_valid_pixels,) — land cover cluster assignments.
    velocity_flat : np.ndarray
        Shape (n_valid_pixels,) — raw velocity in mm/yr.

    Returns
    -------
    cluster_stats : pd.DataFrame
        One row per cluster with velocity statistics.
    """
    unique_labels = sorted(np.unique(labels[labels >= 0]))
    rows = []

    print("\n=== InSAR Velocity per Land Cover Cluster ===\n")

    for label in unique_labels:
        mask = (labels == label) & ~np.isnan(velocity_flat) & (velocity_flat != 0)
        vals = velocity_flat[mask]

        if len(vals) == 0:
            continue

        row = {
            "cluster": label,
            "pixel_count": int(mask.sum()),
            "vel_mean": round(float(vals.mean()), 2),
            "vel_median": round(float(np.median(vals)), 2),
            "vel_std": round(float(vals.std()), 2),
            "vel_min": round(float(vals.min()), 2),
            "vel_max": round(float(vals.max()), 2),
            "vel_p10": round(float(np.percentile(vals, 10)), 2),
            "vel_p25": round(float(np.percentile(vals, 25)), 2),
            "vel_p75": round(float(np.percentile(vals, 75)), 2),
            "vel_p90": round(float(np.percentile(vals, 90)), 2),
            "pct_below_neg2": round(float((vals < -2).sum() / len(vals) * 100), 1),
            "pct_below_neg10": round(float((vals < -10).sum() / len(vals) * 100), 1),
            "pct_below_neg25": round(float((vals < -25).sum() / len(vals) * 100), 1),
            "n_below_neg10": int((vals < -10).sum()),
            "n_below_neg25": int((vals < -25).sum()),
        }
        rows.append(row)

        print(f"  Cluster {label} (n={row['pixel_count']:,}):")
        print(f"    Velocity: mean={row['vel_mean']}, median={row['vel_median']}, "
              f"std={row['vel_std']}")
        print(f"    Range: [{row['vel_min']}, {row['vel_max']}] mm/yr")
        print(f"    10th/90th percentile: [{row['vel_p10']}, {row['vel_p90']}]")
        print(f"    Below -10 mm/yr: {row['n_below_neg10']:,} ({row['pct_below_neg10']}%)")
        print(f"    Below -25 mm/yr: {row['n_below_neg25']:,} ({row['pct_below_neg25']}%)")

    return pd.DataFrame(rows)


def classify_subsidence_severity(velocity_flat, thresholds=None):
    """
    Classify each pixel's subsidence severity independent of land cover.

    Parameters
    ----------
    velocity_flat : np.ndarray
        Shape (n_valid_pixels,) — raw velocity in mm/yr.
    thresholds : dict, optional
        Severity thresholds. Defaults to config settings.

    Returns
    -------
    severity : np.ndarray
        Integer severity labels (0=stable, 1=slow, 2=moderate, 3=rapid).
    severity_names : dict
        Mapping from integer to name.
    """
    if thresholds is None:
        thresholds = SUBSIDENCE_THRESHOLDS

    severity_names = {}
    # Initialize to -1 (unclassified), NOT 0: with a 0 default, any gap in
    # the threshold bins silently classifies pixels as "stable" — this is
    # exactly the bug that mislabelled rapidly subsiding pixels (< -100
    # mm/yr) as stable in v0.2.0.
    severity = np.full(velocity_flat.shape, -1, dtype=np.int8)

    for i, (name, (lo, hi)) in enumerate(thresholds.items()):
        mask = (velocity_flat >= lo) & (velocity_flat < hi)
        severity[mask] = i
        severity_names[i] = name

    # NaN velocities are invalid
    severity[np.isnan(velocity_flat)] = -1

    # Safety net: bins now cover the full real line, so every finite
    # velocity MUST be classified. Fail loudly if the config regresses.
    unclassified = (severity == -1) & ~np.isnan(velocity_flat)
    if unclassified.any():
        raise ValueError(
            f"{int(unclassified.sum()):,} finite-velocity pixels fall "
            f"outside all severity bins. SUBSIDENCE_THRESHOLDS has gaps — "
            f"bins must be half-open [lo, hi) and jointly cover "
            f"(-inf, +inf)."
        )

    # Print distribution
    print("\n=== Subsidence Severity Distribution ===\n")
    total_valid = (severity >= 0).sum()
    for i, name in severity_names.items():
        count = (severity == i).sum()
        pct = count / total_valid * 100 if total_valid > 0 else 0
        print(f"  {name}: {count:,} pixels ({pct:.1f}%)")

    # Transparency: uplift is folded into "stable" for risk purposes,
    # but report it so the choice is visible.
    n_uplift = int((velocity_flat > UPLIFT_REPORT_THRESHOLD).sum())
    if n_uplift > 0:
        pct = n_uplift / total_valid * 100 if total_valid > 0 else 0
        print(f"  (of which uplift > +{UPLIFT_REPORT_THRESHOLD:g} mm/yr: "
              f"{n_uplift:,} pixels, {pct:.1f}% — classified stable)")

    return severity, severity_names


def create_combined_labels(labels, severity, n_clusters, n_severity_levels):
    """
    Create combined land-cover × subsidence-severity labels.

    Each unique combination gets a unique ID:
        combined = cluster_id * n_severity_levels + severity_level

    Parameters
    ----------
    labels : np.ndarray
        Land cover cluster labels.
    severity : np.ndarray
        Subsidence severity labels.
    n_clusters : int
    n_severity_levels : int

    Returns
    -------
    combined : np.ndarray
        Combined labels. -1 for invalid pixels.
    """
    combined = np.full_like(labels, -1, dtype=np.int16)
    valid = (labels >= 0) & (severity >= 0)
    combined[valid] = labels[valid] * n_severity_levels + severity[valid]

    n_unique = len(np.unique(combined[combined >= 0]))
    print(f"\nCombined labels: {n_unique} unique land-cover × severity zones")

    return combined


def build_risk_matrix(labels, severity, velocity_flat, severity_names,
                      n_clusters):
    """
    Build a risk matrix showing how subsidence is distributed across
    land cover types.

    Parameters
    ----------
    labels : np.ndarray
    severity : np.ndarray
    velocity_flat : np.ndarray
    severity_names : dict
    n_clusters : int

    Returns
    -------
    risk_matrix : pd.DataFrame
        Rows = land cover clusters, columns = severity levels.
        Values = pixel counts.
    risk_summary : pd.DataFrame
        One row per cluster with risk assessment.
    """
    # Build count matrix
    matrix_data = {}
    for sev_id, sev_name in severity_names.items():
        col = []
        for c in range(n_clusters):
            count = int(((labels == c) & (severity == sev_id)).sum())
            col.append(count)
        matrix_data[sev_name] = col

    # Count matrix rows sum over severity classes 0..N only, so the "total"
    # here is the number of VALID-VELOCITY pixels per cluster (severity == -1
    # pixels are not in any severity column). Percentages are therefore
    # share-of-valid-velocity — consistent with the risk_summary denominator
    # (review finding 1.5 / 4.3). Named explicitly to avoid confusion with
    # total cluster pixels.
    risk_matrix = pd.DataFrame(matrix_data, index=[f"Cluster_{c}" for c in range(n_clusters)])
    risk_matrix["classified_total"] = risk_matrix.sum(axis=1)

    # Add percentage columns (share of valid-velocity pixels)
    for sev_name in severity_names.values():
        risk_matrix[f"{sev_name}_pct"] = (
            risk_matrix[sev_name] / risk_matrix["classified_total"] * 100
        ).round(1)

    print("\n=== Risk Matrix (pixel counts) ===\n")
    print(risk_matrix.to_string())

    # Build risk summary
    rows = []
    for c in range(n_clusters):
        cluster_mask = labels == c
        total_pixels = int(cluster_mask.sum())
        if total_pixels == 0:
            continue

        # Denominator for subsidence prevalence must be pixels with a VALID
        # velocity classification (severity >= 0), NOT all cluster pixels
        # (review finding 1.5). Using all pixels conflates subsidence
        # prevalence with InSAR coverage: a heavily subsiding cluster with
        # poor coherence would be silently under-rated. This also aligns the
        # risk_summary denominator with the risk_matrix, which already
        # excludes severity == -1.
        classified = (labels == c) & (severity >= 0)
        n_classified = int(classified.sum())

        # Zero is a valid physical velocity. Raw nodata sentinels are converted
        # to NaN in M1, so excluding exact zeros here would bias stable areas.
        vel = velocity_flat[cluster_mask & np.isfinite(velocity_flat)]

        n_moderate = int((classified & (severity >= 2)).sum())
        n_rapid = int((classified & (severity >= 3)).sum())

        if n_classified > 0:
            pct_moderate = round(n_moderate / n_classified * 100, 1)
            pct_rapid = round(n_rapid / n_classified * 100, 1)
        else:
            # Cluster has no valid-velocity pixels at all — cannot assess
            # subsidence. Report zero prevalence and 0% coverage; the risk
            # level falls through to "low" but the coverage column makes the
            # absence of data explicit rather than implying stability.
            pct_moderate = 0.0
            pct_rapid = 0.0

        row = {
            "cluster": c,
            "total_pixels": total_pixels,
            "classified_pixels": n_classified,
            "pct_velocity_coverage": round(n_classified / total_pixels * 100, 1),
            "vel_mean": round(float(vel.mean()), 2) if len(vel) > 0 else 0,
            "vel_median": round(float(np.median(vel)), 2) if len(vel) > 0 else 0,
            "pct_moderate_or_worse": pct_moderate,
            "pct_rapid": pct_rapid,
        }

        # A prevalence estimate from sparse coverage is not evidence of
        # cluster-wide risk. Withhold the rating below the configured gate.
        if (row["pct_velocity_coverage"]
                < MIN_CLUSTER_VELOCITY_COVERAGE_PCT):
            row["cluster_risk"] = "insufficient_evidence"
        elif row["pct_rapid"] > 20:
            row["cluster_risk"] = "very_high"
        elif row["pct_moderate_or_worse"] > 30:
            row["cluster_risk"] = "high"
        elif row["pct_moderate_or_worse"] > 10:
            row["cluster_risk"] = "moderate"
        else:
            row["cluster_risk"] = "low"

        rows.append(row)

    risk_summary = pd.DataFrame(rows)

    print("\n=== Risk Summary per Land Cover Cluster ===\n")
    for _, row in risk_summary.iterrows():
        print(f"  Cluster {int(row['cluster'])}: {row['cluster_risk'].upper()}")
        print(f"    Mean velocity: {row['vel_mean']} mm/yr")
        print(f"    Moderate+ subsidence: {row['pct_moderate_or_worse']}% "
              f"(of valid-velocity pixels)")
        print(f"    Rapid subsidence: {row['pct_rapid']}% "
              f"(of valid-velocity pixels)")
        print(f"    Velocity coverage: {row['pct_velocity_coverage']}% "
              f"({int(row['classified_pixels']):,}/{int(row['total_pixels']):,} pixels)")

    return risk_matrix, risk_summary


def run_insar_overlay(labels, valid_mask, velocity_path, profile,
                      output_dir=None):
    """
    Full Stage 2 pipeline: overlay InSAR onto land cover clusters.

    Parameters
    ----------
    labels : np.ndarray
        Shape (n_valid_pixels,) — land cover cluster labels from Stage 1.
    valid_mask : np.ndarray
        Boolean (H, W).
    velocity_path : str
        Path to aligned velocity GeoTIFF.
    profile : dict
        Rasterio profile for output rasters.
    output_dir : str, optional

    Returns
    -------
    results : dict
        Contains cluster_stats, severity, severity_names, combined_labels,
        risk_matrix, risk_summary, velocity_flat.
    """
    if output_dir is None:
        output_dir = OUT_CLUSTERS_DIR
    os.makedirs(output_dir, exist_ok=True)

    n_clusters = len(np.unique(labels[labels >= 0]))

    # Load velocity
    velocity_flat, velocity_raster = load_aligned_velocity(velocity_path, valid_mask)

    # Analyze velocity per cluster
    cluster_stats = analyze_velocity_per_cluster(labels, velocity_flat)

    # Classify subsidence severity
    severity, severity_names = classify_subsidence_severity(velocity_flat)
    n_severity = len(severity_names)

    # Create combined labels
    combined = create_combined_labels(labels, severity, n_clusters, n_severity)

    # Build risk matrix
    risk_matrix, risk_summary = build_risk_matrix(
        labels, severity, velocity_flat, severity_names, n_clusters
    )

    # Save severity raster
    severity_raster = features_to_raster(severity, valid_mask, nodata_value=-1)
    severity_path = os.path.join(output_dir, "subsidence_severity.tif")
    save_raster(severity_path, severity_raster, profile, nodata=-1)

    # Save combined raster
    combined_raster = features_to_raster(combined, valid_mask, nodata_value=-1)
    combined_path = os.path.join(output_dir, "combined_landcover_subsidence.tif")
    save_raster(combined_path, combined_raster, profile, nodata=-1)

    # Save cluster stats
    stats_path = os.path.join(output_dir, "cluster_velocity_stats.csv")
    cluster_stats.to_csv(stats_path, index=False)
    print(f"\nSaved cluster stats: {stats_path}")

    # Save risk matrix
    matrix_path = os.path.join(output_dir, "risk_matrix.csv")
    risk_matrix.to_csv(matrix_path)
    print(f"Saved risk matrix: {matrix_path}")

    return {
        "cluster_stats": cluster_stats,
        "severity": severity,
        "severity_names": severity_names,
        "combined_labels": combined,
        "risk_matrix": risk_matrix,
        "risk_summary": risk_summary,
        "velocity_flat": velocity_flat,
        "velocity_raster": velocity_raster,
    }
