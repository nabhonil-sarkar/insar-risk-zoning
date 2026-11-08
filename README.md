# Satellite-observed surface differences around Jakarta

A completed descriptive remote-sensing case study of **2020–2025 AlphaEarth
embedding differences** around Jakarta, with follow-up diagnostics and documented
observation limits. It asks **where and when satellite-derived surface descriptions
differed most**. It does not identify confirmed development, land loss, reclamation,
subsidence, exposure or risk from those differences alone.

Owner: Nabhonil Sarkar · Study rectangle: approximately 85 × 59 km.
The repository retains its original `insar-risk-zoning` name and historical radar
code; no project-produced absolute subsidence, hazard or risk map is validated.

## Read the results

- [Final illustrated case study (PDF)](docs/Nabhonil_Sarkar_Jakarta_Surface_Differences_2020-2025.pdf)
  — accepted 10-page Editorial v5, 5 November 2026.
- [Phase B optical feasibility supplement (PDF)](docs/Nabhonil_Sarkar_Jakarta_Phase_B_Optical_Feasibility_Supplement.pdf)
  · [editable supplement (Word)](docs/Nabhonil_Sarkar_Jakarta_Phase_B_Optical_Feasibility_Supplement.docx)
  — accepted three-page supplement, corrected 8 November 2026. It records both
  fixed optical designs and their coverage failures.
- [Technical methodology (Word)](docs/InSAR_Subsidence_Risk_Zoning_Methodology.docx)
  — methods and limitations; historical designs do not imply active work.
- [Changelog and artifact checksums](CHANGELOG.md) — dated milestones,
  verification environments, preserved failures and provenance.

The earlier `Nabhonil_Sarkar_Jakarta_Surface_Change_2020-2025` PDF and DOCX are
superseded drafts, retained for history. That DOCX is **not** the editable source
of the accepted Editorial v5 PDF. The main report and accepted supplement are
preserved unchanged in this repository update.

## Results and current status

As of **8 November 2026**, the descriptive report and Phase A are complete,
the Phase B optical branch is closed, and Phase C is parked after preparation.
No new analysis is needed to regard the descriptive study as complete.

### Annual differences and Phase A

- Six annual grids and seven difference maps use the same **5,619,719 valid
  in-ROI centres**, all 64 embedding components and one frozen nominal 30 m grid.
  GCS inputs use stored 20 m overviews. Decoded 2023 values reproduce the earlier
  Earth Engine export exactly at every valid ROI centre; the legacy export's
  2,650 exterior centres are excluded. This verifies processing equivalence,
  not cross-year product consistency.
- The northwest sector contains **32.2% of the 2020–2025 top-1% differences on
  11.1% of valid cells**. Concentration persists on 2020 baseline land and after
  western tile-strip exclusion (32.99% of re-ranked extremes). The primary
  registered seam comparisons were not flagged; all water-only comparisons
  were inconclusive. These checks do not establish a physical cause.
- **2022–2023 is the largest adjacent-year difference at 85.4% of valid cells.**
  The Phase A follow-up found larger medians across all nine observed baseline
  classes and positive contrasts in all 64 supported class-sector groups against
  each of the four other transitions. Magnitudes vary, and baseline classes do
  not establish unchanged surfaces. The breadth is compatible with a shared
  observation/product influence but does not prove one or exclude real change.

The study's northwest sector is not administrative North Jakarta: 96.8% of its
valid cells lie outside mainland DKI. Embedding differences and any apparent
reversal in the embedding pattern are not measurements of physical change.

### Phase B: two bounded optical feasibility failures

Both designs used the same six 1 km windows, selected geometrically within NW
using WorldCover 2020 rather than embedding scores. Eight dates per seasonal
window were preselected, one per half-month using whole-scene cloud metadata.
Every window required at least 80% of its cells to meet clear-date, month,
60-day-span and spacing rules under both 60 m and 120 m quality buffers.

| Design | Period actually acquired | Result |
|---|---|---|
| Original two-season, 2020–2025 | January–April 2020: eight dates | All 12 window-buffer entries failed; coastal support 0%, best control 0.08% |
| June–September follow-up, 2020–2025 | June–September 2022: eight dates, acquired first | C2 and C4 passed both buffers; the other four windows failed both, so eight of 12 entries failed |

