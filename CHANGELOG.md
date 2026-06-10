# Changelog

All notable changes to the InSAR Risk Zoning pipeline are documented here.

## [0.2.0] — 2026-06-11

Five production-hardening fixes applied across the pipeline. Every module touched is backward-compatible — existing data outputs remain valid.

### Fix 1: Idempotency + Calibration Integration (`run_full_pipeline.py`)

**Problem:** Calibration lived in a standalone script. Running a fresh clone required: run pipeline → manually run calibrate_velocity.py → manually replace the velocity file → rerun the entire pipeline. No step was skippable on reruns.

**Changes:**
- Integrated velocity calibration between M4 (clustering) and M4B (overlay). The pipeline auto-identifies the most stable cluster, computes the reference bias, and shifts the velocity field — no manual steps.
- Added idempotency: each expensive step (M2 reprojection, M1 reprojection, M3 alignment, M4 clustering, calibration) checks for existing output before running. Subsequent runs skip completed work.
- Added `--force` flag to bypass all caches.
- Added `--force-from STAGE` for granular cache control — forces the named stage plus everything downstream. Stage order: `m2 → m1 → m3 → m4 → cal → m4b → m5`.
- Added `--method`, `--k`, `--no-k-search`, `--no-calibration`, `--synthetic` CLI flags so clustering hyperparameters are runtime-configurable without code edits.
- Added pre-flight validation: fails fast if raw data directories are empty.
- Replaced `print()` with Python `logging` module — dual output to console (clean) and timestamped log file (`data/output/logs/`).
- Added shape safety check: cached M4 labels are validated against the current embedding grid before use.

**Files:** `run_full_pipeline.py`

### Fix 2: Double Normalization Cleanup (`m3_feature_fusion.py`)

**Problem:** Embeddings were z-score normalized twice — once in M2 (`preprocess_embeddings`) and again in M3 (`prepare_embedding_features`). On already-z-scored data the second pass is approximately a no-op, but it wastes a full copy of the 64-band raster and is conceptually wrong.

**Changes:**
- Removed `normalize_embedding_features()` function from M3 entirely.
- Removed its call in `prepare_embedding_features()`.
- Removed the unused `NORMALIZATION_METHOD` import.
- Updated docstrings to clarify that M2 is the single normalization authority.

**Files:** `m3_feature_fusion.py`

### Fix 3: State-Aware Sub-clustering (`subcluster_analysis.py`, `run_full_pipeline.py`)

**Problem:** The sub-clustering script hardcoded file paths (`landcover_clusters_kmeans_k4.tif`), target cluster (`labels_raster == 0`), and non-target cluster IDs (`for c in [1, 2, 3]`). It broke if the pipeline produced different filenames or cluster counts.

**Changes:**
- Pipeline now writes `pipeline_state.json` at the end of every run, containing all output paths, configuration, and per-cluster risk summaries.
- Sub-clustering reads this state file instead of hardcoding anything.
- Auto-selects the highest-risk cluster based on the risk summary (overridable with `--cluster N`).
- All cluster IDs, legend entries, and spatial map colors are dynamic.
- Sub-clusters are sorted by severity (index 0 = worst subsidence) regardless of the internal k-means label assignment.
- Added `--state`, `--cluster`, `--sub-k` CLI flags.

**Files:** `subcluster_analysis.py`, `run_full_pipeline.py`

### Fix 4: HDBSCAN Safety Net (`m4_clustering.py`)

**Problem:** `run_hdbscan()` received all 5.5M pixels directly. HDBSCAN is O(n²) in distance computation — this would crash from memory or run for days. If it produced >50% noise or <2 clusters, the broken labels passed silently to downstream modules.

**Changes:**
- Four-step safety pipeline inside `run_hdbscan()`:
  1. PCA dimensionality reduction (64 → 20 dims, fitted on training subsample)
  2. Subsample to 50K for HDBSCAN fitting
  3. Fit with `prediction_data=True`
  4. `approximate_predict` to label all 5.5M pixels via the condensed tree
- Quality assessment: `run_hdbscan()` returns a `quality` dict with `n_clusters`, `noise_fraction`, and `usable` flag.
- Automatic K-Means fallback: if HDBSCAN is unusable (>50% noise or <2 clusters), `cluster_embeddings()` falls back to K-Means with a configurable k.
- Fallback is recorded in the metrics dict (`hdbscan_fallback: True`) so the report captures what happened.
- Fixed the call site: all three methods now follow the same `fit(subsample) → predict(full)` pattern.

**Files:** `m4_clustering.py`

### Fix 5: Hardcoded Values → settings.py (`settings.py` + 4 modules)

**Problem:** Magic numbers were scattered across modules: coherence threshold (0.3 in m1), batch sizes (10,000 in m4, appearing 5 times), silhouette sample caps (inconsistent 30K vs 50K), HDBSCAN safety constants, pipeline paths, sub-clustering defaults.

**Changes:**
- Added 14 constants to `config/settings.py`:
  - InSAR: `COHERENCE_THRESHOLD`, `CALIBRATION_MIN_CLUSTER_PIXELS`
  - Clustering: `DEFAULT_N_CLUSTERS`, `KMEANS_BATCH_SIZE`, `SILHOUETTE_MAX_SAMPLES`
  - HDBSCAN: `HDBSCAN_MAX_FIT_SAMPLES`, `HDBSCAN_PCA_COMPONENTS`, `HDBSCAN_MAX_NOISE_FRACTION`, `HDBSCAN_MIN_USABLE_CLUSTERS`, `HDBSCAN_FALLBACK_K`
  - Pipeline: `OUT_LOG_DIR`, `PIPELINE_STATE_FILE`
  - Sub-clustering: `SUB_K_RANGE`, `SUBCLUSTER_MAX_SAMPLES`
- Updated `ensure_dirs()` to include `OUT_LOG_DIR`.
- Fixed the silhouette sample inconsistency (both sites now use `SILHOUETTE_MAX_SAMPLES = 50_000`).
- Updated imports in `m1_insar_ingestion.py`, `m4_clustering.py`, `run_full_pipeline.py`, `subcluster_analysis.py`.

**Files:** `settings.py`, `m1_insar_ingestion.py`, `m4_clustering.py`, `run_full_pipeline.py`, `subcluster_analysis.py`

---

## [0.1.0] — 2026-06-01

Initial working pipeline with two-stage approach (land cover clustering + InSAR overlay), velocity calibration as standalone script, sub-clustering analysis, and methodology documentation.
