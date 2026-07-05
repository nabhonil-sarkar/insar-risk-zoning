# Changelog

All notable changes to the InSAR Risk Zoning pipeline are documented here.

## [0.3.1] — 2026-07-06

Reliability release: fingerprint-validated caching, data-integrity guards, and a
risk-statistics correction. Driven by a second external code review plus one real
data-poisoning incident caught (and now prevented) by the new guards.

### Fingerprint-validated stage caching (new `src/utils/stage_cache.py`)

Cache invalidation was previously existence-only: changing a setting, a CLI
argument, or an upstream input silently reused stale outputs. Every cached stage
(M2, M1, M3, M4, calibration) now writes a JSON sidecar recording a SHA-256
fingerprint of the settings it depends on, its CLI-resolved parameters, and the
size+mtime identity of each input file. On the next run the cache is used only if
all three match; any mismatch logs the changed key and recomputes.

- Fixes the k-cache bug: requesting `--k 4` after a `--k 6` run no longer reuses
  the six-cluster labels (k is fingerprinted; auto-search fingerprints the search
  config and accepts only sidecars written under the same config).
- Fixes the calibration-staleness bug: the labels raster is a fingerprinted input
  to calibration, so any re-clustering invalidates the calibrated velocity.
- Clustering quality metrics (silhouette, Davies-Bouldin) persist in the sidecar
  and are reloaded on cached runs instead of being lost.
- Covered by `tests/test_stage_cache.py` (10 tests), including a meta-test that
  validates the stage→settings dependency table against the real `settings.py`,
  so a renamed setting fails CI rather than silently fingerprinting nothing.

### Data-integrity guards (`m1_insar_ingestion.py`, `run_full_pipeline.py`)

- **Deprecated `calibrate_velocity.py`.** The legacy calibrate-and-copy-back
  workflow would now re-apply the LOS→vertical factor to already-converted data.
  The script refuses to run and explains the integrated replacement.
- **Distinct-file LOS conversion.** M1 no longer overwrites the reprojected file
  in place; each stage writes its own product (`velocity_reproj.tif` →
  `velocity_vertical.tif` → `velocity_masked.tif`) and stamps unit metadata
  (reference frame, incidence angle, scale factor) into GeoTIFF tags.
- **Raw-directory purity guard.** Discovery refuses to run if any file in
  `data/raw/insar/` carries processed-product vocabulary (`calibrated`,
  `aligned`, `vertical`, `masked`, `reproj`). Added after a stale calibrated
  artifact from the deprecated workflow was silently ingested by a real run.
- **Safe file discovery.** Sorted listing, coherence and synthetic files excluded
  from velocity candidates, hard refusal when more than one candidate remains.
- **Sentinel nodata masked to NaN before any resampling**, with a content-level
  heuristic that warns when a supposedly raw coastal file contains implausibly
  little nodata (the signature of an already-processed input).
- **InSAR resampling is now configurable and defaults to nearest** — appropriate
  for a ~1 km product placed on a 30 m grid, and it eliminates blended-value
  halos around nodata gaps entirely.

### Risk-statistics denominator fix (`m4b_insar_overlay.py`, `m5`, state)

Per-cluster subsidence percentages were computed over all cluster pixels,
including those with no valid velocity — silently under-rating clusters with
poor InSAR coverage and contradicting the risk matrix (which already excluded
them). Both now use the valid-velocity denominator, and a new
`pct_velocity_coverage` column reports coverage explicitly so sparse clusters
are visibly flagged instead of quietly misclassified. This resolves the
20.2% vs 32.1% discrepancy between the methodology document's Table 1 and §5.2
(the same statistic under two denominators).

### Provenance and selection correctness

- HDBSCAN fallback outputs are saved under the method actually used (K-Means),
  with both requested and used methods recorded in metrics and pipeline state.
- Embedding selection is driven by a new `ANALYSIS_YEAR` setting and fails
  loudly on a year mismatch, instead of taking the first file of a sorted glob.
- `cluster_embeddings` returns the exact label path it wrote, replacing a
  `sorted(glob)[-1]` lookup that could pick the wrong file.
- The exposure guard errors out if `CLUSTER_EXPOSURE` references nonexistent
  cluster IDs or if the labels file changed since exposure was assigned
  (`--accept-exposure` bypasses after re-verification).
- `INSAR_ORBIT_DIRECTION` corrected to `ASCENDING` (frame 098A; the A is
  ascending) — documentation had said descending.

### Runtime robustness

- Non-interactive matplotlib backend forced at pipeline entry; plotting helpers
  close figures instead of calling `show()`, which could block the pipeline on
  GUI backends.
- Removed matplotlib calls deprecated/removed in 3.9+ (`boxplot(labels=)`,
  `plt.cm.get_cmap`); the code now runs on both old and current matplotlib.
