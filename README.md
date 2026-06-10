# InSAR-Informed Subsidence Risk Zoning

Two-stage discovery of subsidence risk zones by combining **InSAR displacement data** with **Google AlphaEarth Satellite Embeddings** — without fusing them.

## Overview

This project combines two independent satellite-derived views of the Earth's surface to map urban subsidence risk:

- **AlphaEarth Embeddings** encode *what's on the surface* — 64-dimensional learned representations of land cover, vegetation phenology, and built environment from Google's foundation model at 10 m resolution.
- **InSAR (Interferometric SAR)** measures *how fast the ground is moving* — line-of-sight displacement velocity in mm/year from Sentinel-1, processed via LiCSBAS.

The key methodological choice: these two datasets are **never combined into a single feature space**. Unsupervised clustering operates on embeddings alone to discover land cover types, then InSAR velocity is overlaid independently onto each cluster to characterize subsidence severity. This two-stage separation avoids the dimensionality imbalance where 64 embedding dimensions would dominate 1 velocity dimension in any distance-based algorithm.

The result is a risk map that captures both *what is on the surface* and *how fast it is sinking*, without either signal contaminating the other.

## Study Area

**Jakarta Metropolitan Area, Indonesia** — one of the most rapidly subsiding cities in the world, with documented rates reaching 10–25 cm/year in parts of North Jakarta, driven primarily by excessive groundwater extraction from deep aquifers. The study area covers approximately 85 × 59 km (106.45°E–107.22°E, 6.54°S–6.01°S).

## Pipeline Architecture

```
M2 Embeddings ──→ M3 Alignment ──→ M4 Clustering ──→ Calibration ──→ M4B Overlay ──→ M5 Risk
M1 InSAR ─────────────┘                                    │
                                                            ↓
                                                     Sub-clustering
```

| Module | File | Purpose |
|--------|------|---------|
| Config | `config/settings.py` | All tunable parameters in one place |
| M1 | `src/m1_insar_ingestion.py` | Load, reproject, coherence-mask InSAR velocity |
| M2 | `src/m2_embedding_extraction.py` | Load, reproject, normalize AlphaEarth embeddings |
| M3 | `src/m3_feature_fusion.py` | Align grids (no fusion — datasets stay separate) |
| M4 | `src/m4_clustering.py` | K-Means / GMM / HDBSCAN on embeddings only |
| Cal | `run_full_pipeline.py` | Auto-calibrate velocity bias using cluster labels |
| M4B | `src/m4b_insar_overlay.py` | Velocity stats + severity per cluster, risk matrix |
| M5 | `src/m5_risk_interpretation.py` | Risk zones, vectorization, report, figures |
| Sub | `scripts/subcluster_analysis.py` | Split high-risk clusters into sub-populations |

## Quick Start

```bash
# 1. Clone and install
git clone <repo-url>
cd insar-risk-zoning
pip install -r requirements.txt

# 2. Authenticate with Earth Engine (once)
earthengine authenticate

# 3. Export embeddings from GEE to Google Drive
python scripts/export_embeddings.py

# 4. Download the GeoTIFFs from Drive into data/raw/embeddings/
#    Place InSAR velocity GeoTIFF in data/raw/insar/

# 5. Run the pipeline
python scripts/run_full_pipeline.py
```

The pipeline will preprocess both datasets, cluster the embeddings, auto-calibrate the InSAR velocity, overlay subsidence statistics per cluster, and generate risk zones, figures, and a report.

## CLI Reference

The pipeline exposes all key parameters as command-line flags — no code edits needed to experiment:

```bash
# Default run (skips cached steps automatically)
python scripts/run_full_pipeline.py

# Reprocess everything from scratch
python scripts/run_full_pipeline.py --force

# Reprocess from clustering onward (keeps M1/M2/M3 cached)
python scripts/run_full_pipeline.py --force-from m4

# Just recalibrate and regenerate outputs
python scripts/run_full_pipeline.py --force-from cal

# Try GMM with 6 clusters instead of k-search
python scripts/run_full_pipeline.py --method gmm --k 6

# Try HDBSCAN (auto-falls back to K-Means if results are unusable)
python scripts/run_full_pipeline.py --method hdbscan

# Skip velocity calibration (if InSAR data is already bias-corrected)
python scripts/run_full_pipeline.py --no-calibration

# Test the pipeline without real InSAR data
python scripts/run_full_pipeline.py --synthetic
```

**Stage cascade for `--force-from`** (forces the named stage + everything downstream):
```
m2 → m1 → m3 → m4 → cal → m4b → m5
```

## Sub-clustering

After the main pipeline, the sub-clustering script can further divide the highest-risk cluster into sub-populations:

```bash
# Auto-selects highest-risk cluster from pipeline state
python scripts/subcluster_analysis.py

# Override target cluster or sub-k
python scripts/subcluster_analysis.py --cluster 2 --sub-k 3
```

