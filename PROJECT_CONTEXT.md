# Jakarta project — current context

Authoritative live status, decisions and next actions. Read completely at session
start. Setup is in [README.md](README.md); history, frozen experiment details and
artifact hashes are in [CHANGELOG.md](CHANGELOG.md#artifact-checksums). Read only
the historical entries needed for the task; do not create another status document.

- Owner: Nabhonil Sarkar
- Repository: [nabhonil-sarkar/insar-risk-zoning](https://github.com/nabhonil-sarkar/insar-risk-zoning)
- Development version: `0.3.2.dev0`; last release: `v0.3.1`
- Updated: 3 November 2026
- Tests: 166 passing (full local suite, 3 November 2026)
- Scientific status: no validated project-produced deformation, hazard or risk map.

## Accepted scope and current state

The owner accepted a partial pivot on 8 October: study **Jakarta urban change
and exposure using public data**, audit published subsidence as a contextual
layer, and retain our InSAR experiments as a relative-pattern case study.
Completion no longer depends on replies to ground-data requests. If the
published deformation source fails its audit, the fallback is an AlphaEarth
urban-change study. The repository name and processing code have not changed.

Research question: where did Jakarta's urban surface change during 2020–2025,
and where do those changes overlap published subsidence? Different observation
periods permit spatial comparison, not causal attribution or a current-rate claim.
The added-value test against ordinary vegetation/built-up predictors is parked
for lack of independent labels. Exposure interpretation still needs evidence
about buildings, population or infrastructure.

ROI: `[106.45, -6.54, 107.22, -6.01]` in EPSG:4326, approximately 85 × 59 km.

| Evidence | Usable now | Limitation |
|---|---|---|
| AlphaEarth | Full GCS-only 2020–2025 series on the frozen grid; 5,619,719 valid ROI centres in every year | Embedding differences alone do not identify urban development or exposure |
| Ascending v9 | Audited diagnostic stack and strict footprint | 29.80% mainland DKI coverage; 0% North |
| Descending v13/v14 | Reference-stable centred LOS pattern; 380 cells covering 68.3903% of North | Zero level varies 8.0453 mm/year; `relative_pattern_only`; 31.61% uncovered |
| Published Java VLM/EW | Full source verified; 48,883 screened mainland DKI locations, 10,051 in North | Point support, not continuous coverage; no aggregation or overlay yet |
| Ground validation | Exact no-rate footprint and request package prepared | Owner reports unanswered emails; no compatible independent anchor |

V13 spans 10 January 2020–11 June 2023. Its formal uncertainty and internal
consistency do not establish external accuracy. V9 and v13 have different
periods and geometries; do not mosaic them or extrapolate their strict masks.

## Immediate work and decision points

1. **Wayback exhausted through 3 November 2026 for the frozen benchmark.**
   All 93 relevant releases reconciled. The extension added zero endpoints:
   40 paired development sites/16 blocks, 54 evaluation sites/22 blocks.
   At least 20 blocks per split are required before class and review gates.
   No labels, fits or added-value result. Do not repeat this archive search.
2. The owner confirms no full-resolution Pléiades access. Catalogue footprints
   cannot supply labels. Park the benchmark with its sites and gates unchanged;
   retain the descriptive maps and leave model superiority untested.
   No order or account request was made. Evidence under
   `data/output/{urban_benchmark_v1,urban_wayback_extension_v2,pleiades_catalogue_scout}/`.
3. **Next:** freeze spatial aggregation/support and duplicate-exclusion sensitivity for
   published vertical context before overlay; use the urban-change-only fallback
   if published context proves unsuitable.

No new speculative InSAR rerun is part of this scope. Keep completed experiments
and checkpoints. A failed pilot must lead to a documented diagnosis or separate
prospective experiment, not silent grid changes or post-result threshold tuning.

## Active input contracts

### AlphaEarth

Collection: `GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`. Local reference:
`data/raw/embeddings/AlphaEarth_Jakarta_Wide_30m_2023.tif` (782,795,253 bytes;
2,858 × 1,968; EPSG:4326; 64 bands `A00`–`A63`). The reference and existing
six-year contract hashes are in the changelog registry. Contract builder:
`scripts/prepare_alphaearth_annual_change.py`; existing Earth Engine route:
`scripts/export_embeddings.py`.

[Google's GCS guide](https://developers.google.com/earth-engine/guides/aef_on_gcs_readme)
documents 2017–2025, CC BY 4.0 and provider-paid access. The generation-pinned
GCS inventory finds two intersecting native tiles per year (12 total); all
headers agree with the provider index. The third 2025 bounding-box candidate
starts 13.6 m east of the frozen grid's easternmost projected extent.
All six GCS rasters are local in `data/output/alphaearth_annual_change/gcs_full_v1/`.
Decoded 2023 matches the legacy export exactly on every in-ROI axis; legacy
retains 2,650 valid exterior centres. Never import its mask. Use the GCS-only
series (stored 20 m overview, frozen nominal 30 m grid and explicit centre clip).
The `cosine_change/` subfolder contains the five adjacent-year and two longer
comparisons, their manifest and a diagnostic 2020–2025 preview. All seven have
the same 5,619,719 jointly valid centres, including water. See the
[README](README.md#local-setup-and-verification) for commands.

Rules:

- Preserve the exact frozen 2023 grid and all 64 axes. Version the acquisition
  contract; do not silently overwrite the historical Earth Engine contract.
- GCS int8 nodata is `-128`; mask it before decoding:
  `sign(q) * (q / 127.5)**2`. Never average raw integer values.
  For vector aggregation, decode, sum vectors, then normalize the sum.
- Verify 2023 source-version/resampling equivalence before mixing delivery
  routes. Do not independently z-score annual layers, interpret single axes,
  interpolate missing years or compare without joint finite/non-zero support.
- Use all-axis cosine change for five adjacent-year comparisons plus
  2020–2023 and 2020–2025. Require grid/mask QA, sensitivity analysis,
  cross-year cluster matching/stability, ancillary interpretation and an
  ablation against ordinary predictors.
- First analysis remains on the frozen 30 m grid; native 10 m sensitivity is
  a separate later experiment. Embeddings do not measure deformation.
- Attribution: “The AlphaEarth Foundations Satellite Embedding dataset is
  produced by Google and Google DeepMind.”

### Published deformation and ancillary sources

Primary candidate: [Ohenhen et al., Science Advances (2026)](https://doi.org/10.1126/sciadv.aec0172),
2017–2023 multi-geometry analysis with nominal 75 m support and GNSS referencing.
[Zenodo 15786357](https://zenodo.org/records/15786357) provides
`Java_VLM_EW.csv`, 446,891,387 bytes, CC BY 4.0; expected provider MD5 is
in the changelog. Full-file audit complete: 312,374 ROI records, 261,286
distinct coordinates. Withhold all 40,661 conflicting locations; 220,625
remain with finite VLM and positive finite SD. Never infer area coverage
from point counts. VLM and EW are in cm/year; VLM is IGS14, EW local.

The publication's GNSS comparison includes reference-alignment stations; it
does not independently validate our v13 stack. Its period differs from v13.
Do not put this source into the LiCSBAS-specific raw-input pipeline without an
explicit adapter and provenance/geometry contract.

Secondary candidate: [Sinking City, Zenodo 19456870](https://zenodo.org/records/19456870),
CC BY 4.0, offers NDVI, NDBI, imperviousness and residential context.
Its [processing source](https://github.com/zarashabrina/Jakarta-Sinking-City)
uses the same ascending LiCSAR frame, CJKT comparison and kriging.
Interpolated coverage is not measured coverage or independent ground truth.

## Scientific and software safeguards

- Keep AlphaEarth context, deformation, exposure and confidence separate.
  A risk claim requires adequate validated hazard and evidence-backed exposure;
  cluster similarity alone does not establish exposure or vulnerability.
- LOS is not automatically vertical. Do not infer vertical v13 rates without
  a prospective geometry rule and external zero anchoring.
- Match location, dates, datum/reference, sign, units, component and uncertainty
  in external comparisons. Archive incoming ground data unchanged, screen
  metadata first, and freeze metrics/gates before examining comparison outcomes.
- Preserve native measurement support; resampling to 30 m does not create
  independent InSAR observations. Nodata becomes NaN before resampling;
  InSAR alignment defaults to nearest neighbour.
- A LiCSBAS stack must pair `vel`/`vstd` from one inversion, with matching
  dates, CRS, dimensions, transform and footprint. Preserve `coh_avg`,
  `n_unw`, checksums, units, nodata, ranges and processing provenance.
  Keep sensitivity suffixes; canonical `jakarta_*_2020_2023` names are
  reserved for a validated selected stack.
- Historical pre-`vstd` inputs stay in
  `data/archive/pre_vstd_diagnostic/`; never mix them with new uncertainty.
  `data/raw/insar/` remains reserved for a matched stack.
- Pipeline order: `m2 -> m1 -> m3 -> m4 -> cal -> m4b -> m5`.
  M2 owns preprocessing; M3 aligns, not fuses. The annual branch's
  no-independent-normalization rule takes precedence over legacy preprocessing.
- Severity bins cover all finite values and fail loudly. Statistics use
  valid-velocity denominators and report coverage. Empty `CLUSTER_EXPOSURE`
  is diagnostic only; production requires explicit exposure for every cluster.
- Cache reuse requires matching settings, CLI and input fingerprints.
  `pyproject.toml` defines dependencies; `requirements.lock.txt` records the
  validated environment. Runtime settings live in `config/settings.py`.

Completed InSAR branches retain their frozen controls, fully recorded in
[the changelog](CHANGELOG.md#frozen-experiment-controls). Do not relax the
1.5-rad loop threshold or 0.3 consistency threshold, mix partial GACOS or phase
families, manually prune pairs, rerun v8 cells 10–13, run factor 2 as a rescue,
or run v10 cells 8–12. The historical 25% ceiling remains a v8 failure rule;
it is not a universal standard. Future experiments require separate
preregistration rather than retroactive changes.

## Ground requests, deferred branches and roadmap

The owner reports unanswered emails as of 8 October; recipients, dates and
attachments have not been inspected. No assistant email was sent.
`scripts/build_v13_ground_validation_package.py` rebuilds the checksum-gated
BIG/ITB/DKI protocol, inventory template and unsigned request with the exact
no-rate footprint. Any new transmission requires explicit authorization and
signature/recipient details. The existing protocol allows at most one follow-up
after ten business days; do not assume it remains unsent.

Ground records must include coordinates, dates, datum, sign, units, uncertainty,
offsets and measurement method. SIGA `Data Mounting` methods remain unresolved.
The open GNSS archive DOI `10.5281/zenodo.7775016` offers inadequate
space/time support (CJKT misses strict v9 coverage; CTGR is outside DKI with
only 2020–2021 overlap).

| Stage | Current state / completion requirement |
|---|---|
| 1–2: repository/input recovery | Complete for v9; preserve intentional Git changes and evidence |
| 3: own InSAR | Technical/relative candidates only; retain as case study |
| 4: annual change | Six annual grids pass QA; interpretation, sensitivity and added-value evaluation pending |
| 5: uncertainty | Partial; audit new source uncertainty and native support |
| 6: validation | Own-stack ground anchor blocked; published-source audit is a separate route |
| 7: exposure | Active scope, pending evidence; risk claims remain gated |
| 8: release | Pending reproducible results, sensitivity, provenance, attribution and consistent claims |

Deferred: NISAR v12 is a 2026 coverage/coherence test only; stop after cell 4
inventory/QA and obtain approval before its 9.48 GB cell-5 download.
Newer orbit-98 Sentinel-1 and ALOS-2 need separate inventory, cost/licensing and
prospective method decisions. Neither validates the historical stack by itself.

Priorities after acquisition: native-support summaries, explicit
diagnostic/validated output state and report gates, cluster/exposure
interpretation, coverage/confidence, HDBSCAN and calibration tests, naming
cleanup, CI/linting. Later: multi-geometry/city generalization, environment
packaging, data dictionary, citation/model card and interactive delivery.

## Evidence and maintenance

Keep all source archives, manifests/sidecars, notebooks, failed experiments,
official boundary, QC/audit results and exact no-rate footprints. Verify their
[registered hashes](CHANGELOG.md#artifact-checksums) before reuse. Builders and
audits are under `scripts/`; v9/v10 diagnostics are under
`data/output/v9_qc/` and `data/output/v10_qc/`.
Use README commands for setup, smoke tests and validation.

Follow `AGENTS.md`: change this file only when live state/decisions change,
README only for public scope/setup/status changes, and changelog only for
material completed milestones. Do not add session filler or another handoff.
Revise the sole methodology DOCX when a major method is adopted or a validated
result milestone occurs.