- `requirements.txt` pinned with version bounds reflecting actual code
  requirements (notably: standalone `hdbscan` is required for
  `approximate_predict`, which sklearn's port lacks).
- Console log handler tolerant of legacy Windows terminal encodings.

### Known state at release

Pixel-level severity classification is currently noise-limited: the May LiCSBAS
run used a relaxed velocity-std threshold (`-v 200`), and the resulting field's
per-cluster σ of 32–53 mm/yr exceeds the ±25 mm/yr classification thresholds
(the observed severity distribution is reproduced by a single Gaussian to within
~1 point per class). Cluster medians remain physically coherent (Cluster 0:
−16.9 mm/yr, Cluster 3: −0.1 mm/yr). A LiCSBAS re-run exporting the `vstd`
uncertainty layer is in progress (`notebooks/LiCSBAS_Jakarta_vstd_rerun.ipynb`);
vstd-based quality masking in M1 is the next change.

## [0.3.0] — 2026-06-12

Scientific-rigor release driven by external code review. Two critical bugs fixed (one of which mislabelled the fastest-sinking pixels as stable), the risk model now genuinely uses land cover context, and velocities are converted from line-of-sight to vertical terms.

### Critical: Severity binning bug (`m4b_insar_overlay.py`, `settings.py`)

**Problem:** Severity was initialized to 0 ("stable") and the threshold bins did not cover the full velocity range. The "rapid" bin was (-100, -25) — any pixel subsiding faster than -100 mm/yr fell outside every bin and silently stayed classified as stable. North Jakarta has documented rates beyond -100 mm/yr, so the fastest-sinking pixels in the study area were labelled the safest. Velocities above +2 mm/yr had the same gap.

**Fix (three layers of defense):**
- `SUBSIDENCE_THRESHOLDS` bins are now half-open `[lo, hi)` and jointly cover the entire real line: rapid = `(-inf, -25)`, stable = `(-2, +inf)`. Uplift above +2 mm/yr is deliberately folded into stable and reported separately (`UPLIFT_REPORT_THRESHOLD`).
- Severity initialization changed from 0 to -1 so unclassified pixels are visible, never silently stable.
- Runtime assertion: `classify_subsidence_severity()` raises `ValueError` if any finite velocity escapes classification, so a future config regression fails loudly instead of corrupting results.

### Critical: Risk model now uses land cover context (`m5_risk_interpretation.py`, `settings.py`)

**Problem:** The README and report claimed risk = land cover context × subsidence severity, but `create_risk_zones()` mapped severity directly to risk — the cluster labels were passed in and never used. Stage 1 contributed nothing to the final risk raster except calibration, undermining the entire justification for the two-stage design.

**Fix:** Exposure-weighted risk via an explicit severity × exposure lookup:
- `CLUSTER_EXPOSURE` (settings): analyst assigns low/medium/high exposure per cluster after inspecting the cluster map.
- `EXPOSURE_RISK_MATRIX` (settings): 4×3 lookup mapping (severity, exposure) → risk code. High exposure promotes risk one level (moderate subsidence under dense urban → very high); low exposure demotes one level.
- Graceful degradation: with no exposure assigned, all clusters default to medium, which reproduces the previous severity-only mapping exactly. A warning instructs the analyst to assign exposure and rerun with `--force-from m4b`.

### LOS-to-vertical velocity conversion (`m1_insar_ingestion.py`, `settings.py`)

**Problem:** InSAR measures line-of-sight displacement, but the severity thresholds were framed as vertical subsidence rates. At Sentinel-1's ~39° incidence, LOS underestimates vertical motion by ~22%.

**Fix:** New `los_to_vertical()` in M1 projects velocities (v_vert = v_LOS / cos θ) immediately after reprojection, so every downstream product — calibration, severity, risk — operates in vertical terms. Controlled by `INSAR_VELOCITY_IS_LOS` and `INSAR_INCIDENCE_ANGLE_DEG` (default 39°, replace with frame-specific value from LiCSAR metadata). Assumes purely vertical deformation — appropriate for groundwater-driven subsidence; ascending/descending decomposition noted as future work.

### Calibration sanity checks (`run_full_pipeline.py`, `settings.py`)

**Problem:** Selecting the lowest-velocity-std cluster as the stable reference could calibrate the bias into the data if that cluster were subsiding uniformly.

**Fix:** Two guards:
- Shift-magnitude warning if |reference velocity| exceeds `CALIBRATION_MAX_SHIFT` (15 mm/yr) — the "stable" cluster may itself be deforming.
- Sensitivity report comparing the top-3 reference candidates (lowest std); if their medians disagree beyond `CALIBRATION_CANDIDATE_TOLERANCE` (3 mm/yr), the spread is flagged as calibration uncertainty.

### Config consistency (`settings.py`)

- `ACTIVE_ROI` now points to `JAKARTA_ROI`, which now matches the methodology document's coordinates (106.45–107.22°E, 6.54–6.01°S, ~85 × 59 km). Previously three different ROIs existed across code, settings, and documentation.
- Deleted dead `INSAR_WEIGHT = 1.5` left over from the abandoned single-stage fusion approach.

### Test suite (`tests/`)

- **New `test_severity.py`** — 8 tests for the severity classifier, including the exact regression case (-150 mm/yr must be rapid, never stable), half-open boundary behavior, full-real-line coverage, NaN handling, and a deliberately gappy config that must raise. These tests would have caught the binning bug.
- **New `test_alignment.py`** — replaces the stale `test_fusion.py` (which tested the removed fusion-era `normalize_features` API). Verifies feature matrix shape, finiteness, no re-normalization in M3 (M2 is the single authority), and sampling caps.
- **Deleted `test_fusion.py`.**

### Documentation

- README: added Limitations section (single LOS geometry, relative velocities, resolution mismatch, threshold conventions), exposure-weighted risk explanation, calibration sanity check documentation, corrected project structure.

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