The original initial attempt stopped before pixels at a combined header check;
the absent TIFF nodata tag was diagnosed the following day. The tested XML-backed
correction preserved geometry, masking and calibration. All 576 headers passed
before the corrected original attempt; all 288 passed before the seasonal attempt.

After quality masking, observations were insufficiently spread through the tested
seasons. The 60-day span was a major constraint, alongside clear-date and month
requirements. Quality exclusions are not proof that every excluded pixel was cloud.
Using all available scenes or longer seasons was not tested.

**Neither design completed its six-year sequence or classified transitions.**
Unacquired periods are unknown, not zero-support observations. Passing individual
windows does not establish six-year feasibility. The failures apply to these
windows, selected dates and rules—not optical monitoring in general. This branch
is closed; no further optical rescue, tide analysis or classification is active.

Cumulative reserved accounting ended at 1,252,483,412 bytes, including historical
and documentation allowances. These are accounting assumptions, not verified
lifetime traffic or proven upper bounds. The supplement and changelog distinguish
received response bodies from reservations and record execution/audit dates.

### Phase C: sampling diagnostics complete; contextual analysis parked

The published Java source audit retains **220,625 eligible locations** in the
rectangle, including 48,883 in mainland DKI, after withholding all 40,661
conflicting coordinates. Point counts do not establish continuous area coverage.
NW has 21,611 eligible locations, 20,278 outside mainland DKI; DKI-only administrative
aggregation would omit much of this sector.

A geometry-only 1 km grid inventory and a prospectively specified sampling-overlap
diagnostic are complete. Under the recommended full-unit screen (at least ten
points, four occupied 250 m subregions and points in both halves of each axis),
3,459 units qualify; 413 intersect NW and are not necessarily wholly inside it.

| Sampling convention within those units | All valid NW cells included | NW endpoint extremes included |
|---|---:|---:|
| Union of 75 m squares around eligible points | 20.14% | 9.12% |
| Union of 75 m diameter disks | 15.93% | 7.21% |
| Occupied 250 m subregions | 56.77% | 29.26% |

NW extremes use the original rectangle-wide ranking, not a separate NW ranking.
The square and disk are operational conventions, not established measurement
footprints; occupied subregions are not fully measured. The unequal overlap limits
a comparison's ability to address the headline concentration, without explaining
why observations are missing.

A descriptive protocol and reporting matrices were prepared, but **Phase C is
parked**. No motion values were aggregated or compared with embedding differences.
The proposed 2020–2022 endpoint remains ungenerated. Preparation does not imply
implementation, a validated relationship or a commitment to continue.

### Other limits and retained work

| Branch | What remains usable | Why the original goal is unmet |
|---|---|---|
| Own Sentinel-1 processing | Reference-stable descending relative LOS pattern over 68.39% of North Jakarta | Its zero level changes by 8.0453 mm/year across reference choices; ascending strict coverage is 0% of North; no compatible independent anchor |
| Embeddings versus simpler predictors | Frozen benchmark and imagery-availability audits | Paired imagery candidates cover only 16 development blocks versus 20 required; no full-resolution Pléiades access; neither model was scored |
| Surface classification | Existing four-cluster 2023 baseline as surface context | Further cross-year clustering and physical attribution are deferred |
| Exposure and risk | Separate conceptual requirements | Suitable exposure analysis and validated hazard were not established |

## Optional future work

The project can close with its present report, supplement and sampling limitations.
Alternatively, one short exploratory check could assess whether a rule-selected
sample is interpretable from endpoint imagery. No attribution study, distant-area
jump test, radar water mapping, Phase C execution or dashboard is currently active.
An exploratory label would describe an observed surface difference, not its cause.

New work uses proportionate checks: labelled exploration; a short prospective plan
for reported analyses with prior exploration disclosed; and relevant tests,
provenance and wording checks before publication. One review per milestone and a
simple study-level resource/effort cap replace routine intermediate approval loops.
Historical protocols, evidence and accounting remain intact. The public code
includes frozen historical guards for reproducibility; these are not a universal
workflow template for every future task.

