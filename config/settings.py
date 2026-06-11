"""
Centralized configuration for the InSAR Risk Zoning project.
All tunable parameters live here — ROI, dates, clustering params, file paths.
"""

import os

# =============================================================================
# PROJECT PATHS
# =============================================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")
OUTPUT_DIR = os.path.join(DATA_DIR, "output")

# Raw subdirectories
RAW_EMBEDDINGS_DIR = os.path.join(RAW_DIR, "embeddings")
RAW_INSAR_DIR = os.path.join(RAW_DIR, "insar")
RAW_ANCILLARY_DIR = os.path.join(RAW_DIR, "ancillary")

# Processed subdirectories
PROC_EMBEDDINGS_DIR = os.path.join(PROCESSED_DIR, "embeddings")
PROC_INSAR_DIR = os.path.join(PROCESSED_DIR, "insar")
PROC_FUSED_DIR = os.path.join(PROCESSED_DIR, "fused")

# Output subdirectories
OUT_CLUSTERS_DIR = os.path.join(OUTPUT_DIR, "clusters")
OUT_RISK_MAPS_DIR = os.path.join(OUTPUT_DIR, "risk_maps")
OUT_FIGURES_DIR = os.path.join(OUTPUT_DIR, "figures")
OUT_LOG_DIR = os.path.join(OUTPUT_DIR, "logs")

# Pipeline state: written by run_full_pipeline, read by sub-clustering etc.
PIPELINE_STATE_FILE = os.path.join(OUTPUT_DIR, "pipeline_state.json")

# =============================================================================
# REGION OF INTEREST — Jakarta
# =============================================================================
# [min_lon, min_lat, max_lon, max_lat]
# Full study area — Jakarta Metropolitan Area (~85 x 59 km), matching README
JAKARTA_ROI = [106.45, -6.54, 107.22, -6.01]

# Smaller test area for development (North Jakarta coastal strip)
JAKARTA_TEST_ROI = [106.78, -6.15, 106.92, -6.08]

# Production runs use the full ROI. Switch to JAKARTA_TEST_ROI only for
# fast development iterations.
ACTIVE_ROI = JAKARTA_ROI

# =============================================================================
# EARTH ENGINE EXPORT
# =============================================================================
EMBEDDING_COLLECTION_ID = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
EMBEDDING_YEARS = [2020, 2023]
EXPORT_FOLDER = "InSAR_Risk_Zoning_Project"
EXPORT_SCALE = 10  # meters
EXPORT_CRS = "EPSG:4326"

# =============================================================================
# InSAR PARAMETERS
# =============================================================================
# Sentinel-1 parameters
INSAR_ORBIT_DIRECTION = "DESCENDING"
INSAR_POLARIZATION = "VV"

# LOS -> vertical projection. LiCSBAS velocities are line-of-sight; the
# severity thresholds are vertical rates. v_vert = v_los / cos(incidence).
# Assumes purely vertical deformation — reasonable for groundwater-driven
# subsidence in Jakarta. For rigorous separation of vertical/horizontal,
# use ascending + descending decomposition (future work).
INSAR_VELOCITY_IS_LOS = True
# Sentinel-1 IW incidence spans ~29-46 deg across the swath; 39 deg is the
# mid-swath default. Replace with the frame-specific value from the LiCSAR
# metadata (or use the per-pixel incidence raster) for best accuracy.
INSAR_INCIDENCE_ANGLE_DEG = 39.0

# Coherence masking: pixels below this threshold are discarded as unreliable
COHERENCE_THRESHOLD = 0.3

# Calibration: minimum valid pixels required for a cluster to qualify as the
# stable reference (avoids selecting a tiny cluster with low std by chance)
CALIBRATION_MIN_CLUSTER_PIXELS = 100

# Calibration sanity checks: warn if the computed reference shift exceeds
# this magnitude (mm/yr) — a large shift may mean the "stable" reference
# cluster is itself deforming uniformly.
CALIBRATION_MAX_SHIFT = 15.0
# Warn if the medians of the top reference candidates (lowest std) disagree
# by more than this (mm/yr) — the calibration would then be sensitive to
# reference choice.
CALIBRATION_CANDIDATE_TOLERANCE = 3.0

# Velocity thresholds (mm/year), in VERTICAL terms (see LOS correction, M1).
# Bins are half-open [lo, hi) and cover the entire real line so no velocity
# can escape classification. Uplift (> +2 mm/yr) is folded into "stable" for
# risk purposes but counted and reported separately by M4B.
SUBSIDENCE_THRESHOLDS = {
    "stable":   (-2.0, float("inf")),
    "slow":     (-10.0, -2.0),
    "moderate": (-25.0, -10.0),
    "rapid":    (float("-inf"), -25.0),
}

