"""Append the approved coastal design to the sole methodology; preserve history."""

import hashlib
import json
from pathlib import Path
import shutil

from docx import Document
from docx.shared import Pt

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/output/coastal_transition_pilot_v1'
SHA='4faf2430c6dbce50fb7e69cdcad9db819953bac6bb90edb2de4376cd38698754'


def main():
    raw=(OUT/'protocol.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SHA:raise ValueError('Protocol mismatch')
    protocol=json.loads(raw)
    if json.loads((OUT/'approval.json').read_bytes())['protocol_sha256']!=SHA:raise ValueError('Approval missing')
    target=ROOT/'docs/InSAR_Subsidence_Risk_Zoning_Methodology.docx'
    backup=OUT/'methodology_before_adoption.docx'
    with backup.open('xb') as stream:stream.write(target.read_bytes())
    d=Document(target)
    if any(p.text=='Coastal observation pilot' for p in d.paragraphs):raise ValueError('Already adopted')
    d.paragraphs[30].text=('The completed surface-type follow-up found the 2022–2023 elevation across supported baseline classes and sectors. '
                         'This does not establish a physical cause or unchanged baseline surfaces. The separately approved coastal protocol below '
                         'tests repeated direct observations. Risk interpretation still requires supported deformation and independent exposure evidence.')
    def page(kicker,title,sections):
        d.add_page_break();d.add_paragraph(kicker);d.add_heading(title,level=1)
        for heading,text in sections:
            d.add_heading(heading,level=2);d.add_paragraph(text)
    page('ADOPTED DESIGN    /    APPROVED 5 NOVEMBER 2026','Coastal observation pilot',[
        ('Question and authority','Can repeated public observations support persistent water-to-land or land-to-water transitions in six bounded northwest windows during 2020–2025? Protocol v1 was approved before optical pixel acquisition. Existing embedding maps and aggregates are known; this is not an entirely blind study. The northwest study sector is not administrative North Jakarta. WorldCover labels are ancillary baseline descriptions, not proof of unchanged surfaces.'),
        ('Frozen footprint','Use four coastal and two control squares selected from the pinned WorldCover 2020 v100 tile. Each core is 1,000 by 1,000 m on the EPSG:32748 zero-anchored lattice, with a 160 m read halo and 20 m analysis cells. Lower-left core coordinates in metres are C1 (661000, 9330000), C2 (669000, 9333000), C3 (678000, 9333000), C4 (686000, 9332000), L1 (673000, 9317000), W1 (673000, 9334000). Add 1,000 m to each coordinate for the upper-right corner. Controls are inland and northern-connected water proxies, not independent validation.'),
        ('Observation selection','Use the 96 fixed Planetary Computer scene IDs and dates in the protocol: one per half-month in January–April and June–September for every year. Scenes must cover all core-plus-halo windows. Metadata selection uses minimum whole-tile cloud percentage, then timestamp and ID, after the specified processing-version deduplication. These contrasting calendar windows do not match tides or establish local monsoon boundaries. No dates, sites, years or providers may be replaced after outcomes are inspected.'),
        ('Execution boundary','The total acquisition ceiling is 3 GiB including metadata and retries; require 7 GiB free disk and stop at two hours. Verify exact protocol approval, all evidence hashes, actual native geometry and source ETags before pixels. Complete synthetic tests and the full suite, then execute from a clean local commit. Allow at most two transient-request retries and respect Retry-After. Reject full-object responses. Preserve immutable range hashes and outputs; no push, scale-up, broader acquisition or Phase C is authorized.')])
    page('MEASUREMENT SUPPORT    /    SOURCE LIMITATIONS','Calibration and observation rules',[
        ('One public source','Use the selected Sentinel-2 L2A B02, B03, B04, B08, B11 and SCL assets from Planetary Computer tile 48MXU. Earth Search Collection 1 has only six catalogue items here in 2022; the PC processing-baseline 05 subset lacks 2020–2021. The accepted single-source route therefore spans processing baselines. It uses product XML calibration, not an assumed uniformly reprocessed archive. Encoding correction cannot erase atmospheric, cloud-classification or geolocation differences. Record processing baseline and spacecraft with every date.'),
        ('Reflectance and alignment','Mask native DN zero first. The product XML quantification value must equal 10,000. PB02.12/03.00 uses the documented zero-offset convention; PB04.00/05.09/05.10/05.11 requires offset −1,000 for the five spectral bands. Add the offset once and divide by 10,000. Reject conflicting calibration or unknown baselines. Average aligned 2 by 2 calibrated 10 m samples to 20 m, requiring all contributors finite. Keep native B11/SCL at 20 m. Do not claim 10 m SWIR support or resample to the embedding grid.'),
        ('Clouds and spectral ambiguity','A clear observation requires finite B03/B11, SCL 4, 5 or 6, and exclusion from the Euclidean 60 m cloud/shadow buffer around codes 2, 3, 8, 9 and 10. All other SCL classes are masked. No separate cloud-probability layer is supplied on this route. MNDWI is the green-minus-SWIR reflectance difference divided by their sum; require both nonnegative and their sum above 0.02. Water requires MNDWI above +0.10, land below −0.10; equality and the middle remain ambiguous.'),
        ('Mixed cells and sensitivity','A date label requires all cells in a 3 by 3 neighbourhood to share the same strong spectral label; any masked or ambiguous neighbour defeats it. Process the halo before cropping. Run all six combinations of threshold centres −0.05, 0 and +0.05 with a ±0.10 ambiguity margin, and buffer radii 60/120 m. Primary: centre zero, radius 60 m. These fixed conservative choices are not locally validated accuracy guarantees. No fitted registration correction or preferred-result sensitivity selection is allowed.')])
    page('TEMPORAL EVIDENCE    /    STOPPING RULES','Persistence and feasibility gates',[
        ('Seasonal and annual states','Each cell needs at least three clear observations on distinct UTC dates, in at least three months per year-season, spanning at least 60 days. At least three dates must be mutually separated by ten days, using a chronological greedy subset. A seasonal water/land state needs at least 80% agreement among all clear observations; ambiguous clear cells stay in that denominator. Both seasons must pass support, be classified and agree for an annual state. Missing observations are never interpolated.'),
        ('Persistence','All six annual states must be known. Stable land or water requires agreement across all years. A persistent transition has exactly one switch and at least two consecutive annual states on either side: eligible intervals are 2021–2022, 2022–2023 and 2023–2024. Edge switches have insufficient duration; reversals and unknowns remain separate. Observation dates bound an interval rather than a construction or erosion date. Repeated seasons do not eliminate tides, turbidity, flooding or processing effects.'),
        ('Coverage stop','Every window and year-season must have at least 80% of its fixed 2,500 core cells meeting temporal support under both cloud buffers. Evaluate complete seasonal batches in chronological order. At any failure, stop further acquisition and transition inference; report coverage-only feasibility with unacquired periods explicit. No replacement dates/sites or lower gate is allowed.'),
        ('Interpretation and robustness','If coverage passes, every sensitivity needs known annual states for at least 70% of the full core in every year and window. Each alternative must retain the exact primary final category for at least 90% of primary stable/persistent cells, and the direction for at least 80% of primary transition cells. Alternative unknowns count as disagreements; empty denominators cannot pass. Zero transitions mean direction retention is not estimable, not validated precision. Under every sensitivity, at least 95% of baseline-eligible control cells must retain their expected stable class over all six years. Any failed applicable gate stops progression; diagnostic output is retained.')])
    page('BOUNDED INTERPRETATION    /    REVIEW REQUIRED','Outputs and review',[
        ('Area and uncertainty','Compute each core cell polygon area geodesically on WGS84 after transforming its projected corners, using pyproj.Geod. Sum disjoint cells; report square metres and hectares. Keep gross water-to-land and land-to-water areas separate. Coastal totals include only C1–C4, with controls reported separately. Report unknown, ambiguous, reversal and insufficient-duration areas, all six sensitivity values and their ranges. Sensitivity is not a confidence interval; no nominal 30 m area multiplier or pixel-independence significance test is valid.'),
        ('Dated examples','If the interpretation gates pass, select up to ten coastal cells per direction, ten unresolved cells and five per control by ascending SHA-256 of comma-separated window ID, row, column and category, with lexical ties. Include all if fewer. Show every selected date across six years and both seasons, native RGB and green/SWIR context, masking/MNDWI, annual states, processing baseline and spacecraft. Retain disagreements. These examples use the same observations, not independent ground truth.'),
        ('Review and exclusions','Owner review must support the direction of every selected transition example before any later scaling decision. An unresolved cloud, tide or registration explanation blocks scaling. A zero-transition result can establish observational feasibility only. This authorization covers the bounded pilot alone. Do not infer erosion, reclamation, subsidence-driven loss, hazard or risk; do not overlay published deformation, acquire other imagery, reopen the independent benchmark or revise the accepted report.'),
        ('Immutable specification and sources','The machine-readable protocol and its bound catalogue, geometry and resource records are the exact execution specification; preserve them without overwriting. Protocol SHA-256: '+SHA+'. Sentinel-2 calibration and processing descriptions: senti wiki Copernicus S2 Products and S2 Processing (sentiwiki.copernicus.eu/web/s2-products and /s2-processing). MNDWI: Xu (2006), doi:10.1080/01431160600589179. Public data access: Microsoft Planetary Computer Sentinel-2 L2A examples. Copernicus Sentinel data retain their ESA data-notice attribution. Dynamic World shares Sentinel-2 inputs; JRC coverage checked through 2024 supplies no 2025 endpoint and is not acquired here.')])
    d.save(target)
    print(hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
