# Jakarta surface change and subsidence context

A Jakarta research project studying urban change, exposure and subsidence
evidence. The accepted scope is to analyse **2020–2025 land-surface change
with AlphaEarth**, audit a published deformation dataset for subsidence context,
and retain our Sentinel-1 experiments as a relative-pattern case study.

The question is: where has Jakarta's urban surface changed, and where do those
changes overlap published subsidence? Comparing different observation periods
describes spatial overlap; it does not establish causation.

Owner: Nabhonil Sarkar. Repository:
[nabhonil-sarkar/insar-risk-zoning](https://github.com/nabhonil-sarkar/insar-risk-zoning).
Study area: approximately 85 × 59 km around Jakarta.

## Status

As of 3 November 2026, **no project-produced deformation, hazard or risk map is
validated**. The 2023 four-cluster AlphaEarth baseline is usable as surface
context. The descending InSAR result supports a reference-stable relative LOS
pattern over 68.39% of North Jakarta, but its zero level is uncertain and
independent ground validation is missing.

The owner has accepted a public-data route so progress no longer depends on
unanswered validation emails. Two official AlphaEarth tiles intersect the
frozen Jakarta grid per year (2020–2025); all 12 headers were verified.
All **six full-area annual rasters and seven embedding-difference maps** have
been generated locally; the GeoTIFFs are not distributed in Git. Each comparison
has 5,619,719 joint in-ROI cells. Decoded GCS 2023
matches the frozen baseline exactly throughout the ROI; the legacy export
also retained 2,650 valid exterior cells. Differences are not labelled development.
The published Java source passed its file check. Screening leaves 48,883
distinct mainland Jakarta locations for contextual analysis, not a continuous
deformation layer. Across all 93 relevant Wayback releases, the frozen 300-patch
benchmark has paired imagery candidates in only 16 development blocks (20
required). A separate Pléiades footprint search suggests broader coverage,
but the project lacks full-resolution review access. Neither model was scored.
The benchmark is parked. Next: define how to group published subsidence points
and report coverage before comparing them with the embedding differences.
Verification: 166 tests passed with the local archive; a clean checkout passed
165 and skipped only the real-data v13 regression.

See the [changelog](CHANGELOG.md) for milestones and artifact checksums.

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
| [AlphaEarth annual embeddings](https://developers.google.com/earth-engine/guides/aef_on_gcs_readme) | 2020–2025 target; native 10 m, frozen local analysis grid 30 m |
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
in the project environment. The pipeline CLI's `--synthetic` flag replaces only
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

For the local v2 tile-seam diagnostic, first obtain approval for the exact
registered protocol. Only then use `python -m scripts.run_alphaearth_tile_seam`
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