# Uplift faster than this (mm/yr) is reported separately in the severity
# distribution printout (still classified "stable" for risk).
UPLIFT_REPORT_THRESHOLD = 2.0

# =============================================================================
# RISK MODEL — exposure-weighted severity
# =============================================================================
# Land cover context modifies subsidence severity: the same -30 mm/yr is a
# higher risk under dense urban fabric than under bare ground. Clusters are
# unsupervised, so exposure must be assigned manually after inspecting
# figures/landcover_clusters.png. Keys are cluster IDs from the current run.
#
# Example after inspection:
#   CLUSTER_EXPOSURE = {0: "high", 1: "low", 2: "medium", 3: "high"}
CLUSTER_EXPOSURE = {}

# Exposure assumed for clusters not listed in CLUSTER_EXPOSURE. With the
# default matrix below, "medium" for all clusters reproduces the plain
# severity -> risk mapping (1, 2, 3, 4).
DEFAULT_EXPOSURE = "medium"

# Risk lookup: rows = severity (0=stable, 1=slow, 2=moderate, 3=rapid),
# columns = exposure (low, medium, high). Values = risk code
# (1=low, 2=moderate, 3=high, 4=very_high).
# Rationale: high exposure promotes risk one level (moderate subsidence under
# dense urban fabric -> very high); low exposure demotes one level (rapid
# subsidence on unbuilt land remains high — still a hazard signal — but not
# very high). Stable ground is low risk regardless of what sits on it.
EXPOSURE_RISK_MATRIX = [
    # exposure:  low  medium  high
    [1, 1, 1],   # stable
    [1, 2, 2],   # slow
    [2, 3, 4],   # moderate
    [3, 4, 4],   # rapid
]

# =============================================================================
# FEATURE FUSION
# =============================================================================
COMMON_RESOLUTION = 30  # meters
COMMON_CRS = "EPSG:32748"  # UTM Zone 48S (Jakarta)
NORMALIZATION_METHOD = "zscore"  # 'zscore' or 'minmax'

# =============================================================================
# CLUSTERING PARAMETERS
# =============================================================================
CLUSTERING_METHODS = ["kmeans", "gmm", "hdbscan"]
DEFAULT_METHOD = "kmeans"

# K-Means / GMM
K_RANGE = range(4, 16)  # test cluster counts from 4 to 15
DEFAULT_N_CLUSTERS = 8   # fallback when k-search is disabled
RANDOM_STATE = 42
KMEANS_BATCH_SIZE = 10_000  # MiniBatchKMeans batch size

# HDBSCAN
HDBSCAN_MIN_CLUSTER_SIZE = 500
HDBSCAN_MIN_SAMPLES = 50
HDBSCAN_MAX_FIT_SAMPLES = 50_000   # cap for HDBSCAN fitting (O(n²) algorithm)
HDBSCAN_PCA_COMPONENTS = 20        # PCA dims before HDBSCAN distance computation

# HDBSCAN safety net — if results are unusable, fall back to K-Means
HDBSCAN_MAX_NOISE_FRACTION = 0.50  # >50% noise triggers fallback
HDBSCAN_MIN_USABLE_CLUSTERS = 2    # <2 clusters triggers fallback
HDBSCAN_FALLBACK_K = 4             # K-Means k when HDBSCAN fails

# Evaluation: silhouette scoring is O(n²), so subsample for large datasets
SILHOUETTE_MAX_SAMPLES = 50_000

# Sampling: for large rasters, cluster on a random sample then predict full image
MAX_CLUSTERING_SAMPLES = 500_000
SAMPLE_FRACTION = 0.1  # fraction of valid pixels to sample

# =============================================================================
# SUB-CLUSTERING PARAMETERS
# =============================================================================
SUB_K_RANGE = [2, 3, 4]          # k values to test during sub-cluster search
SUBCLUSTER_MAX_SAMPLES = 200_000  # subsample cap for sub-clustering

# =============================================================================
# VISUALIZATION
# =============================================================================
RISK_COLORMAP = {
    "low": "#2ecc71",
    "moderate": "#f39c12",
    "high": "#e74c3c",
    "very_high": "#8e44ad",
    "ecological": "#3498db",
}

MAP_CENTER = [-6.2, 106.85]  # Jakarta center [lat, lon]
MAP_ZOOM = 12


def ensure_dirs():
    """Create all project directories if they don't exist."""
    dirs = [
        RAW_EMBEDDINGS_DIR, RAW_INSAR_DIR, RAW_ANCILLARY_DIR,
        PROC_EMBEDDINGS_DIR, PROC_INSAR_DIR, PROC_FUSED_DIR,
        OUT_CLUSTERS_DIR, OUT_RISK_MAPS_DIR, OUT_FIGURES_DIR, OUT_LOG_DIR,
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    print(f"All directories verified under {PROJECT_ROOT}")
