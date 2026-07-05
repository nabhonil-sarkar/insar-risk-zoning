# InSAR Subsidence Risk Zoning

Mapping ground-subsidence risk in Jakarta by combining satellite radar
interferometry (InSAR) with learned land-cover representations (Google
AlphaEarth embeddings).

Parts of northern Jakarta are sinking by more than 10 cm/year, driven mainly by
groundwater extraction. Displacement maps alone don't answer the planning
question, because risk depends on what sits on the sinking ground: the same
rate under a dense neighbourhood and under farmland are different problems.
This pipeline produces risk zones that account for both.

## Approach

Two independent satellite datasets, deliberately **never fused** into one
feature space:

```
Stage 1   AlphaEarth embeddings (64-D, 30 m)  ──▶  K-Means  ──▶  land-cover clusters
                                                                  (no InSAR involved)
Stage 2   Sentinel-1 InSAR velocity (mm/yr)   ──▶  calibrated, overlaid per cluster
                                                                  ──▶  subsidence severity

Risk  =  severity × exposure   (per-cluster exposure via an explicit lookup matrix)
```

The obvious alternative — concatenating the 64 embedding dimensions with the
1 velocity dimension and clustering the 65-D space — lets the embeddings drown
the velocity signal in any distance-based algorithm, regardless of weighting.
Keeping the stages separate means land cover is discovered on its own terms and
velocity remains a physically interpretable overlay. A side benefit surfaced in
practice: when a corrupted velocity file entered the pipeline, the clustering
was unaffected, because InSAR never touches Stage 1.

**Study area:** Jakarta metropolitan area, ~85 × 59 km. **Scale:** 5.6 M valid
pixels at 30 m; InSAR from 4 years of Sentinel-1 acquisitions (LiCSBAS SBAS
inversion, ~1 km effective resolution).

## Design notes

Decisions that shaped the implementation, with the reasoning:

- **Fingerprint-validated caching.** Every expensive stage writes a sidecar
  recording a hash of the settings it depends on, its resolved CLI parameters,
  and the identity (size + mtime) of each input file. A cached output is reused
  only if all three match; any mismatch logs the changed key and recomputes.
  Plain existence-checking had already caused silent reuse of stale results —
  e.g. a `--k 4` run picking up a six-cluster file.

- **Fail loudly on suspicious input.** The ingestion refuses to run if the raw
  data directory contains files with processed-product names (`calibrated`,
  `aligned`, `masked`, …), if more than one velocity candidate exists, or if a
  "raw" coastal file contains implausibly little nodata. Each guard corresponds
  to a failure mode that actually occurred or nearly did.

- **Geodesy handled explicitly.** Line-of-sight velocities are projected to
  vertical (v / cos θ, ~1.29× at this frame's incidence angle) before any
  thresholding; conversion state is stamped into GeoTIFF tags so a file's units
  are never ambiguous. Nodata is masked to NaN *before* resampling, and the
  ~1 km InSAR product is placed on the 30 m grid with nearest-neighbour
  resampling — interpolation would manufacture values that were never measured.

- **Calibration with self-checks.** InSAR velocities are relative; the pipeline
  anchors them by identifying the most internally consistent land-cover cluster
  as the stable reference. Because a low-variance cluster could itself be
  deforming, the calibration warns when the shift exceeds a configurable bound
  and reports the spread across the top reference candidates as an explicit
  uncertainty.

- **Classification that cannot fail silently.** Severity bins are half-open
  intervals covering the entire real line, pixels start unclassified rather
  than defaulting to "stable", and the classifier raises if any finite velocity
  escapes the bins. An earlier version classified the fastest-sinking pixels
  (< −100 mm/yr) as stable because of a gap in the bins; the regression test
  for that exact case is in the suite.

- **Coverage reported alongside risk.** Per-cluster statistics use only pixels
  with valid velocity and publish the coverage percentage, so a cluster rated
  from 3% coverage (open water, where InSAR decorrelates) is visibly
  distinguishable from one rated from 95%.

## Current status

Honest assessment as of v0.3.1: the pipeline machinery is sound, and the
per-cluster medians tell a physically coherent story (the dense-urban cluster
at −17 mm/yr, the stable reference at ~0). But **pixel-level severity is
currently noise-limited** — the source LiCSBAS run used a relaxed noise
threshold to preserve coverage under tropical decorrelation, and the resulting
per-pixel scatter (σ ≈ 40 mm/yr) exceeds the ±25 mm/yr classification
thresholds. The observed severity distribution is reproduced by a single
Gaussian to within a percentage point per class, which is the statistical way
of saying the per-pixel map currently classifies noise.

In progress: re-running the LiCSBAS inversion to export the velocity-uncertainty
layer (`vstd`), then masking pixels whose uncertainty exceeds the classification
thresholds (`notebooks/LiCSBAS_Jakarta_vstd_rerun.ipynb`). Planned next:
validation against published GNSS/levelling benchmarks for Jakarta, and deriving
cluster exposure from building-density data instead of manual assignment.

## Quick start

```bash
pip install -r requirements.txt

# place inputs:
#   data/raw/embeddings/  <- AlphaEarth annual export (see scripts/export_embeddings.py)
#   data/raw/insar/       <- one LiCSBAS velocity GeoTIFF

python scripts/run_full_pipeline.py            # full run; later runs reuse valid caches
python -m pytest tests/                        # test suite
```

Useful flags:

```
--force                 recompute everything
--force-from STAGE      recompute a stage and everything downstream
                        (m2 → m1 → m3 → m4 → cal → m4b → m5)
--method {kmeans,gmm,hdbscan}   clustering algorithm (HDBSCAN auto-falls back
                                to K-Means if it produces unusable results)
--k N                   fixed cluster count (skips the silhouette search)
--synthetic             synthetic InSAR, for exercising the pipeline without data
```

Outputs land in `data/output/`: cluster and severity rasters, risk-zone raster
and vector (GeoPackage), per-cluster statistics (CSV), figures, a text report,
a timestamped log, and `pipeline_state.json` — a machine-readable record of
paths, configuration and per-cluster results consumed by the downstream
sub-clustering tool.

## Data

| Dataset | Source | Resolution |
|---|---|---|
| InSAR velocity | Sentinel-1 via COMET-LiCSAR, LiCSBAS SBAS inversion | ~1 km |
| Land-cover embeddings | Google AlphaEarth (`GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`), Earth Engine | 30 m (native 10 m) |

## Repository layout

```
config/settings.py        every tunable parameter, fingerprint-tracked
src/m1 … m5               ingestion → alignment → clustering → overlay → risk
src/utils/stage_cache.py  cache fingerprinting
scripts/run_full_pipeline.py
scripts/subcluster_analysis.py   splits the highest-risk cluster into sub-populations
notebooks/                LiCSBAS processing (Colab)
tests/                    severity classifier, alignment, cache invalidation
docs/                     methodology document
```

## License

Copyright © 2026 Nabhonil Sarkar. All rights reserved. Provided for reference
and evaluation; no license is granted for use, modification or distribution.
For licensing or other inquiries, please get in touch.