## Reproducibility and repository contents

This repository contains code, tests, methodology and report artifacts. Source
datasets, large rasters, cached metadata and local run/protocol bundles under
`data/` are not distributed. A fresh clone supports the software tests but cannot
reproduce the research outputs without those pinned inputs and bundles. Historical
runners use write-once paths and fail on absent or changed inputs; do not remove
checks or overwrite completed runs to make a command proceed.

Key local evidence namespaces (not Git download links):

| Evidence | Local namespace |
|---|---|
| Annual grids and difference maps | `data/output/alphaearth_annual_change/gcs_full_v1/` |
| Registered seam test | `data/output/alphaearth_seam_v2/` |
| Completed Phase A | `data/output/alphaearth_surface_type_v1/run/` |
| Original coastal attempts | `data/output/coastal_transition_pilot_v1/` |
| Seasonal coverage-only outcome | `data/output/coastal_jun_sep_v1/stage1_run/` |
| Phase C geometry inventory | `data/output/phase_c_geometry_support_v1/` |
| Sampling-overlap diagnostic | `data/output/phase_c_matched_support_v1/` |
| Parked descriptive protocol | `data/output/phase_c_descriptive_v1/` |

The published geometry/matched-support scripts preserve the completed diagnostics;
they do not implement the parked motion-comparison protocol. The accepted main
report is distributed as a PDF; this repository does not claim a self-contained
rebuild of that editorial artifact.

## Approach and inputs

The information streams remain separate:

- **AlphaEarth:** all 64 embedding axes describe surface context and annual
  differences on the frozen 2023 grid. Added value over ordinary vegetation
  and built-up predictors remains untested.
- **Deformation:** audit published vertical/east–west motion, including its
  period, reference frame, coverage, uncertainty and duplicate coordinates.
  Our own unvalidated LOS results remain a separately labelled case study.
- **Exposure:** interpret buildings, population and infrastructure using
  explicit evidence. Risk claims require adequate hazard validation and
  exposure evidence.

