# Satellite-observed surface differences around Jakarta

A remote-sensing case study comparing **2020–2025 AlphaEarth embeddings**
around Jakarta on one nominal 30 m grid. The current deliverable describes
surface differences, not confirmed development, subsidence, exposure or risk.
Our Sentinel-1 experiments remain a relative-pattern case study; published
ground motion is screened but separate.

The question answered here is: where and when did the satellite-derived surface
descriptions differ most? Physical interpretation and comparison with published
subsidence remain future work; spatial overlap would not establish causation.

Owner: Nabhonil Sarkar. Repository:
[nabhonil-sarkar/insar-risk-zoning](https://github.com/nabhonil-sarkar/insar-risk-zoning).
Study area: approximately 85 × 59 km around Jakarta.

[Read the final illustrated case study (PDF)](docs/Nabhonil_Sarkar_Jakarta_Surface_Differences_2020-2025.pdf) ·
[Technical methodology (Word)](docs/InSAR_Subsidence_Risk_Zoning_Methodology.docx).

The current report is the accepted 10-page Editorial v5 (5 November 2026).
The older `Nabhonil_Sarkar_Jakarta_Surface_Change_2020-2025` PDF and DOCX in
`docs/` are superseded drafts, preserved for history; the DOCX is not the source
of the final editorial PDF.

## Status

As of 5 November 2026, **no project-produced deformation, hazard or risk map is
validated**. The 2023 four-cluster AlphaEarth baseline is usable as surface
context. The descending InSAR result supports a reference-stable relative LOS
pattern over 68.39% of North Jakarta, but its zero level is uncertain and
independent ground validation is missing.

Two descriptive findings need interpretation: the northwest of the study
rectangle contains 32.2% of endpoint top-1% cells on 11.1% of valid cells,
and 2022–2023 is the largest adjacent-year difference at 85.4% of valid cells.
The northwest is mostly west of mainland Jakarta, not administrative North
Jakarta. Its concentration persists on 2020 land and after western tile-strip
exclusion. These checks do not identify a physical cause.

The owner has accepted a public-data route so progress no longer depends on
unanswered validation emails. Two official AlphaEarth tiles intersect the
frozen Jakarta grid per year (2020–2025); all 12 headers were verified.
All **six full-area annual rasters and seven embedding-difference maps** have
been generated locally; the GeoTIFFs are not distributed in Git. Each comparison
has 5,619,719 joint in-ROI cells. Decoded GCS 2023
matches the frozen baseline exactly throughout the ROI; the legacy export
also retained 2,650 valid exterior cells. Differences are not labelled development.
Reproducing 2023 verifies processing, not product consistency across years.
The published Java source passed its file check. Screening leaves 48,883
distinct mainland Jakarta locations for contextual analysis, not a continuous
deformation layer. Across all 93 relevant Wayback releases, the frozen 300-patch
benchmark has paired imagery candidates in only 16 development blocks (20
required). A separate Pléiades footprint search suggests broader coverage,
but the project lacks full-resolution review access. Neither model was scored.
The benchmark is parked. The approved surface-type diagnostic now finds a
broad 2022–2023 elevation across baseline classes and sectors, with varying
magnitude. Its physical cause still needs independent dated observations. Before comparing
published subsidence, define spatial units and minimum observation support.
Verification: 326 tests passed locally with project data, none skipped, after the
nodata correction and restart safeguards on 6 November 2026; this is not a count from a data-free checkout. GitHub Actions also runs automated
checks; data-dependent tests may skip when local inputs are absent.

See the [changelog](CHANGELOG.md) for milestones and artifact checksums.

## Next phase (Phase A complete; coastal execution stopped before pixels)

The next goal is to explain observable surface differences before attempting
broader risk interpretation:

1. Completed the comparison of all five annual transitions by **2020 baseline
   surface class** and geographic sector for owner review. Existing
   WorldCover classes describe the baseline, not proven unchanged surfaces.
2. Test a small **2020–2025 coastal land–water pilot** using repeated public
   optical observations. First establish clear-image support, then assess
   persistent transitions with explicit ambiguous areas and sensitivity checks.
   Do not equate a transition with reclamation, erosion or subsidence.
3. If the pilot supports interpretation, consider the screened published
   subsidence data as context under predefined spatial-support rules. The
   observation periods differ; overlap alone is not causation.

Each stage needs a specified protocol, synthetic tests and a review before
expansion. Insufficient observations lead to a documented stop, not weaker
thresholds. The existing model-comparison benchmark stays parked; no new radar
rerun or risk-map release is planned. The accepted report remains unchanged.

The approved Phase A diagnostic ran once on 5 November, using 5,619,719 jointly
valid cells with no support loss. Across all nine observed baseline classes,
2022–2023 has a larger median than each other annual transition. All 64 supported
class-by-sector groups also have positive median cell-paired contrasts against
each of the four alternatives (256/256 descriptive contrasts). Magnitudes vary;
this breadth is compatible with a shared observation/product influence but does
not prove one or establish physical change. Nine sparse and 26 empty class-sector
groups remain explicit; all 681 mangrove-labelled cells occur in the N study
sector. Baseline labels do not prove locations stayed unchanged.

The complete local output is `data/output/alphaearth_surface_type_v1/run/`:
support, transition and contrast tables, JSON provenance, a summary and two
figures. Its approved runner requires a clean commit and verified input hashes,
and refuses to overwrite the run. The owner subsequently authorized Phase B
feasibility and protocol preparation; coastal acquisition and published-data
overlay have not started. See the
changelog for all class medians, limitations and artifact hashes.

The approved coastal pilot uses four 1 km coastal windows and two controls
selected from 2020 WorldCover geometry, with 96 fixed Sentinel-2 dates across
2020–2025. Public catalogue/XML/TIFF-header checks support a bounded acquisition:
1.70 GiB of required compressed blocks, a 3 GiB transfer ceiling and 7 GiB disk
reservation. Clear-pixel support remains unmeasured. The Planetary Computer
route requires verified per-product reflectance offsets and retains mixed
processing baselines; it is not a uniformly reprocessed archive. The separate
protocol fixes masking, temporal support, persistence, sensitivity and stopping
rules. The owner approved the exact protocol and acquisition ceiling on 5 November.
The execution runner verifies all sources before pixel requests, enforces the
total byte/time budget and stops at a failed temporal-support gate. The adopted
design is in the sole methodology; no scale-up or published overlay is authorized.
Local protocol/approval/evidence: `data/output/coastal_transition_pilot_v1/`.

The approved run from clean local commit `5dbdbb4` stopped at the actual
GeoTIFF geometry/datatype/nodata check before any pixel blocks were requested.
No dates were acquired and no transition classification ran. Clear-pixel
feasibility remains untested; this is an input/execution stop, not a failed
temporal-support result. Metadata-only diagnosis identified an absent TIFF
nodata tag on the first scene's B03 asset; its pinned product XML explicitly
declares NODATA=0 and all other native fields match. The corrected runner accepts
absent or zero TIFF nodata only after verifying the exact asset/product XML
association and a unique zero declaration. Conflicts and missing/ambiguous
declarations fail before image-block requests; geometry/datatype checks remain
exact. Failures now retain asset identity and named expected/actual fields.
All 576 cached asset/XML associations pass, and the diagnosed header passes
local replay. This does not establish compatibility of every native TIFF or
clear-pixel feasibility. The original run and diagnosis remain immutable;
the owner approved the correction and separate restart plan on 6 November.
The new attempt requires fresh test verification and a clean local commit,
preserves the original evidence, and carries prior traffic/time charges forward.
The approved remaining allowance is 2,948,670,514 bytes and 7,140 seconds,
with at least 7 GiB free disk and all frozen source/scientific gates unchanged.
All 144 window/year-season/buffer coverage entries explicitly remain unacquired.
No date/site substitution, threshold change, push or scale-up followed the stop.

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

Interpretation benchmark: run `scripts.urban_change_benchmark register` then
`select` as Python modules before imagery inspection. The companion modules
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
