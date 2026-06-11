"""
Run the full InSAR Risk Zoning pipeline — Option B: Two-Stage Approach.

Stage 1: Cluster AlphaEarth embeddings to discover land cover types.
          No InSAR data is used in clustering.
Stage 2: Overlay calibrated InSAR velocity onto land cover clusters.
          Analyze subsidence patterns within each land cover context.
Risk:    Combine land cover type × subsidence severity.

Features:
  - Pre-flight validation: fails fast if raw data is missing.
  - Idempotency: skips expensive steps if outputs already exist.
  - Integrated calibration: auto-corrects InSAR velocity bias using
    cluster labels — no manual intervention needed.
  - Granular --force flags: reprocess everything, or cascade from
    a specific stage onward.
  - Logging: all pipeline decisions written to timestamped log file.
  - CLI hyperparameters: clustering method and k configurable at runtime.

Usage:
    python scripts/run_full_pipeline.py                     # default run
    python scripts/run_full_pipeline.py --force              # reprocess all
    python scripts/run_full_pipeline.py --force-from m4      # redo clustering+
    python scripts/run_full_pipeline.py --method gmm --k 6   # try GMM k=6
    python scripts/run_full_pipeline.py --force-from cal     # recalibrate only
"""

import sys
import os
import argparse
import glob
import json
import logging
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    ensure_dirs,
    RAW_EMBEDDINGS_DIR, RAW_INSAR_DIR,
    PROC_EMBEDDINGS_DIR, PROC_INSAR_DIR, PROC_FUSED_DIR,
    OUT_CLUSTERS_DIR, OUT_RISK_MAPS_DIR, OUT_FIGURES_DIR,
    OUT_LOG_DIR, PIPELINE_STATE_FILE, DEFAULT_N_CLUSTERS,
    CALIBRATION_MIN_CLUSTER_PIXELS,
    CALIBRATION_MAX_SHIFT, CALIBRATION_CANDIDATE_TOLERANCE,
)

# ── Constants ────────────────────────────────────────────────────────────────
# Pipeline stages in execution order. --force-from cascades from the chosen
# stage through everything downstream.
STAGE_ORDER = ["m2", "m1", "m3", "m4", "cal", "m4b", "m5"]
# ─────────────────────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════════════════════
# SETUP & HELPERS
# ══════════════════════════════════════════════════════════════════════════════

logger = logging.getLogger("pipeline")


