"""
Run the full InSAR Risk Zoning pipeline — Option B: Two-Stage Approach.

Stage 1: Cluster AlphaEarth embeddings to discover land cover types.
          No InSAR data is used in clustering.
Stage 2: Overlay InSAR velocity onto land cover clusters.
          Analyze subsidence patterns within each land cover context.
Risk:    Combine land cover type × subsidence severity.

Usage:
    python scripts/run_full_pipeline.py
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    ensure_dirs,
    RAW_EMBEDDINGS_DIR, RAW_INSAR_DIR,
    PROC_EMBEDDINGS_DIR, PROC_INSAR_DIR, PROC_FUSED_DIR,
    OUT_CLUSTERS_DIR, OUT_RISK_MAPS_DIR, OUT_FIGURES_DIR,
)

# ── Configuration ────────────────────────────────────────────────────────────
USE_SYNTHETIC_INSAR = False   # Set True only for testing without real data
CLUSTERING_METHOD = "kmeans"  # 'kmeans', 'gmm', or 'hdbscan'
N_CLUSTERS = 8               # Used for kmeans/gmm if RUN_K_SEARCH is False
RUN_K_SEARCH = True           # Search for optimal k
# ─────────────────────────────────────────────────────────────────────────────


def main():
    print("=" * 70)
    print("InSAR-INFORMED SUBSIDENCE RISK ZONING")
    print("Two-Stage Approach: Land Cover Clustering + InSAR Overlay")
    print("=" * 70)

    ensure_dirs()

    # ── MODULE 2: Embedding Processing ───────────────────────────────────
    print("\n" + "─" * 50)
    print("MODULE 2: Processing AlphaEarth Embeddings")
    print("─" * 50)

    from src.m2_embedding_extraction import find_embedding_files, preprocess_embeddings

    emb_files = find_embedding_files(RAW_EMBEDDINGS_DIR)
    if not emb_files:
        print("ERROR: No embedding files found in data/raw/embeddings/")
        sys.exit(1)

    emb_path = preprocess_embeddings(emb_files[0])

    # ── MODULE 1: InSAR Ingestion ────────────────────────────────────────
    print("\n" + "─" * 50)
    print("MODULE 1: InSAR Data Ingestion")
    print("─" * 50)

    from src.m1_insar_ingestion import preprocess_insar, generate_synthetic_insar
    from src.utils.geo_utils import load_raster, save_raster

    if USE_SYNTHETIC_INSAR:
        print("Using SYNTHETIC InSAR data for pipeline testing.")
        emb_data, emb_profile = load_raster(emb_path)
        h, w = emb_data.shape[1], emb_data.shape[2]
        synth_velocity = generate_synthetic_insar((h, w))
        synth_path = os.path.join(RAW_INSAR_DIR, "synthetic_velocity.tif")
        save_raster(synth_path, synth_velocity, emb_profile, nodata=np.nan)
        vel_path = synth_path
    else:
        vel_files = [f for f in os.listdir(RAW_INSAR_DIR)
                     if f.endswith((".tif", ".tiff"))]
        if not vel_files:
            print("ERROR: No InSAR files found in data/raw/insar/")
            sys.exit(1)

        vel_raw_path = os.path.join(RAW_INSAR_DIR, vel_files[0])
        coh_files = [f for f in vel_files if "coh" in f.lower()]
        coh_path = os.path.join(RAW_INSAR_DIR, coh_files[0]) if coh_files else None
        vel_path = preprocess_insar(vel_raw_path, coh_path)

    # ── MODULE 3: Data Alignment ─────────────────────────────────────────
    print("\n" + "─" * 50)
    print("MODULE 3: Aligning Datasets to Common Grid")
    print("  (Embeddings and InSAR kept SEPARATE — no fusion)")
    print("─" * 50)

    from src.m3_feature_fusion import align_datasets, prepare_embedding_features

    emb_path_aligned, vel_path_aligned = align_datasets(
        embedding_path=emb_path,
        insar_velocity_path=vel_path,
    )

    # Prepare embedding features for clustering (Stage 1)
    features, valid_mask, full_features, raster_profile = prepare_embedding_features(
        emb_path_aligned, sample=True,
    )

    print(f"\nEmbedding feature matrix: {full_features.shape[1]} dimensions")
    print("InSAR velocity is NOT included in clustering features.")

    # ── MODULE 4: Stage 1 — Land Cover Clustering ────────────────────────
    print("\n" + "─" * 50)
    print("STAGE 1: Land Cover Clustering (Embeddings Only)")
    print("  InSAR data plays NO role in this step.")
    print("─" * 50)

    from src.m4_clustering import find_optimal_k, cluster_embeddings
    from src.utils.plotting import plot_elbow_silhouette

    if RUN_K_SEARCH and CLUSTERING_METHOD in ("kmeans", "gmm"):
        print("Searching for optimal k...")
        k_results = find_optimal_k(features, method=CLUSTERING_METHOD)
        plot_elbow_silhouette(
            k_results["k_values"],
            k_results["inertias"],
            k_results["silhouettes"],
            save_path=os.path.join(OUT_FIGURES_DIR, "k_search.png"),
        )
        best_k = k_results["best_k"]
    else:
        best_k = N_CLUSTERS

    labels, label_raster, metrics = cluster_embeddings(
        features, valid_mask, full_features, raster_profile,
        method=CLUSTERING_METHOD,
        n_clusters=best_k,
    )

    # ── MODULE 4B: Stage 2 — InSAR Overlay ───────────────────────────────
    print("\n" + "─" * 50)
    print("STAGE 2: InSAR Velocity Overlay per Land Cover Cluster")
    print("  Analyzing subsidence within each land cover type.")
    print("─" * 50)

    from src.m4b_insar_overlay import run_insar_overlay

    overlay_results = run_insar_overlay(
        labels=labels,
        valid_mask=valid_mask,
        velocity_path=vel_path_aligned,
        profile=raster_profile,
    )

    # ── MODULE 5: Risk Interpretation ────────────────────────────────────
    print("\n" + "─" * 50)
    print("MODULE 5: Risk Interpretation & Visualization")
    print("─" * 50)

    from src.m5_risk_interpretation import (
        create_risk_zones, vectorize_risk_zones,
        generate_report, generate_all_figures,
    )

    # Create risk zones
    risk_path, risk_labels = create_risk_zones(
        labels=labels,
        severity=overlay_results["severity"],
        severity_names=overlay_results["severity_names"],
        valid_mask=valid_mask,
        profile=raster_profile,
    )

    # Vectorize
    gdf, vector_path = vectorize_risk_zones(risk_path)

    # Report
    report_path = generate_report(
        cluster_stats=overlay_results["cluster_stats"],
        risk_matrix=overlay_results["risk_matrix"],
        risk_summary=overlay_results["risk_summary"],
        metrics=metrics,
        severity_names=overlay_results["severity_names"],
    )

    # Figures
    generate_all_figures(
        labels=labels,
        velocity_flat=overlay_results["velocity_flat"],
        severity=overlay_results["severity"],
        severity_names=overlay_results["severity_names"],
        label_raster=label_raster,
        profile=raster_profile,
        risk_summary=overlay_results["risk_summary"],
    )

    # ── Done ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    print("=" * 70)
    print(f"\nOutputs:")
    print(f"  Land cover clusters:  {OUT_CLUSTERS_DIR}/")
    print(f"  Subsidence severity:  {OUT_CLUSTERS_DIR}/subsidence_severity.tif")
    print(f"  Combined labels:      {OUT_CLUSTERS_DIR}/combined_landcover_subsidence.tif")
    print(f"  Risk zone map:        {risk_path}")
    print(f"  Risk zone vector:     {vector_path}")
    print(f"  Risk matrix:          {OUT_CLUSTERS_DIR}/risk_matrix.csv")
    print(f"  Report:               {report_path}")
    print(f"  Figures:              {OUT_FIGURES_DIR}/")


if __name__ == "__main__":
    main()
