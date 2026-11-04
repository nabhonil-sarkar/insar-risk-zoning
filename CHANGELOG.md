# Changelog

Material milestones; see the [README](README.md) for current public status.
Read only entries relevant to the task. Historical outcomes are not current
execution instructions. Artifact hashes are recorded once in the registry below.

## [Unreleased — 0.3.2 recovery]

- Added array-only AlphaEarth tile-seam and northwest-exclusion diagnostics.
  Nine synthetic test cases passed on 5 November 2026, including planted
  steps, control ties and insufficient support. No real seam result yet.

- Repository publication cleanup: preserve frozen notebook bytes across platforms,
  make the v13 real-data test optional only when its local bundle is absent, and
  distinguish local research outputs from files distributed by Git. The model
  comparison is parked: the owner has no full-resolution Pléiades access.
  Verification: 166 tests passed locally; 165 passed and one skipped without data.

### 2026-11-03 — exhaustive Wayback search and separate Pléiades footprint check

- Registered the extension before querying missing endpoints; reconciled 81
  release checks with the original 13 snapshots (93 distinct relevant releases).
  Zero new endpoints or pairs. Original inputs and gates unchanged. Checkpoint
  hashes and site totals verified; do not score or commission Wayback reviews.
- Separate [Airbus catalogue](https://space-solutions.airbus.com/imagery/how-to-order-imagery-and-data/archive-preview-tool/)
  check: 207/114 Pléiades segments intersect the ROI in 2020/2025. One or more
  footprints fully cover each patch in both years at 287/300 sites (48/49
  development/evaluation blocks). Geometry only, not full-resolution access
  or interpretable imagery. No images ordered or downloaded. **166 tests passed**.

### 2026-11-03 — frozen spatial benchmark; independent-image support insufficient

- Registered endpoint label rubric, eligibility, spatial splits, NDVI/NDBI
  baseline vs baseline + embedding distance, paired block uncertainty and
  decision gates before sampling. Selected three nominal 90 m patches in each
  of 100 buffered 5 km blocks without opening predictor pixels.
- Audited 13 [Wayback](https://livingatlas.arcgis.com/wayback/) releases by
  whole-patch source footprint, capture date, sensor and resolution: 154
  candidate sites for 2020, 150 for 2025, 94 paired. Development 40 sites/16
  blocks; evaluation 54/22. Minimum 20 blocks per split is impossible for v1.
  Among the 34 development blocks lacking pairs, 11 had only 2020 candidates,
  nine only 2025 and 14 neither. No replacements, labels, fits or test scores.
- Indexed 92 and 129 Sentinel-2 Collection 1 L2A candidate scenes for the
  respective June–September seasons; no pixel-level baseline or clear-coverage
  claim. Full suite: **156 passed**.

### 2026-11-03 — six full-area annual rasters and seven continuous change maps

- Acquired the required stored 20 m blocks from the pinned annual GCS objects.
  All six 64-band int8 rasters pass grid, unique assignment, seam/edge, saved
  byte readback and frozen sample checks. Each has 5,619,719 valid interior
  and 4,825 clipped exterior centres. No legacy pixels were substituted.
- Whole-grid 2023 audit: exact agreement on all 64 decoded axes everywhere
  inside; 2,650 exterior cells were valid only in the old export.
- Seven decoded all-axis cosine-distance GeoTIFFs passed support/range checks
  and all 84 frozen point comparisons. Their manifest records hashes for six
  annual rasters, six QA sidecars and seven maps. Interpretation/ablation and
  exposure remain open. Added a diagnostic 2020–2025 preview; **152 tests passed**.

### 2026-11-03 — 20 m reproduction, six-year edge pilot and published-source audit

- Preregistered two stages at the original 1e-7 tolerance. All 18 holdout
  and 54 broader 2023 vectors matched exactly across 64 axes. The broader
  sample contained no masked cells, so its mask gate **did not pass**.
- Separate GCS-only southern-edge pilot: 12 interior and six exterior centres
  per year, using the frozen geometry. At the six exterior 2023 centres GCS
  had data at all six; EE masked three. All 12 interior vectors matched.
  Twelve joint interior cells supported all five adjacent and two longer
  comparisons. No citywide inference. Full-grid compressed 20 m payload
  estimate: 5,046,130,848 bytes (12 files, no retries, not downloaded).
- Verified the complete 4,042,230-row [Zenodo CSV](https://zenodo.org/records/15786357).
  Of 312,374 ROI rows, 40,661 repeated coordinates had inconsistent records;
  none were exact duplicate rows. Withhold conflicting locations and require
  finite VLM and positive finite SD: 220,625 eligible; 48,883 in mainland
  DKI, 10,051 in North. No interpolation, independent validation, or risk claim.
  Full suite: **144 passed**.

### 2026-11-03 — six-year AlphaEarth inventory and bounded 2023 comparison

- The official spatial index and 12 live headers confirm two intersecting
  10 m EPSG:32748 tiles per year on the frozen 30 m grid. Stored GCS object
  generations, sizes and provider MD5s (not full-download checksums). The
  third 2025 bbox candidate starts at easting 745760 m; the frozen grid ends
  at 745746.39 m. This resolves the October candidate count.
- Read 86,686,626 TIFF bytes for the pixel test. Sampled two fixed 3×3
  patterns on opposite tiles, decoded A00–A63 and compared native nearest at
  exact reference centres. All 18 had joint support; **0/18** passed 1e-7.
  Per-cell maximum absolute errors ranged from 0.023622 to 0.058131.
  Decision: `hold_do_not_mix`. No annual exports or scientific map.
- Added reproducible, bounded GCS pilot with no-overwrite outputs. Full suite:
  **140 passed**. Original raster and six-year contract hashes verified unchanged.

### 2026-10-08 — accepted scope and documentation consolidation

- Owner accepted Jakarta urban change/exposure with audited published subsidence
  context, retaining our InSAR work as a relative-pattern case study. The
  fallback is urban change alone if published deformation fails audit.
  Unanswered emails no longer block the main workstream. Recipients/send dates
  are unverified; no assistant transmission occurred.
- Verified CC BY 4.0 metadata and anonymous HTTP 206 access for
  [Java VLM/EW](https://zenodo.org/records/15786357):
  `Java_VLM_EW.csv`, 446,891,387 bytes, provider MD5
  `02ef53d4cb962e2c044fbf0d096824df`. The associated
  [Science Advances study](https://doi.org/10.1126/sciadv.aec0172) covers
  2017–2023. Sample columns include VLM/EW and SD in cm/year; repeated
  coordinates require review. Full-file integrity, Jakarta coverage and method
  checks remain pending. Published GNSS referencing is not independent
  validation of our stack. [Zenodo 19456870](https://zenodo.org/records/19456870)
  offers ancillary layers; its same-frame LiCSBAS/kriging product is a
  comparison source, not ground truth. (C29, C34)
- Verified anonymous AlphaEarth 2020–2025/48S listings and all 178 2025 tile
  headers using 64 KiB ranges: zero errors; three ROI bounding-box candidates.
  Google's [GCS guide](https://developers.google.com/earth-engine/guides/aef_on_gcs_readme)
  confirms 2025 availability and nonlinear decoding. This supersedes August's
  availability/authentication blocker; no complete annual tile was downloaded.
  All-year inventory, pixel support and 2023 equivalence are still required. (C33)
- Shortened context to live decisions, README to public scope/setup, and this
  file to milestones, frozen controls and the complete existing checksum
  registry. Folded the 34-item challenge register into the relevant entries.
  No new status file, software change or methodology edit. Documentation checks do not rerun
  or supersede the last recorded **134 passing tests**.

The three 2025 candidates share prefix
`gs://alphaearth_foundations/satellite_embedding/v1/annual/2025/48S/`:

| File | Approximate full size |
|---|---|
| `x4rxvwvibg07oqoga-0000008192-0000000000.tiff` | 3.40 GB |
| `x4rxvwvibg07oqoga-0000008192-0000008192.tiff` | 2.78 GB |
| `x9zg0k81erdlnq6mr-0000008192-0000008192.tiff` | 3.33 GB |

Each is 8,192 × 8,192, EPSG:32748, 64 int8 bands, nodata -128.
Bounding-box overlap is not verified valid-pixel coverage.

### 2026-08-10 — annual-change preflight and validation package

- Froze all calendar years 2020–2025 around the authenticated 2023 raster:
  782,795,253 bytes, 2,858 × 1,968 EPSG:4326 grid, official `A00`–`A63`
  order. Corrected the previous `A01`–`A64` labels; cosine change preserves
  invalid/zero masks. The contract requires five adjacent-year and two
  cumulative comparisons, joint support, no independent annual normalization,
  stability/sensitivity, ancillary interpretation and baseline ablation.
  Exporter gained exact-grid output, inventory-only mode, provenance and atomic
  failure for missing years. At this checkpoint the catalogue ended at 2024,
  API/credentials were absent and no export was submitted. Suite: 134 tests.
- Built checksum-gated BIG/ITB/DKI ground-validation protocol, inventory
  template and unsigned request; prepared without sending. Metadata screening
  and prospective temporal/LOS/uncertainty rules precede comparison.
  The exact v13 no-rate footprint is a valid 21-part MultiPolygon of 380 cells
  and 100.456701 km2. Dissolving tiny district overlaps changes summed area by
  only 0.0254 m2. No resampling, buffering or simplification. (C21, C29)
- Consolidated project records and moved only six approved ignored cache
  directories to the Recycle Bin: 89 files, 1,128,982 bytes. Scientific inputs,
  outputs and intentional Git changes were preserved. (C11)

### 2026-08-07–10 — descending candidate and reference sensitivity

- V11 frame `047D_09652_111009` retained 347/349 pairs, all 76 acquisitions,
  no bridges and complete triangle participation. Catalogue dates
  2020-01-10–2023-06-11 cover 85.4795% of the requested four years, failing
  the frozen 95% span rule; no inversion. An erroneous requirement for optional
  `n_ifg_noloop` was removed; the custom all-edge audit remains authoritative.
  Recovery archive verified. (C22, C23)
- Descriptive attribution excluded only the impossible requested-span
  condition: 380/618 North cells passed other gates; complete triangle
  participation remained the main local limiter (397/618; 71.9330% area).
  This justified a separately preregistered exact-window v13, not a v11 pass.
- V13 reused the verified regenerated checkpoint, passed its cell-6 checkpoint
  and prospective inversion gate, and exported/audited six rasters on the
  154 × 106 grid. Exactly 380 cells cover 68.3903% of North; 95.6252% of
  passing area is eight-connected. District coverage: Cilincing 55.3049%,
  Penjaringan 49.5456%, Tanjung Priok 90.1078%, Pademangan 88.6709%,
  Koja 75.8883%, Kelapa Gading 100%. Every cell has finite velocity/uncertainty,
  zero gaps/loop errors and survives descriptive 5/10/15/20 mm/year masks.
  Non-fatal tiling-option warnings were resolved by grid/content/hash and
  raw-array verification. (C24, C25, C28)
- V13 internal LOS diagnostics: rate -27.2843 to +5.3764, median -3.2125;
  formal `vstd` 1.0256–1.7884, median 1.2707 mm/year; median coherence
  0.5550; median `n_unw` 341. The 9.4 MB final archive and all 75 members
  passed independent local audit. These are computational results, not
  validated vertical or absolute rates.
- V14 schema 1 stopped because the automatic reference had phase in only
  344/347 UNWs; no pairs were removed. Schema 2 froze the control and three
  quality-only references with 347/347 support, changing only `12ref.txt`
  in isolated step-13/14 reruns. West `63:64/36:37`, east `92:93/37:38`,
  south `56:57/66:67` archives completed and were independently audited.
- Every reference preserved the 380-cell mask, strict `vstd < 1.80` and
  centred-pattern gates; east/south centred RMSE was 0.0187/0.1218 mm/year.
  Control/west/east/south medians were -3.2125, +0.9537, -5.3038 and -7.0916:
  **8.0453 mm/year spread versus the frozen 3 mm/year limit**. Outcome:
  `relative_pattern_only`. Raw arrays, configuration, candidate archives and
  summary reproduce the result; ground anchoring remains absent. (C04, C26, C27)

### 2026-08-07–10 — alternative-source feasibility

- Public GNSS archive `10.5281/zenodo.7775016` was inadequate: CJKT is in
  unmeasured v9 North, while strict-cell match CTGR is outside DKI and overlaps
  only 2020–2021. Prepared the no-rate v9 attachment: valid 19-part,
  169,823-byte MultiPolygon covering 193.9086 km2. (C21)
- Implemented NISAR v12 inventory/QA and resumable, range-checked downloads
  for four provisional GUNWs (two each on tracks 10/18; 9,483,321,344 bytes).
  Supports both Rev-E grid layouts; only a 2026 coverage/coherence test.
  Downloads remain approval-gated after cell 4. It cannot establish velocity,
  loop closure, wavelength causality or historical-stack validation. (C30)
- Deferred 2024–mid-2025 orbit-98 processing and ALOS-2 pending inventory,
  licensing/cost and prospective method decisions. (C31, C32)

### 2026-08-06–07 — regenerated ascending stack and failed correction

- V9 uniformly regenerated all 609 UNWs from unfiltered wrapped phase.
  Atomic size-checked downloads gained up to six retry/backoff attempts after
  a transient `IncompleteRead` at 125/609; checksummed checkpoints survive
  Colab restarts. GACOS covered only 78/120 dates and was not applied
  partially. (C16, C17)
- Network pass: step 11/12 rejected 8/34 pairs (42 unique; 6.90%), leaving
  567 edges, 118/120 acquisitions, 99.45% span, edge/image 4.805, cycle rank
  450, no bridges and complete triangle participation. Diagnostic inversion,
  uncertainty, matched exports and 7.8 MB final archive completed.
- Finite `vel/vstd`: 11,771/16,324 cells (72.11%); median `vstd` 1.603,
  coherence 0.299. Strict zero-gap/zero-loop mask: 2,477 cells (15.17% grid),
  rate -22.09 to +16.61, median `vstd` 1.382 mm/year, coherence 0.491.
  Exact intersections with 267 official kelurahan features cover
  193.9086/650.78 km2 mainland DKI (29.80%): South 63.97%, West 38.32%,
  Central 31.84%, East 20.40%, North 0%. Largest of 54 strict patches:
  83.00% of pixels. Citywide/north-coast promotion failed. (C18)
- North: 361/477 centres have no finite output; the remaining 116 fail
  loops only (108), gaps+loops (5), or gaps only (3). Loop-only median
  coherence 0.630 and `n_unw=459` rule out a simple coherence-mask fix.
  Global rejections concentrate at 20220527, 20231118, 20220807 and 20210601,
  but removed pairs cannot explain retained-loop failures. (C19)
- Exact reconstruction of 990 retained triangles reproduced `n_loop_err`
  at all 16,324 cells: 1,398 North events across 122 triangles and 113
  loop-failing cells. Median residual 6.289 rad; 97.07% within 0.5 rad of one
  cycle. Top 20 loops account for 53.65%; strongest triangle
  `20230203_20230227_20230311`. Participation does not uniquely identify
  a faulty pair; manual deletion was rejected.
- V10 tested whole-SNAPHU-component integer corrections with five deterministic
  held-out folds. Ten stable non-zero integers failed every fold: whole-grid
  events 289,302 → 341,822 (+18.2%); North 2,438 → 3,020 (+23.9%);
  100,668 clean events became errors. These are held-out evaluation counts,
  distinct from the v9 retained-loop census. Stopped before materialization;
  no corrected stack/inversion. Frozen rule rejected; no post-hoc tuning. (C20)

### 2026-08-06 — loop failures, grid repair and ROI decision

- V6 added omitted recommended `--multi_prime`; factor 2 still rejected
  576/609 (94.6%), retaining 12.5% of acquisitions and 11.5% period span.
  Of 1,128 loops, 98.0% exceeded 1.5 rad; median 5.06 rad. Reference-related
  rejections were zero. Missing multi-prime was not a sufficient explanation.
- V7 factor 5 rejected 558/609 (91.6%), retaining 23 dates in disconnected
  17/3/3 components. Median loop RMS 4.73 rad; 96.9% exceeded 1.5;
  factor-2/5 correlation 0.9943. Apparent 92.1% overall temporal reach was
  misleading; v8 switched to largest-component gates. Raising thresholds
  to roughly 4.58/4.25 rad merely to pass was rejected. (C14)
- V8 crop guards evolved from identical-grid/coefficient checks to an
  all-raster pixel-space audit: 1,223 rasters, 1,002 compatible, 221 alternate
  UNWs; all CCs/ancillaries passed. Harmless drift ~1.46e-11 pixel differs
  from the alternate family's 0.213082-pixel error. CEDA reproduced the seam;
  pinned LiCSBAS checked dimensions, not transforms. No pair was discarded.
- The alternate grid follows a pixel-centre/outer-edge fencepost relation
  (reference width/2860, height/2790). LiCSAR commit
  `e1cb8724643a664a728d69d43904d70221cca7ba` (2023-09-18) introduced
  nearest-grid matching. Reproducing it left 1,967,436 valid phase values
  unchanged in the representative pair. Schema 4 accepts exactly this
  221-member family with zero ROI array-value change; other mismatches retain
  the 0.01-pixel limit. Grid normalization resolves provenance, not phase
  inconsistency: 93% of reference-only full-frame loops still failed. (C13)
- ROI factor 5: 8 step-11 failures (all 20220527) plus 165 step-12 failures;
  436 pairs retained, 113/120 acquisitions, 96.2% span. Rejection 28.4%
  exceeded the frozen 25% cap (173 versus maximum 152), so no inversion.
  Median RMS 1.65 rad; 58.3% of 1,110 loops above 1.5. Cropping rescued
  385 pairs with no new rejection. Legacy-family rejection remained 47.1%
  versus 17.8% after array-preserving repair. (C15)
- Literature review found no universal 25% LiCSBAS rejection cap. V8 remains
  failed; prospective v9 replaced that local safeguard with connectivity,
  redundancy and loop participation while retaining 1.5 rad. The
  [original method](https://doi.org/10.3390/rs12030424) requires sufficient
  retained observations rather than a universal rejected fraction.

### 2026-07-28–08-02 — input and software recovery

- Rejected incomplete 5.96 GB archive: 22 pair folders, 18 UNWs, zero CCs.
  Recovered/inventoried 609 complete pairs in a verified 6.40 GB archive,
  reproduced in a clean Colab restore. Corrected the checksum transcription
  `dbb7c3db...` to the runtime-verified registry value. (C12)
- Factor 10 (~1.106 km) completed, but finite coverage 28.6%, median coherence
  0.090, median `vstd` 14.38 mm/year and extreme rates prevented promotion.
  Factor 2 (~221 m, 2 August) completed structurally but rejected 577 pairs,
  used only 15 images, retained 29.07% finite coverage, median coherence
  0.0724, median `vstd` 48.59 and rates -573.52 to +697.47 mm/year.
  Both remained diagnostic. (C14)
- Completed matched uncertainty ingestion/scaling, nodata handling, inclusive
  masking and retained/rejected/missing counts; missing coherence is invalid.
  Added ambiguity guards, multi-output cache invalidation, atomic versioned
  state, input validator, bounded dependencies, packaging/CLI and synthetic
  smoke test. Test suite grew from 25 to 73.
- Consolidated canonical documents/dependencies, removed obsolete scripts and
  duplicate handoffs/requirements, quarantined pre-`vstd` inputs, and isolated
  sensitivity outputs by multilook suffix. Began independent AlphaEarth
  context/change work; withdrew noisy July risk claims. (C10, C11)

## [0.3.1] — 2026-07-06

- Replaced existence-only caches with settings/CLI/input fingerprints;
  corrected stale cluster-count/calibration reuse and preserved clustering
  metrics. Dependency-table tests catch renamed settings. (C05)
- Deprecated calibrate-and-copy-back to prevent double LOS conversion.
  Added distinct tagged outputs, raw-directory purity, deterministic
  unambiguous discovery, nodata-before-resampling and nearest alignment.
  Corrected frame 098A to ascending. (C03, C06, C07)
- Changed cluster statistics to valid-velocity denominators and explicit
  coverage, resolving the 20.2% versus 32.1% discrepancy. (C08)
- Corrected year/label selection, HDBSCAN fallback provenance and exposure
  invalidation after reclustering. Added noninteractive plotting, modern
  matplotlib calls, dependency bounds and Windows logging compatibility.
- Scientific limitation: relaxed earlier `-v 200` output had 32–53 mm/year
  within-cluster scatter, comparable to/exceeding severity thresholds.
  Requested matched `vstd`; attractive cluster summaries did not validate
  pixel risk. July artifacts were subsequently quarantined. (C10)

## [0.3.0] — 2026-06-12

- Fixed extreme subsidence silently labelled stable: half-open bins now cover
  the real line, initialize to -1 and assert completeness. Rapid is below
  -25; stable starts at -2; uplift above +2 mm/year is separately reported.
  Added extreme/boundary/NaN regression tests. (C01)
- Replaced severity-only risk with explicit 4 × 3 severity/exposure mapping.
  Unassigned exposure retains a warned diagnostic fallback; later production
  enforcement requires every cluster. (C02)
- Added conditional LOS-to-vertical conversion `v/cos(theta)` with explicit
  assumptions/metadata; it assumes vertical-only motion and cannot by itself
  validate the descending candidate. Added 15 mm/year reference-shift warning
  and top-three-reference spread check at 3 mm/year. (C03, C04)
- Unified the ROI, removed unused fusion weighting, replaced obsolete fusion
  tests with alignment tests, and documented geometry/resolution limitations.

## [0.2.0] — 2026-06-11

- Integrated calibration, existence-based resumability (superseded in 0.3.1),
  force/from-stage and clustering CLI options, preflight, logging and grid checks.
- Removed double embedding normalization; M2 is the sole preprocessing owner.
  State-driven subclustering replaced hardcoded paths/labels, with severity-
  ordered outputs and overrides. (C09)
- Bounded HDBSCAN with 64→20 PCA, 50k training sample and approximate
  prediction; unusable results (>50% noise or <2 clusters) fall back to K-Means.
  Centralized coherence, batch, sampling, fallback and output settings.

## [0.1.0] — 2026-06-01

Initial two-stage embedding clustering/InSAR overlay pipeline, standalone
calibration, subclustering and methodology documentation.

## Frozen experiment controls

These are audit rules for completed/deferred branches, not permission to resume.

- **Shared v9/v11/v13:** LiCSBAS
  `a145e6c4217b29eb7348ea95630454a099809098`; `licsar_extra`
  `557a50811b03a722c7a326c62ea0375949f0b7e4`; fixed ROI, factor 5
  (~553 m), common unfiltered phase, SNAPHU, Goldstein, one cascade,
  consistency 0.3, no partial GACOS, multi-prime, loop threshold 1.5 rad.
- **V8:** maximum rejected fraction 25%; largest component ≥75% acquisitions
  and ≥90% requested span. Failure prohibits cells 10–13 and ROI factor 2.
- **V9 structural:** largest component ≥90% acquisitions and ≥95% span,
  edge/image ≥2, zero bridges, every edge in a triangle. Pair rejection
  fraction is descriptive. Pixel mask requires finite `vel/vstd`,
  `n_gap=0`, `n_loop_err=0`.
- **V10:** MintPy `297aa16018b93ba0d247413a56855cf012b8a7bb`;
  deterministic whole-component `2*pi*k`, 1,110 triangles after frozen
  step-11 exclusions, five SHA-256-assigned held-out folds. Identical integer
  estimates, improvement in every fold, no new error, unchanged wrapped
  phase/masks/components, all 113 North loop-failures recovered and all 2,477
  baseline strict cells preserved were mandatory before materialization.
  No random/per-pixel edits or pair removal. Failure prohibits cells 8–12.
- **V11/v13 local:** unchanged structural graph criteria at each finite pixel
  and zero loop errors. Require ≥50% North area, ≥25% in every district and
  ≥75% passing area in one eight-connected patch. V13 additionally requires
  finite post-inversion `vel/vstd` and zero gaps/loop errors.
  `vstd` 5/10/15/20 and area 40/50/60%, district 15/25/35% sweeps are
  descriptive, not alternate acceptance rules. V13's period is explicitly
  2020-01-10–2023-06-11; it does not reclassify v11's four-year failure.
- **V14:** select references without rates; finite non-zero phase in all 347
  UNWs, zero gaps/loop errors. Preserve 380 cells and maximum strict
  `vstd <=5` mm/year. Centred Pearson/Spearman ≥0.99; RMSE ≤0.5,
  p95 absolute difference ≤1.0, maximum ≤3.0 mm/year. Reference median
  spread ≤3.0 mm/year required for zero-level pass; otherwise pattern-only
  if pattern gates pass. Keep schema-1 evidence; schema 2 supersedes it.
- **NISAR v12:** coherence 0.30; each track's two products cover ≥95% of
  mainland North; each ≥50% usable, joint ≥40%, largest component ≥80% of
  usable pixels in each. Coherence 0.20/0.40 is descriptive. Inventory/QA
  through cell 4 only; explicit approval before cell-5 download.

## Artifact checksums

Preserved verbatim from the pre-consolidation registry; these identify
historical artifacts, not fresh integrity checks. Verify before reuse. Grouped
rows retain hashes in the same order as their labels. Source-script hashes are
historical snapshots and may change with later implementation.

### Historical input and ascending-branch evidence

| Artifact | SHA-256 |
|---|---|
| Verified historical GEOC archive | `dbb7c3ab5291b752f28e7b2ffb8f54c80f8c2f8979d237155ffe7f49d5ad4b5c` |
| Factor-2 final diagnostic archive | `e0b883b0c00917165d257e02b84393ca9c97fe4bdf020c2818b21e48f21436d8` |
| Factor-2 multi-prime step-12 diagnostic | `c2059017f281aff0a9b55b7bdfc6c0fbf0ca071c3d0594b005dea201bcc1016` |
| Factor-5 full-frame step-12 diagnostic | `b7aa30d05a274bc530237a6770ac8e30ab8e3e268d366e794d8a52d160d72b8b` |
| V8 grid-family diagnostic | `c96fa207c393fd986b5641a6f588e5d91b2a7e79c17e3a5292298f5283ec558a` |
| V8 notebook | `843029d99b59f341a4ea9d5e54f1186317e9b3611474da51762e7f0f16f306ec` |
| V8 fixed-ROI failure diagnostic | `6b35956d3c416b7d63e16c2682d6a9a1ebca926120a7a37a650022782dc9ec8d` |
| V9 notebook | `11d9b2cd11de67961d2064df7684503511f2bb28828986b3668c3cae9e920924` |
| V9 regenerated checkpoint | `3329cd9c75d5c96e604f0c9b3b950fe127018bfebc06d2c19f9426b3fb234efb` |
| V9 checkpoint inventory | `cf06e2235374b36aa8d5ca790adf8356ebd8b1d40daf0aa2e45e739a016e52af` |
| V9 step-12 diagnostic | `b5f31f8e5d88c6b27394af357687535025503f963c856b94a63fc76659311c68` |
| V9 results archive | `99f38ec03233f900a6c28ee629e279df8aed427e18c70c8101a9e4f094bbd23d` |
| Official DKI boundary | `7bb4dd0589cec8bd64e8930c94b1835116701b6148f7b7de183e61196593c540` |

### V9 QC and attribution

| Artifact | SHA-256 |
|---|---|
| Strict mask | `850cd07c62963758fe4a8a2a7eed2d6463ad8e9eb68dbb33060bc761918454a9` |
| Strict-masked velocity | `76d890449fedf13b126a81bac465931e394721c39471920e34cdc63c7197f8fd` |
| Strict-mask summary | `a242b8039d1e7d204a9fddab0ca7174011f61d446dfc79141b99797315600392` |
| Spatial-coverage map / summary | `0336e13d0eec5f0ad88f895f05f1ddd69e8f34f40a0daa6c26e9fe45319b7aab` / `e030c1a121350a005455e16ea9164a06f579e10186c47a0f6f677a80a97bd85c` |
| North-failure map / summary | `2ef611fb683a0ffe8ccb3c13615780906ee17a5db13f25a2b0e049ba6105dad8` / `ee6c2f58815a1fcd32409b3adbbc56c0da1eeada1742abaaff8e373cfa8c2d21` |
| Rejected-pair CSV | `434c7b668714e43d84941817469a1f873a68229c928c2ccee2e1894f00cb6b91` |
| Rejected-pair acquisition CSV | `ce5d8cd6c3c737fbd116188511e919dff11ea4aeabdcc8cbe0550b651f1d7f8a` |
| Rejected-pair plot / summary | `52d46832bfac667b8a355853715c0cc75525af2df59b90d06f664413f23285a4` / `4cf46dd2e210e56a61671b7a284be09c08382b93ce8617ce5299518e5f33bde2` |
| Retained-loop CSV | `f0b0c5722bd05b879c1f140ffed1242cfc93b3455e30e2be51c34252171060ed` |
| Retained-loop pair CSV | `ad53c360b5d31bfb7f96f0963d6e56460b6053c185b3e8cc41d08d73c9150eb4` |
| Retained-loop acquisition CSV | `a9c2baa571496de399d2b9b13d2e95edf01c962ae22afd3f69090f127f0da72e` |
| Retained-loop plot / summary | `5ea619a12ee1e907b3139aee660f4cfe543abcd72781f0b8cb70cb0b48d3f4ed` / `879a6626d7e65acf056663ce7e5aaca97ed73242071c29d0cbbee15383f6da3f` |
| V9 no-rate footprint | `8b14da5f04909eb073ff7041ed8e227a039b4fd506b5e9a46f2843e094394bd6` |

### V10–V12

| Artifact | SHA-256 |
|---|---|
| V10 notebook | `455a0862636b637335d06c99eec4c0b09380567ec18c580c887169a61654e3d0` |
| V10 held-out report | `c4436169aae04a65d163cda2cca1784472abe6029e5f98801fe37a86f72f66da` |
| V10 stable ledger | `0bc08e50dc173c8306ed4788cc08c41db5cff0e41a27470ba58191bf1b957e94` |
| V10 configuration fingerprint | `d7d2b61c10a84c36747c22c59932f7bc49e7d4541ac704408a67ecff328f0788` |
| V11 notebook | `119e495f1c6a7b1dbba6640997f5e9756d86e61679e1217223a57c1f2f35e067` |
| V11 recovery archive | `cfa62c3031527b94f2098c938a797fe95ab06f4f77aa6a63d650af8d3874d856` |
| V11 attribution report / map | `e457a5635867f5a0cc604ef48a9e26239640292ef0cb5e3b0ed5b8127c61f3bc` / `235269b4f908c6d990851bc2397c50c9aae338c14a96fe85800c274cfdf7f2cb` |
| V12 notebook | `94129bb634ba7df9b1504eb0a92a5a6543c69c7c35c690aadfcaf3ad796471ce` |

### V13

| Artifact | SHA-256 |
|---|---|
| V13 notebook | `e3b14fe6e05a4a741e3e4102b82c82e669a2041bbe7f8cc4bdf92968976f0448` |
| Regenerated checkpoint | `0a3d1378234eef757fdb07341abb96dc2934612d4a4124c8282cf40b619565b9` |
| Checkpoint configuration | `8aa6272c2f629684926140b864361cb15ff3a3c5c988c3bad0cd015b817984f9` |
| Step-12 diagnostic | `b117e83ddb78a5c55585e621bb09626b94354bc0ad7418a9e3491fa28206cf17` |
| Final results archive | `54afa2dc1255af1dc04727ea0e6730e6975f6edbcf897744ef0724975d468187` |
| QC summary / manifest | `f000d159f6e8f551ad8531342675203c4a4289109872cdf09e790d3c2dce6c51` / `8c3c2bf86c3a661285ae3e035cbc0f765ed56a6d72e08536a220305279d241a7` |
| Independent audit | `775dac65e9793fcbbe5d4fc18c09bcfc90ab2a698b5e6fd11a037abf52b9244b` |
| No-rate footprint / summary | `dc5e5a9b5093751120f68e82d116f5af1630d2c3f95368d8003d098ad2d1a5e5` / `7f4b86131740ef33ffb905e18faea0234ce8aa8cd48bead2b6dea526149c6af9` |
| Ground-validation protocol / inventory template | `97a171ccfd6f624a7e3946a30caada24b2a0418f7655c215404a9cfeaa3a9b7d` / `6dba226a47391f8bcb2686c5ba9a68116f3b40b6afc276419cd9d62ea6793248` |
| BIG/ITB/DKI request draft / package manifest | `539ddc9fe966536ada40869306c1dfb52d6df4097341d2e6f8e04eed6cfbf773` / `798d1b951bf5b7e1ffd1ff3291fdf5371374ed9fae8454e75765248785b3b948` |
| Package builder / tests | `8f39c23176ae054a52d66adeaec42ec54ab0292827c5abbc0b3b094b408b4ac4` / `378382e2bd750b42d236b48f2d3815ee4097b06f3389a163d9557c05bb3a22b7` |
| Footprint grid parameters | `f8ec4cb779cda6978ea5bd48c958cc917669cda957a5a570c8a3d7d012b4a30b` |
| Footprint North ledger | `e6e4aceb4370e33562aa13bbde908d02eb9ce537754bddf00abc4da62e5ffa87` |
| Footprint post-inversion gate | `dec555a09c9ef48d022d9b00485269f96c2a5eb5b2aa1128e04e0b14c89cf880` |
| Raw `vel` / `vstd` | `943279ec2a8aa17ba7d8d6db5cf9a6eae5552c8ccf89f27ab9b63ba13df87895` / `03572b2cc175cca5f9a029d720a9a72628753a5984406172386320822f8c4285` |
| Raw `n_gap` / `n_loop_err` | `045329a24a8ad2622dc17888a2cebbe96435c8cf975ef442219634bbf66cde14` / `eeff1bc65a94049b6375fe47c1aa6066bfa410143de90feb9add4decdf6880e4` |

### V14

| Artifact | SHA-256 |
|---|---|
| V14 notebook | `8a379c0caa142b3029f5e81e1f4d68ff94ac231629115fe9660d9d6170deab8d` |
| Superseded schema-1 fingerprint | `46af15bbda3298c77171d14978ebed10b72028c3a17c966392b90143007bb899` |
| Schema-2 fingerprint | `b76aab7903de62b9068c4ed87f41b97692e26b1c15be6743d7a75023ab8db994` |
| West / east / south archives | `bbac3c3d712bbd21fa8705ab433674c54446fecfe1a0234b122443f085637da5` / `bfdc6261dfb2ea6793f83c6fa9c864f44816b65706dbea9c63c6d6ce6caa2ad7` / `60e6e4d4cca5ba0c71818cab027a9f730b8c74e2cb2ecd2aa9c107bb4bc76c74` |
| Compact summary archive | `065906f9e1b313fbc062e2ce016eced48dd947e73cf58245081682f109f7b3f6` |
| Preregistration / decision / manifest | `8693e6473d5e8029e97b8d21fc6dcd975ef2925d325cdff3a3b035b11f104e01` / `70e718439ec27edee5fc547cb8944deb56672b37bef56a56e1eed08ef9d51c95` / `451d019a745393b046bd7fcfd06e3561963fd9a55ed723070a0f44f1f1857302` |
| Independent audit report | `6a1e6945df0010821b01c60395771d8890c39bdfc1b0c2eac6a8cbbd374116ae` |

### AlphaEarth annual-change preflight

| Artifact | SHA-256 |
|---|---|
| Authenticated 2023 30 m raster | `19a8f04bdb71e9be0cd7dd9a2a033e513dea69f6860541ef2c2ab5315be472c7` |
| Benchmark v1 protocol / assignment | `e3c9bb88b966eece0578162d68ab19b759c5a44f92364b3c4f782da3bdeef62b` / `f5914a2426b9f066152fcf6042445dc464035a5f34e8d8dbc8eb94986fbe119c` |
| Wayback extension v2 protocol / verified availability | `191600a505893cf5dd15c15a27ac50c9aa925081c3ad4501f1e6dfc130dc7edd` / `35debbdaf557967181f87c0d1efe3d4872d5e09e0691a26e5c42237a5dff38e1` |
| Pléiades metadata scout rule / footprint inventory (not image access) | `02f887abb1ba5389f3cba2e1f7cb673127e09c9c6dfd3d6d40d69f15282ac08a` / `ea41835763bc6456504851ac26eb5506977293954d4fd0796d556f96c5e8fd02` |
| Reference audit / support gate / S2 inventory | `380b30a82390a7f5dc78fe65c6524b0e9bbb6def00d1b6e875ec4a15e4a65ff8` / `0d56e1833b6133d8e2433549e74dec01c50002933403b46fd03d6379fa9f2140` / `d1a68ed72a194bd17c8c1f7c5ceba8d5beb8529fb2342b57fe9c8db69c3280ad` |
| Full-grid contract / 2023 legacy audit / comparison manifest | `0fac38294b4b2e8ebd1ef2189df0898b4b79ef07ae7b8dcac21aa3e673829862` / `de3a5d48b18a345fa962f0b25c3f359313d31e4b1537c90ed1449342a2514258` / `6f5a56846626ec2c058472ce4ee8707172c245da6642027f645591668fea3fbb` |
| GCS v1 inventory / pixel pilot | `be02701d9a3c539653f5d395fc1a5a659340217b56986e4df8ccd500f2c0e63e` / `49f491d873e9362bc2c5a61502d97842adeca4cd1d4d2c18e62300354ed211bb` |
| Overview protocol / holdout / confirmation | `784208fb47f72c12862511e622a5317b8bacf5e060217267351833c4ea7ee9b8` / `25b9a272190e799b59439e10114087ced4b810d45f22725c41dd58cd7c6bc6e5` / `1fcd1d31ac73dff348a3b929189cee2f3178b758c09a55d63bf5a04d5c3d01a5` |
| Six-year GCS-only protocol / comparison (contains year hashes) / volume estimate | `aeb1a2c3e2763f3964c9c6bcf5bf8914063dc30370e5412e0bb2b190137ed07e` / `5a8d4d67e6d63a17ba10ba9c9fe82d652e0c7eeefe4aa98f3d3064223ad7b8aa` / `2e6277b4ac82ac66d80254f4c39e4cc0636953d5fd70fce1d9acf96d4a4a261b` |
| Java VLM/EW CSV / source audit / municipality counts | `f82dd843df5a87a2db990416c9ea2a6a86c6cd77b6c1ba91ebf3f5be9f05cf65` / `0a62c5d9d1d5bf95e783571023f0e7c2dd69a85d6ee56880470bbfa18f1c1f18` / `994b4ca869e411527f5292e3d876f519e8ebf9df60031b7e15b34a8528040efa` |
| Six-year contract | `a43b2fff3dd8dbfdfe55f3c79be1add90e17360a2918893e43f4e8a25ec74c63` |
| Contract builder / exact-grid exporter | `3999e75ba922e561ac38946c001f80bd7cf0089d893746bccc69e5af5518104c` / `ba80831eb9018f1f0f1444cef953a4b00fb1bcfd7ff2d1cde942455bdc30dacb` |
| Contract / exporter tests | `b14578efa031b9eaecacebe071fda27853cf8be967680a801ff4fa48a75c1077` / `dfc8d56211ebdaff435113eb4d8f51732f84ecd518146f7db5b5979d36fd4576` |