| Source | Role |
|---|---|
| [AlphaEarth annual embeddings](https://developers.google.com/earth-engine/guides/aef_on_gcs_readme) | Six years, 2020–2025; stored 20 m overview sampled onto the frozen nominal 30 m grid; native product 10 m |
| [Java VLM/EW](https://zenodo.org/records/15786357) | Candidate published 2017–2023 deformation and uncertainty |
| [Sinking City](https://zenodo.org/records/19456870) | Candidate urban-context/comparison layers |
| COMET-LiCSAR / LiCSBAS | Archived processing experiments and relative LOS evidence |

Embeddings do not measure displacement. LOS is not automatically vertical;
30 m display cells are not independent InSAR measurements. Historical July
risk products and failed experiments are diagnostic only.

## Local setup and verification

Supported Python: 3.12–3.14. From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest tests
```

For the previously validated Windows/Python 3.14 environment, install
`requirements.lock.txt`, then install the project with `-e . --no-deps`.
For a data-free end-to-end smoke test, run `python -m pytest tests/test_pipeline_smoke.py`
in the project environment. The installed `insar-risk-zoning` command is the
legacy clustering/overlay pipeline, not the annual workflow below. Its `--synthetic` flag replaces only
the InSAR input; it still requires local embeddings. The real v13 footprint
regression runs only with its local audit bundle.
Historical full-data verification on 6 November 2026: **383 passed, none skipped**
(Windows, Python 3.14.5; network blocked). Data-dependent checks are explicitly
skipped when their excluded local bundles are absent. See CHANGELOG for the
publication validation and GitHub Actions for fresh-clone checks.

Earth Engine export optionally requires `.[earth-engine]`, authentication
and an approved Cloud project. The GCS route needs neither. With the locked
environment, frozen 2023 reference and registered pilot evidence present:

```powershell
.\.venv\Scripts\python -m scripts.build_alphaearth_full_grid
.\.venv\Scripts\python -m scripts.audit_alphaearth_full_2023
.\.venv\Scripts\python -m scripts.alphaearth_full_grid_change
.\.venv\Scripts\python -m scripts.render_alphaearth_change
```

Outputs: `data/output/alphaearth_annual_change/gcs_full_v1/`. The builder resumes
verified byte ranges and completed years, starting with 2023. Annual rasters
store **encoded int8**, not analysis-ready floats: mask −128, then decode each
axis as `sign(q)*(q/127.5)**2`. The comparison command does this before computing
cosine distance. Diagnostic outputs are write-once. Source generations, pilot
protocols and artifact hashes are in the changelog and manifests.

The approved v2 seam diagnostic found no unusual sharp boundary step in either
primary comparison. All water-only checks were inconclusive. The northwest
retained 33.0% of the re-ranked endpoint extremes after excluding the western
tile sliver (32.2% before exclusion); this does not establish physical change.
See the [changelog](CHANGELOG.md#2026-11-05--registered-jakarta-tile-seam-test-and-endpoint-sensitivity)
for all outcomes. The completed write-once run used `python -m scripts.run_alphaearth_tile_seam`
with `--worldcover PATH` and `--approved-protocol-sha256 HASH` from a clean
checkout containing the frozen inputs. It verifies every manifest-listed map
before raster decoding and writes a single non-overwritable `results.json`
beside the protocol, including the executing Git commit. To test the runner
without study data, use `python -m pytest tests/test_run_alphaearth_tile_seam.py`.

Published-source helpers: `scripts.fetch_published_java`,
`scripts.audit_published_java`, then `scripts.audit_published_java_dki`.

Historical benchmark tools: `scripts.urban_change_benchmark register` and
`select` specify samples before imagery inspection. The benchmark is parked;
these commands document the retained workflow rather than an active next step. The companion modules
`scripts.audit_urban_reference`, `scripts.inventory_urban_baseline` and
`scripts.check_urban_benchmark_support` audit availability without assigning
labels. Frozen local outputs: `data/output/urban_benchmark_v1/`. The separate
`scripts.expand_urban_wayback` module supports `register`, `audit` and read-only
`verify`. The `scripts.scout_pleiades_footprints` module (`register`, `audit`)
checks public scene footprints only; its output cannot unlock model scoring.

Existing helpers:

```powershell
.\.venv\Scripts\python scripts\prepare_alphaearth_annual_change.py
.\.venv\Scripts\python scripts\validate_inputs.py --json data\output\input_validation.json
```

The contract builder records the frozen baseline; its historical availability
metadata must be versioned for the new acquisition route. Input validation needs
real matched inputs and may fail until they are supplied. Synthetic output
exercises software only.

## Code and operation

Configuration is in `config/settings.py`; processing in `src/`; acquisition,
pipeline entry points and experiment audits in `scripts/`; Colab experiments
in `notebooks/`; regression checks in `tests/`. Outputs and provenance go to
`data/output/`, including rasters, GeoPackage, statistics, figures, reports,
logs and `pipeline_state.json`.

The existing pipeline supports `--force`, `--force-from STAGE`,
`--method {kmeans,gmm,hdbscan}` and `--k N`. Stage order is
`m2 -> m1 -> m3 -> m4 -> cal -> m4b -> m5`. Production mode requires
explicit cluster exposure; this software guard does not establish scientific
validation.

Raw embeddings belong in `data/raw/embeddings/`. The LiCSBAS input contract
reserves `data/raw/insar/` for matched `vel`, `vstd`, optional
`coh_avg`, and QA `n_unw` layers plus provenance from one inversion.
It rejects ambiguous or processed inputs. Published VLM requires its own
explicit adapter; do not pass it through assumed LOS conversion.

Fingerprint caching, nodata handling, complete severity bins and coverage
reporting protect against known failures. Failed notebooks and archived inputs
remain reproducibility evidence. The project methodology is under `docs/`.

## Attribution and license

“The AlphaEarth Foundations Satellite Embedding dataset is produced by Google
and Google DeepMind.” Respect each source's license and attribution.

Copyright © 2026 Nabhonil Sarkar. All rights reserved. Provided for reference
and evaluation; no license is granted for use, modification or distribution.
For licensing inquiries, contact the owner. Third-party terms remain separate;
see [THIRD_PARTY_NOTICE.md](THIRD_PARTY_NOTICE.md).