def setup_logging():
    """
    Configure dual-output logging: timestamped file + clean console.

    Log files are written to data/output/logs/ with per-run timestamps
    so previous runs are preserved for auditing.

    Note: Module-internal print() calls (m1–m5) appear on console only.
    The log file captures pipeline orchestration, caching decisions,
    calibration results, and timing — the important bits for debugging.
    """
    os.makedirs(OUT_LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(OUT_LOG_DIR, f"pipeline_{timestamp}.log")

    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if main() is called more than once
    if not logger.handlers:
        # File handler — full timestamps for post-hoc debugging
        fh = logging.FileHandler(log_file)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(fh)

        # Console handler — clean output matching the existing print style
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(ch)

    logger.info(f"Log file: {log_file}")
    return log_file


def validate_prerequisites(synthetic=False):
    """
    Fail fast if raw data files are missing.

    Checks that embedding and InSAR directories contain at least one
    GeoTIFF before any expensive processing begins. Does not hardcode
    filenames — the pipeline discovers files dynamically downstream.
    """
    errors = []

    emb_files = (glob.glob(os.path.join(RAW_EMBEDDINGS_DIR, "*.tif"))
                 + glob.glob(os.path.join(RAW_EMBEDDINGS_DIR, "*.tiff")))
    if not emb_files:
        errors.append(
            f"No GeoTIFF files in {RAW_EMBEDDINGS_DIR}. "
            f"Export embeddings from Earth Engine first "
            f"(see scripts/export_embeddings.py)."
        )

    if not synthetic:
        insar_files = (glob.glob(os.path.join(RAW_INSAR_DIR, "*.tif"))
                       + glob.glob(os.path.join(RAW_INSAR_DIR, "*.tiff")))
        if not insar_files:
            errors.append(
                f"No GeoTIFF files in {RAW_INSAR_DIR}. "
                f"Provide InSAR velocity data or use --synthetic."
            )

    if errors:
        for e in errors:
            logger.error(f"MISSING DATA: {e}")
        logger.error("Pipeline cannot proceed without raw data.")
        sys.exit(1)

    logger.info("Pre-flight check passed: raw data present.")


def compute_force_stages(force_all=False, force_from=None):
    """
    Determine which stages should bypass their cache.

    --force:           every stage reruns.
    --force-from m4:   m4, cal, m4b, m5 rerun; m2, m1, m3 use cache.

    Returns a set of stage names that should be forced.
    """
    if force_all:
        return set(STAGE_ORDER)
    if force_from and force_from in STAGE_ORDER:
        idx = STAGE_ORDER.index(force_from)
        forced = set(STAGE_ORDER[idx:])
        logger.info(f"Forcing stages from '{force_from}' onward: "
                    f"{', '.join(sorted(forced, key=STAGE_ORDER.index))}")
        return forced
    return set()


def find_cached(pattern, label, stage, force_stages):
    """
    Check if an output file matching `pattern` already exists.

    Returns the path if found and the stage is not forced, else None.
    """
    if stage in force_stages:
        logger.info(f"  [forced] {label} — reprocessing")
        return None
    matches = sorted(glob.glob(pattern))
    if matches:
        path = matches[-1]
        size_mb = os.path.getsize(path) / 1e6
        logger.info(f"  [cached] {label}: {os.path.basename(path)} "
                    f"({size_mb:.1f} MB)")
        return path
    return None


def save_pipeline_state(paths, config, risk_summary_df):
    """
    Write pipeline state to JSON so downstream scripts (e.g. sub-clustering)
    can discover file paths and risk results without hardcoding.

    Parameters
    ----------
    paths : dict
        Key output file paths (embeddings, velocity, labels, etc.).
    config : dict
        Pipeline configuration (method, k, calibrated, etc.).
    risk_summary_df : pd.DataFrame
        Per-cluster risk summary from M4B.
    """
    # Convert risk_summary DataFrame to serializable list of dicts
    risk_records = []
    for _, row in risk_summary_df.iterrows():
        risk_records.append({
            "cluster": int(row["cluster"]),
            "cluster_risk": row["cluster_risk"],
            "total_pixels": int(row["total_pixels"]),
            "vel_mean": float(row["vel_mean"]),
            "pct_moderate_or_worse": float(row["pct_moderate_or_worse"]),
            "pct_rapid": float(row["pct_rapid"]),
        })

    state = {
        "timestamp": datetime.now().isoformat(),
        "config": config,
        "paths": paths,
        "risk_summary": risk_records,
    }

    os.makedirs(os.path.dirname(PIPELINE_STATE_FILE), exist_ok=True)
    with open(PIPELINE_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    logger.info(f"  Pipeline state:       {PIPELINE_STATE_FILE}")


# ══════════════════════════════════════════════════════════════════════════════
# CALIBRATION
# ══════════════════════════════════════════════════════════════════════════════

def calibrate_velocity_field(label_raster, velocity_path, output_path,
                             figures_dir=None):
    """
    Calibrate InSAR velocity by identifying the most stable land cover
    cluster and shifting the entire field so stable areas read ~0 mm/yr.

    The most stable cluster is the one with the lowest velocity standard
    deviation. Its median velocity is subtracted from all pixels.

    Parameters
    ----------
    label_raster : np.ndarray
        Cluster label raster, shape (1, H, W) with nodata = -1.
    velocity_path : str
        Path to the aligned (uncalibrated) velocity GeoTIFF.
    output_path : str
        Where to save the calibrated velocity GeoTIFF.
    figures_dir : str, optional
        If provided, saves a before/after histogram comparison.

    Returns
    -------
    output_path : str
    ref_velocity : float
        The bias that was subtracted (mm/yr).
    ref_cluster : int
        Which cluster was used as the stable reference.
    """
    import rasterio
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels_2d = label_raster[0] if label_raster.ndim == 3 else label_raster

    with rasterio.open(velocity_path) as src:
        vel = src.read(1).astype(np.float32)
        profile = src.profile.copy()

    # ── Find the most stable cluster (lowest velocity std) ───────────
    logger.info("  Scanning clusters for stable reference...")
    candidates = []  # (std, median, cluster, n)

    for c in sorted(np.unique(labels_2d[labels_2d >= 0])):
        mask = (labels_2d == c) & ~np.isnan(vel) & (vel != 0)
        vals = vel[mask]
        if len(vals) > CALIBRATION_MIN_CLUSTER_PIXELS:
            std = float(vals.std())
            med = float(np.median(vals))
            logger.info(f"    Cluster {c}: median={med:+.2f}, "
                        f"std={std:.2f}, n={len(vals):,}")
            candidates.append((std, med, int(c), len(vals)))

    if not candidates:
        logger.warning("  No suitable reference cluster found. "
                       "Skipping calibration.")
        return velocity_path, 0.0, -1

    candidates.sort()  # by std ascending
    best_std, ref_velocity, best_cluster, _ = candidates[0]

    # ── Sanity check 1: shift magnitude ──────────────────────────────
    if abs(ref_velocity) > CALIBRATION_MAX_SHIFT:
        logger.warning(
            f"  Calibration shift {ref_velocity:+.2f} mm/yr exceeds "
            f"CALIBRATION_MAX_SHIFT ({CALIBRATION_MAX_SHIFT:g}). The "
            f"reference cluster may itself be deforming uniformly — "
            f"verify cluster {best_cluster} against known stable ground "
            f"before trusting calibrated rates."
        )

    # ── Sanity check 2: sensitivity to reference choice ──────────────
    top = candidates[:3]
    if len(top) > 1:
        medians = [m for _, m, _, _ in top]
        spread = max(medians) - min(medians)
        detail = ", ".join(f"C{c}: median={m:+.2f} (std={s:.2f})"
                           for s, m, c, _ in top)
        logger.info(f"  Reference candidates (lowest std): {detail}")
        if spread > CALIBRATION_CANDIDATE_TOLERANCE:
            logger.warning(
                f"  Top reference candidates disagree by {spread:.2f} mm/yr "
                f"(> {CALIBRATION_CANDIDATE_TOLERANCE:g}) — calibration is "
                f"sensitive to reference choice. Report this spread as "
                f"calibration uncertainty."
            )

    # ── Compute and apply the shift ──────────────────────────────────
    valid = ~np.isnan(vel) & (vel != 0)
    vel_calibrated = vel.copy()
    vel_calibrated[valid] -= ref_velocity

    cal_vals = vel_calibrated[valid]
    logger.info(f"  Reference cluster: {best_cluster} (std={best_std:.2f})")
    logger.info(f"  Reference velocity (median): {ref_velocity:+.2f} mm/yr")
    logger.info(f"  Before calibration: mean={vel[valid].mean():+.2f} mm/yr")
    logger.info(f"  After calibration:  mean={cal_vals.mean():+.2f} mm/yr")
    logger.info(f"  Pixels below -10 mm/yr: {(cal_vals < -10).sum():,}")
    logger.info(f"  Pixels below -25 mm/yr: {(cal_vals < -25).sum():,}")

    # ── Save ─────────────────────────────────────────────────────────
    profile.update(dtype="float32", nodata=np.nan)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(vel_calibrated[np.newaxis, :, :])
    logger.info(f"  Saved: {output_path}")

    # ── Before/after histogram ───────────────────────────────────────
    if figures_dir:
        os.makedirs(figures_dir, exist_ok=True)
        orig_vals = vel[valid]

        fig, axes = plt.subplots(1, 2, figsize=(16, 6))

        axes[0].hist(orig_vals, bins=100, color="steelblue", alpha=0.7,
                     edgecolor="none")
        axes[0].axvline(x=0, color="black", linestyle="--", linewidth=1)
        axes[0].set_title("Before Calibration", fontsize=13, fontweight="bold")
        axes[0].set_xlabel("Velocity (mm/yr)")
        axes[0].set_ylabel("Pixel count")

        axes[1].hist(cal_vals, bins=100, color="coral", alpha=0.7,
                     edgecolor="none")
        axes[1].axvline(x=0, color="black", linestyle="--", linewidth=1)
        axes[1].axvline(x=-10, color="orange", linestyle="--", linewidth=1,
                        label="Moderate (-10)")
        axes[1].axvline(x=-25, color="red", linestyle="--", linewidth=1,
                        label="Rapid (-25)")
        axes[1].set_title("After Calibration", fontsize=13, fontweight="bold")
        axes[1].set_xlabel("Velocity (mm/yr)")
        axes[1].legend()

        plt.suptitle(
            f"Velocity Calibration (shift={ref_velocity:+.2f} mm/yr, "
            f"ref=Cluster {best_cluster})",
            fontsize=14, fontweight="bold",
        )
        plt.tight_layout()
        save_path = os.path.join(figures_dir, "calibration_comparison.png")
        plt.savefig(save_path, dpi=200, bbox_inches="tight")
        plt.close()
        logger.info(f"  Saved figure: {save_path}")

    return output_path, ref_velocity, best_cluster


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def main(force=False, force_from=None, method="kmeans", k=None,
         no_k_search=False, no_calibration=False, synthetic=False):
    """
    Run the full two-stage pipeline.

    Parameters
    ----------
    force : bool
        Bypass ALL caches — reprocess from scratch.
    force_from : str or None
        Rerun from this stage onward (cascade). One of:
        m2, m1, m3, m4, cal, m4b, m5.
    method : str
        Clustering algorithm: 'kmeans', 'gmm', or 'hdbscan'.
    k : int or None
        Explicit cluster count. If set, skips k-search.
    no_k_search : bool
        Skip optimal-k search; use --k or DEFAULT_N_CLUSTERS.
    no_calibration : bool
        Skip InSAR velocity calibration.
    synthetic : bool
        Use synthetic InSAR data for testing.
    """
    # ── Setup ────────────────────────────────────────────────────────
    log_file = setup_logging()
    force_stages = compute_force_stages(force, force_from)

    logger.info("=" * 70)
    logger.info("InSAR-INFORMED SUBSIDENCE RISK ZONING")
    logger.info("Two-Stage Approach: Land Cover Clustering + InSAR Overlay")
    logger.info(f"  Method: {method}  |  k: {k or 'auto-search'}  |  "
                f"Calibrate: {not no_calibration}")
    if force_stages:
        logger.info(f"  Forced stages: {', '.join(sorted(force_stages, key=STAGE_ORDER.index))}")
    logger.info("=" * 70)

    ensure_dirs()

    # ── Pre-flight Validation ────────────────────────────────────────
    validate_prerequisites(synthetic=synthetic)

    # Resolve clustering hyperparameters
    if k is not None:
        run_k_search = False
        best_k = k
        logger.info(f"Using explicit k={k} (k-search disabled).")
    elif no_k_search:
        run_k_search = False
        best_k = DEFAULT_N_CLUSTERS
        logger.info(f"k-search disabled, using default k={DEFAULT_N_CLUSTERS}.")
    else:
        run_k_search = True
        best_k = None  # determined by search

    # ── MODULE 2: Embedding Processing ───────────────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("MODULE 2: Processing AlphaEarth Embeddings")
    logger.info("─" * 50)

    from src.m2_embedding_extraction import find_embedding_files, preprocess_embeddings

    emb_files = find_embedding_files(RAW_EMBEDDINGS_DIR)
    if not emb_files:
        logger.error("No embedding files found in data/raw/embeddings/")
        sys.exit(1)

    # Idempotency: check for existing processed embeddings
    raw_basename = os.path.splitext(os.path.basename(emb_files[0]))[0]
    expected_emb = os.path.join(PROC_EMBEDDINGS_DIR, f"{raw_basename}_norm.tif")
    cached_emb = find_cached(expected_emb, "Processed embeddings", "m2",
                             force_stages)

    if cached_emb:
        emb_path = cached_emb
    else:
        emb_path = preprocess_embeddings(emb_files[0])

    # ── MODULE 1: InSAR Ingestion ────────────────────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("MODULE 1: InSAR Data Ingestion")
    logger.info("─" * 50)

    from src.m1_insar_ingestion import preprocess_insar, generate_synthetic_insar
    from src.utils.geo_utils import load_raster, save_raster

    if synthetic:
        logger.info("Using SYNTHETIC InSAR data for pipeline testing.")
        emb_data, emb_profile = load_raster(emb_path)
        h, w = emb_data.shape[1], emb_data.shape[2]
        synth_velocity = generate_synthetic_insar((h, w))
        synth_path = os.path.join(RAW_INSAR_DIR, "synthetic_velocity.tif")
        save_raster(synth_path, synth_velocity, emb_profile, nodata=np.nan)
        vel_path = synth_path
    else:
        # Idempotency: check for existing reprojected velocity
        # M1 outputs either velocity_masked.tif (with coherence) or
        # velocity_reproj.tif (without)
        cached_vel = (
            find_cached(
                os.path.join(PROC_INSAR_DIR, "velocity_masked.tif"),
                "Masked InSAR velocity", "m1", force_stages,
            )
            or find_cached(
                os.path.join(PROC_INSAR_DIR, "velocity_reproj.tif"),
                "Reprojected InSAR velocity", "m1", force_stages,
            )
        )

        if cached_vel:
            vel_path = cached_vel
        else:
            vel_files = [f for f in os.listdir(RAW_INSAR_DIR)
                         if f.endswith((".tif", ".tiff"))]
            if not vel_files:
                logger.error("No InSAR files found in data/raw/insar/")
                sys.exit(1)

            vel_raw_path = os.path.join(RAW_INSAR_DIR, vel_files[0])
            coh_files = [f for f in vel_files if "coh" in f.lower()]
            coh_path = (os.path.join(RAW_INSAR_DIR, coh_files[0])
                        if coh_files else None)
            vel_path = preprocess_insar(vel_raw_path, coh_path)

    # ── MODULE 3: Data Alignment ─────────────────────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("MODULE 3: Aligning Datasets to Common Grid")
    logger.info("  (Embeddings and InSAR kept SEPARATE — no fusion)")
    logger.info("─" * 50)

    from src.m3_feature_fusion import align_datasets, prepare_embedding_features

    # Idempotency: check for existing aligned velocity
    expected_aligned = os.path.join(PROC_FUSED_DIR, "velocity_aligned.tif")
    cached_aligned = find_cached(expected_aligned, "Aligned velocity", "m3",
                                 force_stages)

    if cached_aligned:
        emb_path_aligned = emb_path
        vel_path_aligned = cached_aligned
    else:
        emb_path_aligned, vel_path_aligned = align_datasets(
            embedding_path=emb_path,
            insar_velocity_path=vel_path,
        )

    # Always prepare embedding features — needed in memory for M4 and M4B
    features, valid_mask, full_features, raster_profile = \
        prepare_embedding_features(emb_path_aligned, sample=True)

    logger.info(f"Embedding feature matrix: {full_features.shape[1]} dimensions")
    logger.info("InSAR velocity is NOT included in clustering features.")

    # ── MODULE 4: Stage 1 — Land Cover Clustering ────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("STAGE 1: Land Cover Clustering (Embeddings Only)")
    logger.info("  InSAR data plays NO role in this step.")
    logger.info("─" * 50)

    from src.m4_clustering import find_optimal_k, cluster_embeddings

    # Idempotency: check for existing cluster labels matching current method
    label_pattern = os.path.join(
        OUT_CLUSTERS_DIR, f"landcover_clusters_{method}_*.tif"
    )
    cached_labels = find_cached(label_pattern, "Cluster labels", "m4",
                                force_stages)

    if cached_labels:
        import rasterio
        with rasterio.open(cached_labels) as src:
            label_raster = src.read()

        # Safety: verify cached labels match the current embedding grid
        expected_shape = (1, valid_mask.shape[0], valid_mask.shape[1])
        if label_raster.shape != expected_shape:
            logger.warning(
                f"  Cached labels shape {label_raster.shape} != "
                f"embedding grid {expected_shape}. Rerunning clustering."
            )
            cached_labels = None  # fall through to clustering below

    if cached_labels:
        # Reconstruct flat label array from raster + valid_mask
        labels = label_raster[0][valid_mask]
        n_clusters = len(np.unique(labels[labels >= 0]))
        metrics = {
            "n_clusters": n_clusters,
            "n_valid_pixels": int((labels >= 0).sum()),
            "note": f"loaded from cache: {os.path.basename(cached_labels)}",
        }
        logger.info(f"  Loaded {n_clusters} clusters, "
                    f"{metrics['n_valid_pixels']:,} valid pixels")

    if not cached_labels:
        from src.utils.plotting import plot_elbow_silhouette

        if run_k_search and method in ("kmeans", "gmm"):
            logger.info("Searching for optimal k...")
            k_results = find_optimal_k(features, method=method)
            plot_elbow_silhouette(
                k_results["k_values"],
                k_results["inertias"],
                k_results["silhouettes"],
                save_path=os.path.join(OUT_FIGURES_DIR, "k_search.png"),
            )
            best_k = k_results["best_k"]

        labels, label_raster, metrics = cluster_embeddings(
            features, valid_mask, full_features, raster_profile,
            method=method,
            n_clusters=best_k,
        )

    # Resolve the label file path for pipeline state
    if cached_labels:
        label_file_path = cached_labels
    else:
        label_files = sorted(glob.glob(os.path.join(
            OUT_CLUSTERS_DIR, f"landcover_clusters_{method}_*.tif"
        )))
        label_file_path = label_files[-1] if label_files else None

    # ── CALIBRATION: Velocity Bias Correction ────────────────────────
    if not no_calibration and not synthetic:
        logger.info("\n" + "─" * 50)
        logger.info("CALIBRATION: InSAR Velocity Bias Correction")
        logger.info("  Using cluster labels to identify stable reference.")
        logger.info("─" * 50)

        vel_calibrated_path = os.path.join(PROC_FUSED_DIR,
                                           "velocity_calibrated.tif")
        cached_cal = find_cached(vel_calibrated_path, "Calibrated velocity",
                                 "cal", force_stages)

        if cached_cal:
            vel_for_overlay = cached_cal
        else:
            vel_for_overlay, ref_velocity, ref_cluster = \
                calibrate_velocity_field(
                    label_raster=label_raster,
                    velocity_path=vel_path_aligned,
                    output_path=vel_calibrated_path,
                    figures_dir=OUT_FIGURES_DIR,
                )
    else:
        vel_for_overlay = vel_path_aligned
        if synthetic:
            logger.info("Skipping calibration (synthetic data).")
        else:
            logger.info("Skipping calibration (--no-calibration).")

    # ── MODULE 4B: Stage 2 — InSAR Overlay ───────────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("STAGE 2: InSAR Velocity Overlay per Land Cover Cluster")
    logger.info("  Analyzing subsidence within each land cover type.")
    logger.info("─" * 50)

    from src.m4b_insar_overlay import run_insar_overlay

    overlay_results = run_insar_overlay(
        labels=labels,
        valid_mask=valid_mask,
        velocity_path=vel_for_overlay,
        profile=raster_profile,
    )

    # ── MODULE 5: Risk Interpretation ────────────────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("MODULE 5: Risk Interpretation & Visualization")
    logger.info("─" * 50)

    from src.m5_risk_interpretation import (
        create_risk_zones, vectorize_risk_zones,
        generate_report, generate_all_figures,
    )

    risk_path, risk_labels = create_risk_zones(
        labels=labels,
        severity=overlay_results["severity"],
        severity_names=overlay_results["severity_names"],
        valid_mask=valid_mask,
        profile=raster_profile,
    )

    gdf, vector_path = vectorize_risk_zones(risk_path)

    report_path = generate_report(
        cluster_stats=overlay_results["cluster_stats"],
        risk_matrix=overlay_results["risk_matrix"],
        risk_summary=overlay_results["risk_summary"],
        metrics=metrics,
        severity_names=overlay_results["severity_names"],
    )

    generate_all_figures(
        labels=labels,
        velocity_flat=overlay_results["velocity_flat"],
        severity=overlay_results["severity"],
        severity_names=overlay_results["severity_names"],
        label_raster=label_raster,
        profile=raster_profile,
        risk_summary=overlay_results["risk_summary"],
    )

    # ── Save Pipeline State ──────────────────────────────────────────
    save_pipeline_state(
        paths={
            "embeddings_norm": emb_path,
            "velocity_aligned": vel_path_aligned,
            "velocity_for_overlay": vel_for_overlay,
            "cluster_labels": label_file_path,
            "risk_zones": risk_path,
            "risk_zones_vector": vector_path,
            "risk_matrix_csv": os.path.join(OUT_CLUSTERS_DIR, "risk_matrix.csv"),
            "report": report_path,
        },
        config={
            "method": method,
            "n_clusters": int(metrics.get("n_clusters", 0)),
            "calibrated": not no_calibration and not synthetic,
            "synthetic": synthetic,
        },
        risk_summary_df=overlay_results["risk_summary"],
    )

    # ── Done ─────────────────────────────────────────────────────────
    logger.info("\n" + "=" * 70)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 70)
    logger.info(f"Outputs:")
    logger.info(f"  Land cover clusters:  {OUT_CLUSTERS_DIR}/")
    logger.info(f"  Subsidence severity:  {OUT_CLUSTERS_DIR}/subsidence_severity.tif")
    logger.info(f"  Combined labels:      {OUT_CLUSTERS_DIR}/combined_landcover_subsidence.tif")
    logger.info(f"  Calibrated velocity:  {vel_for_overlay}")
    logger.info(f"  Risk zone map:        {risk_path}")
    logger.info(f"  Risk zone vector:     {vector_path}")
    logger.info(f"  Risk matrix:          {OUT_CLUSTERS_DIR}/risk_matrix.csv")
    logger.info(f"  Report:               {report_path}")
    logger.info(f"  Figures:              {OUT_FIGURES_DIR}/")
    logger.info(f"  Pipeline state:       {PIPELINE_STATE_FILE}")
    logger.info(f"  Log:                  {log_file}")


# ══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="InSAR-Informed Subsidence Risk Zoning Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python run_full_pipeline.py                      "
            "# default run, skip cached steps\n"
            "  python run_full_pipeline.py --force              "
            "# reprocess everything from scratch\n"
            "  python run_full_pipeline.py --force-from m4      "
            "# redo clustering, calibration, overlay, figures\n"
            "  python run_full_pipeline.py --force-from cal     "
            "# recalibrate and rerun overlay + figures\n"
            "  python run_full_pipeline.py --method gmm --k 6   "
            "# try GMM with 6 clusters\n"
            "  python run_full_pipeline.py --no-calibration     "
            "# skip velocity bias correction\n"
            "\n"
            "Stage order for --force-from (cascades downstream):\n"
            "  m2 → m1 → m3 → m4 → cal → m4b → m5"
        ),
    )

    # Force flags
    force_group = parser.add_mutually_exclusive_group()
    force_group.add_argument(
        "--force", action="store_true",
        help="Bypass ALL caches — reprocess from scratch.",
    )
    force_group.add_argument(
        "--force-from", type=str, default=None,
        choices=STAGE_ORDER,
        metavar="STAGE",
        help="Rerun from STAGE onward (cascade). "
             "Choices: m2, m1, m3, m4, cal, m4b, m5.",
    )

    # Clustering hyperparameters
    parser.add_argument(
        "--method", type=str, default="kmeans",
        choices=["kmeans", "gmm", "hdbscan"],
        help="Clustering algorithm (default: kmeans).",
    )
    parser.add_argument(
        "--k", type=int, default=None,
        help="Explicit number of clusters. Skips k-search if set.",
    )
    parser.add_argument(
        "--no-k-search", action="store_true",
        help=f"Skip optimal-k search; use --k or default ({DEFAULT_N_CLUSTERS}).",
    )

    # Pipeline toggles
    parser.add_argument(
        "--no-calibration", action="store_true",
        help="Skip InSAR velocity bias calibration.",
    )
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Use synthetic InSAR data (for pipeline testing).",
    )

    args = parser.parse_args()
    main(
        force=args.force,
        force_from=args.force_from,
        method=args.method,
        k=args.k,
        no_k_search=args.no_k_search,
        no_calibration=args.no_calibration,
        synthetic=args.synthetic,
    )