This reads `pipeline_state.json` (written by the main pipeline) to discover file paths and risk levels — no hardcoded paths.

## Key Design Decisions

**Two-stage separation.** Clustering on embeddings alone, then overlaying InSAR, avoids dimensionality imbalance and ensures scientific defensibility. Neither dataset contaminates the other.

**Auto-calibration.** InSAR velocities are relative to an arbitrary reference point. The pipeline identifies the most stable land cover cluster (lowest velocity standard deviation) and shifts the entire field so stable areas read ~0 mm/yr. No manual intervention needed.

**Idempotency.** Each expensive step (reprojection, alignment, clustering) checks for existing output before running. Subsequent runs skip completed work automatically. Use `--force` or `--force-from` to override.

**HDBSCAN safety net.** HDBSCAN is O(n²) and can produce >50% noise on large datasets. The pipeline caps fitting at 50K samples, uses PCA dimensionality reduction, and auto-falls back to K-Means if HDBSCAN produces unusable results (too much noise or too few clusters).

**Centralized configuration.** Every tunable parameter lives in `config/settings.py` — subsidence thresholds, coherence masking, clustering hyperparameters, HDBSCAN safety limits, file paths. Nothing is hardcoded in module code.

## Outputs

After a full pipeline run, outputs are organized under `data/output/`:

```
data/output/
├── clusters/
│   ├── landcover_clusters_kmeans_k4.tif    # Cluster label raster
│   ├── subsidence_severity.tif             # Per-pixel severity classification
│   ├── combined_landcover_subsidence.tif   # Cluster × severity labels
│   ├── cluster_velocity_stats.csv          # Velocity stats per cluster
│   └── risk_matrix.csv                     # Cluster × severity pixel counts
├── risk_maps/
│   ├── risk_zones.tif                      # Risk zone raster (1-4 encoding)
│   ├── risk_zones.gpkg                     # Vectorized risk polygons
│   └── analysis_report.txt                 # Full text report
├── figures/
│   ├── k_search.png                        # Elbow + silhouette plots
│   ├── calibration_comparison.png          # Before/after velocity histograms
│   ├── landcover_clusters.png              # Cluster map
│   ├── velocity_per_cluster.png            # Box plots
│   ├── velocity_histograms.png             # Per-cluster distributions
│   └── risk_matrix_heatmap.png             # Risk matrix visualization
├── logs/
│   └── pipeline_20260609_143000.log        # Timestamped run log
└── pipeline_state.json                     # Machine-readable pipeline state
```

## Data Sources

| Dataset | Source | Resolution | License |
|---------|--------|------------|---------|
| AlphaEarth Embeddings | `GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL` via GEE | 30 m (native 10 m) | CC-BY 4.0 |
| InSAR Velocity | COMET-LiCSAR / LiCSBAS | ~1 km (10× multi-look) | Open |
| SAR Data | Sentinel-1 (ESA Copernicus) | ~5 m (IW SLC) | Open |

## Project Structure

```
insar-risk-zoning/
├── config/
│   └── settings.py                 # All parameters centralized here
├── src/
│   ├── m1_insar_ingestion.py       # InSAR preprocessing
│   ├── m2_embedding_extraction.py  # Embedding preprocessing
│   ├── m3_feature_fusion.py        # Grid alignment (no fusion)
│   ├── m4_clustering.py            # Unsupervised clustering
│   ├── m4b_insar_overlay.py        # InSAR analysis per cluster
│   ├── m5_risk_interpretation.py   # Risk zones + visualization
│   └── utils/
│       ├── geo_utils.py            # Raster I/O, reprojection, alignment
│       ├── plotting.py             # Matplotlib figure utilities
│       └── validation.py           # Clustering quality metrics
├── scripts/
│   ├── run_full_pipeline.py        # Main pipeline entry point
│   ├── subcluster_analysis.py      # Post-pipeline sub-clustering
│   ├── export_embeddings.py        # Earth Engine export
│   └── calibrate_velocity.py       # Standalone calibration (ad-hoc use)
├── tests/
│   ├── test_clustering.py
│   └── test_fusion.py
├── data/                           # Created by ensure_dirs(), gitignored
│   ├── raw/
│   ├── processed/
│   └── output/
├── docs/
│   └── InSAR_Subsidence_Risk_Zoning_Methodology.docx
├── requirements.txt
├── README.md
└── CHANGELOG.md
```

## Requirements

Python 3.10+ with the following packages (see `requirements.txt`):

- `earthengine-api`, `geemap` — Earth Engine access for embedding export
- `rasterio`, `geopandas`, `shapely` — geospatial I/O and vector operations
- `scikit-learn`, `hdbscan` — clustering algorithms and evaluation
- `numpy`, `pandas` — numerical computation
- `matplotlib`, `folium` — visualization

## License

MIT
