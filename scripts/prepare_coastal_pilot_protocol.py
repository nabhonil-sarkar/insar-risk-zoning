"""Freeze a reviewable Phase B proposal from metadata-only evidence."""

from collections import Counter
import json

from scripts import coastal_pilot_feasibility as f
from scripts.coastal_pilot_rules import season_state
import numpy as np


def prepare():
    geom=json.loads((f.OUT/'geometry.json').read_bytes())
    selection=json.loads((f.OUT/'pc_calibrated_selection.json').read_bytes())
    resources=json.loads((f.OUT/'pc_resources.json').read_bytes())
    if (resources['selection_sha256']!=f.digest(f.OUT/'pc_calibrated_selection.json')
            or selection['geometry_sha256']!=f.digest(f.OUT/'geometry.json')
            or resources['pixel_bytes_read']!=0 or not resources['budget_feasible']):
        raise ValueError('Evidence chain/budget failed')
    selected=selection['selected_items']
    if len(selected)!=96 or {i['id'] for i in selected}!={r['item'] for r in resources['scenes']}:
        raise ValueError('Incomplete selected-scene metadata audit')
    available=[]
    for year in range(2020,2026):
        for name,months in [('Jan-Apr',(1,2,3,4)),('Jun-Sep',(6,7,8,9))]:
            subset=[i for i in selected if int(i['properties']['datetime'][:4])==year and int(i['properties']['datetime'][5:7]) in months]
            dates=sorted(i['properties']['datetime'][:10] for i in subset)
            temporal_possible=bool(season_state(dates,np.ones((len(dates),1),bool),np.ones((len(dates),1),int))[0][0])
            if len(dates)!=8 or not temporal_possible:raise ValueError('Catalogue temporal support fails')
            available.append(dict(year=year,season=name,dates=dates,catalogue_scenes=len(dates),
                                  processing_baselines=dict(Counter(i['properties']['s2:processing_baseline'] for i in subset)),
                                  temporal_support_possible=True,clear_pixel_support='unmeasured'))
    evidence={name:f.digest(f.OUT/name) for name in ('geometry.json','windows.png','catalogue_selection.json','pc_selection.json','pc_calibrated_selection.json','pc_resources.json')}
    code={name:f.digest(f.ROOT/name) for name in ('scripts/coastal_pilot_feasibility.py','scripts/coastal_pilot_pc.py','scripts/coastal_pilot_rules.py','scripts/prepare_coastal_pilot_protocol.py','tests/test_coastal_pilot.py')}
    proposal=dict(
        schema='coastal_transition_pilot_protocol_v1', prepared_date='2026-11-05',
        status='PROPOSED; exact-hash owner approval required before optical acquisition; not an executed or validated method',
        question='Can repeated public observations support persistent water-to-land or land-to-water transitions in six bounded NW windows during 2020-2025?',
        scope='Four coastal cores and two controls; no regional extrapolation, benchmark rescue, subsidence overlay, new InSAR or report revision. Original NW sector is not administrative North Jakarta.',
        prior_knowledge='Existing embedding maps and aggregates and Phase A result are known. Selection uses only 2020 WorldCover geometry and scene metadata, not embedding scores or new spectral outcomes. WorldCover and control labels do not prove unchanged locations.',
        approvals=dict(required_before='Any Sentinel-2 spectral/SCL pixel blocks, thumbnails, quicklooks or classification',
                       proposed_next_action='Approve this exact hash for the bounded acquisition and pilot under all gates; first implement a fail-closed acquisition/inference runner, update the sole methodology for the adopted design, run the full suite, and record a clean local executing commit. No push.',
                       recording='Separate write-once approval record with exact protocol SHA-256 and owner wording; never edit protocol bytes. Any scientific rule/source/window/scene change needs a new prospective version and review.'),
        evidence_sha256=evidence, preparation_code_sha256=code,
        geometry=dict(crs=geom['crs'],analysis_cell_m=20,core_side_m=1000,halo_m=160,
                      windows=geom['windows'],selection=geom['selection'],
                      nominal_core_cells_per_window=2500,core_area='Six nominal 1 km squares; report geodesic WGS84 cell polygon areas, not 30 m counts. Controls excluded from coastal transition totals.',
                      baseline_control_eligible='L1: 2020 WC non-water class at 20 m centre; W1: northern-connected sea-proxy cell. Reconstruct from pinned geometry algorithm/tile; not independent validation.'),
        source=dict(provider='Microsoft Planetary Computer',collection='sentinel-2-l2a',tile='48MXU',
                    assets=['B02','B03','B04','B08','B11','SCL'],licence='Copernicus Sentinel data subject to ESA Sentinel Data Legal Notice; retain Copernicus Sentinel source/year and provider attribution. No paid imagery, account or subscription created.',
                    access='Public catalogue and public container-scoped read signing succeeded. Cache token in memory only; respect rate limits, never record token in provenance. HEAD/206 byte ranges with ETags checked for every selected asset.',
                    alternative_findings='Earth Search C1 2022 inventory has six items; inadequate uniform C1 route. PC PB>=05-only has no 2020/2021 items here. Both audits retained. Earth Search legacy not mixed in; its reported calibration metadata inconsistency remains unresolved.',
                    calibration='Raw COG DNs; mask DN=0 first. Per selected product XML BOA_QUANTIFICATION_VALUE=10000. PB02.12/03.00: absent BOA offset, use 0 by ESA convention. PB04.00/05.09/05.10/05.11: required BOA_ADD_OFFSET=-1000 for IDs 1,2,3,7,11. Reflectance=(DN+offset)/10000 exactly once. Reject any other/contradictory baseline, quantification, offset or band mapping.',
                    harmonization_limit='This aligns reflectance encoding, not full cross-version algorithm, atmospheric correction, sensor radiometry or geolocation. It is not a uniformly reprocessed/harmonized archive. PB and spacecraft must accompany each date, coverage table and example. Conclusions crossing processing-version boundaries remain conditional on sensitivity and reviewed direct imagery.',
                    quality='20 m Sen2Cor SCL only. No separate cloud-probability asset on this route. No hidden fallback to unmasked reflectance or another collection.',
                    archive_limit='Exhausted PC next links but no numberMatched is supplied; inventory is this catalogue snapshot, not proof of a complete satellite archive.'),
        observations=dict(years=list(range(2020,2026)),seasons={'Jan-Apr':[1,2,3,4],'Jun-Sep':[6,7,8,9]},
                          seasons_reason='Fixed four-month contrasting calendar windows spanning repeated observations; not universal monsoon boundaries or tide matching. May and Oct-Dec are excluded prospectively.',
                          selection='Deduplicate exact acquisition timestamp/platform/tile by latest generation time then ID. Within each calendar half-month (1-15,16-end), choose lowest finite whole-tile eo:cloud_cover then acquisition timestamp then ID among full six-window+halo footprint scenes. One date is one vote. No local cloud pixels inspected for selection; no cloud-percent cutoff.',
                          maximum_scenes=96,actual_dates_and_baselines=available,
                          replacements='None after pixel inspection, download failure or poor support. Retain missing scenes/years/windows; stop if gates fail. No extra-date search, provider mixing, shortened period or window replacement.'),
        spatial_processing=dict(grid='Native EPSG:32748 20 m zero-anchored lattice, 50x50 core with eight-cell halo. B11/SCL native 20 m; average each aligned 2x2 B02/B03/B04/B08 block after calibration, requiring all four finite native contributors. No 10 m claim for B11 and no embedding-grid resampling.',
                                validity='Expected uint16 reflectance DN 0..32767; 0 masked before offset. Reject unexpected datatype/code/range, CRS, shape, transform, alignment or version. SCL categories use nearest/native samples only. Verify actual GeoTIFF geokeys/transform before accepting pixel output; metadata audit has checked STAC transforms and TIFF dimensions.',
                                geolocation='No result-fitted registration shift. Conservative one-cell uniform-neighbour erosion limits mixed/edge evidence but does not establish registration accuracy. Show native RGB/SWIR edge alignment for dated review; visible cross-date misregistration that could explain a transition makes it unresolved and prevents scaling.'),
        date_rule=dict(clear_support='Finite calibrated B03/B11, SCL in {4,5,6}, outside the cloud/shadow buffer. Counts include spectrally ambiguous clear cells; never remove ambiguity from the agreement denominator.',
                       masked_scl=[0,1,2,3,7,8,9,10,11],buffer_seeds=[2,3,8,9,10],
                       primary_cloud_shadow_buffer_m=60,strict_buffer_m=120,
                       buffer_metric='Euclidean distance between 20 m cell centres <= radius; dilation on full halo before core crop.',
                       index='MNDWI=(B03-B11)/(B03+B11), only when both reflectances >=0 and sum>0.02. Noneligible clear pixels remain ambiguous. No clipping negative reflectance into a class.',
                       primary_water='MNDWI>+0.10',primary_land='MNDWI<-0.10',ties_and_middle='ambiguous',
                       mixed_rule='A date label requires all 3x3 neighbouring 20 m cells to have the same strong raw spectral label. Any masked/ambiguous neighbour defeats the label. Outside-read neighbours are invalid; halo prevents core edge artefacts.',
                       sensitivity='Six Cartesian combinations: threshold centres {-0.05,0,+0.05}, each with +/-0.10 ambiguity margin, and cloud/shadow buffers {60,120} m. Primary centre=0, buffer=60. Preserve every combination; no best-case selection.',
                       rationale='MNDWI green/SWIR formula follows Xu (2006). Zero is a heuristic boundary, not a validated local threshold. +/-0.10 ambiguity margin, +/-0.05 shifts, sum floor, 60/120 m buffers and 20 m neighbourhood are conservative prospective pilot choices. They are not accuracy guarantees or fitted values.'),
        temporal_rule=dict(per_cell_per_year_season='At least 3 clear observations on 3 distinct UTC dates in at least 3 distinct months, first-to-last >=60 days, and at least 3 dates mutually >=10 days apart (greedy chronological subset). A missing date never becomes a clear vote.',
                           seasonal_state='Water or land only if at least 80% of ALL clear observations have that strong date label, including ambiguous clear observations in the denominator. Otherwise ambiguous; inadequate temporal support is separately marked unknown. Zero denominator remains unknown.',
                           annual_state='Both calendar seasons must independently pass support, be classified, and agree. No interpolation or majority across seasons.',
                           persistence='Require known annual states in all six years. Stable water/land if all six agree. Persistent transition requires exactly one switch and >=2 consecutive annual states on each side; eligible switch intervals are 2021-2022,2022-2023,2023-2024. Edge switches 2020-2021/2024-2025 have insufficient duration; reversals/transient water remain separate. Every year is still reported.',
                           interpretation='Nominal dates bound a change interval, not its construction/erosion date. Two seasons and multi-year persistence reduce but do not remove tidal, turbidity, flooding and processing effects. No tide observations are acquired; unresolved tidal/mixed areas cannot be called land loss.'),
        stop_and_scale=dict(temporal_support='For EACH of six windows and EACH year-season, >=80% of all 2500 core cells must meet clear-date/month/spacing support in BOTH buffer settings. Failures stop transition inference and yield coverage-only feasibility output.',
                            interpretability='If support passes, classify all six fixed sensitivities. Under EVERY sensitivity, >=70% of all core cells per window must have known annual states in EVERY year. Unknown/ambiguous remains in the fixed core denominator. Failure permits diagnostic maps but no scale-up.',
                            robustness='For EACH window and EACH alternative, >=90% of primary final stable/persistent cells must retain the exact same final category; an alternative unknown/reversal/edge-duration counts as disagreement. Empty primary denominator is not estimable and cannot pass. Among primary persistent-transition cells, >=80% must retain direction in EACH alternative; if none exist, explicitly NA, not evidence of transition accuracy.',
                            controls='In EACH sensitivity, >=95% of baseline-eligible L1/W1 cells must remain stable in the expected land/water class across all six years, with missing/ambiguous counted as not retained. These are baseline-based diagnostics, not known unchanged truth. Failure stops scale-up and requires diagnosis, never replacement controls.',
                            examples='Owner review required before scaling. Select up to 10 cells per direction across coastal cores, up to 10 unresolved cells, and 5 per control by ascending SHA256(window_id,row,col,category) with comma-separated ASCII fields and lexical ties. Include all if fewer; state small/zero counts. For each cell show all selected dates in six-year Jan-Apr/Jun-Sep contact sheets, native RGB and green/SWIR context, validity/MNDWI, annual states and baseline/spacecraft. Retain all examples, including disagreements. No new image acquisition for examples.',
                            review_gate='All selected transition examples must be supported as the stated persistent direction by direct imagery; any ambiguous, cloud, tide or registration explanation blocks scale-up pending a separately specified study. Review uses the same Sentinel-2 observations, not independent ground truth or an accuracy estimate. If zero transitions, assess observational feasibility only; do not claim validated transition precision.',
                            failure='Report exact failed gates and denominators; preserve evidence. No thresholds lowered, failed sites replaced or automatic rescue tests.'),
        outputs=dict(namespace=str(f.OUT.relative_to(f.ROOT)).replace('\\','/'),
                     records=['source IDs, versions, XML hashes, ETags, byte-range checksums and actual dates','per-window/year/season coverage: selected/available/clear counts, month/spacing support, masked/ambiguous/unknown fractions','all six annual state maps and all five interval tables, with insufficient-duration/reversal/unknown explicit','gross water-to-land and land-to-water geodesic areas separately, controls separate, unknown area and all six sensitivity values/ranges','deterministically selected dated review examples and owner review record'],
                     area='Transform each 20 m cell polygon to lon/lat and use pyproj.Geod WGS84 polygon_area_perimeter absolute area. Sum disjoint core cells. Report m2 and hectares; no population/hazard/risk attribution, regional extrapolation or nominal30m multiplier.',
                     uncertainty='Sensitivity min/max is not a confidence interval. No pixel-independence p values, causal attribution, erosion/reclamation labels, absolute subsidence or independent-validation claims.',
                     ancillary='No Dynamic World/JRC acquisition required for this pilot. DW would share Sentinel-2 inputs. JRC currently ends in 2024, not a 2025 endpoint; any later ancillary addition needs a separate version.'),
        resources={k:v for k,v in resources.items() if k not in ('scenes','schema')},
        execution_checks=dict(before_any_pixels='Exact protocol approval; SHA256 match for geometry/selection/resource/XML bundle and source metadata; clean local executing commit; full tests pass; free disk >=2*transfer ceiling+1 GiB. Verify and log expected ETags using If-Match. Changes abort before pixel payload.',
                              transfer='Only registered native blocks needed by the six halo windows, deduplicated across windows. Total bytes including retries/metadata capped at approved ceiling; at most two retries for transient network/429/5xx, respect Retry-After, stop if two-hour wall time reached. No full-object HTTP200 fallback. No alternate scenes, bands, overviews or thumbnail downloads.',
                              access_failures='Permission/token failures stop; token refresh for the same public container allowed without changing source. Rate-limited access is paced, not routed around.',
                              byte_integrity='Native tile ETags and offsets pinned; cache each received range with SHA256. Provider full-file checksums are not locally verified by partial reads. Output tables/maps and logs have a final immutable hash manifest.',
                              required_tests='Synthetic permanent transitions, reversals, short duration, ambiguity, cloud buffers, low/zero coverage, distinct dates/months/spacing, calibration across PB04 boundary, nodata, grid/area units, protocol/approval/hash/ETag failure before payload, byte cap/no-full-file response, every gate boundary and non-overwrite. Current array/metadata tests are preparation; acquisition/inference runner and its tests must be complete before real execution.'),
        sources=[
            {'url':'https://sentiwiki.copernicus.eu/web/s2-products','use':'Native support, DN nodata and PB04 reflectance offset formula'},
            {'url':'https://sentiwiki.copernicus.eu/web/s2-processing','use':'Processing baselines and algorithm/geolocation changes; calibration does not erase these'},
            {'url':'https://github.com/microsoft/PlanetaryComputerExamples/blob/main/datasets/sentinel-2-l2a/sentinel-2-l2a-example.ipynb','use':'Public Planetary Computer Sentinel-2 access'},
            {'url':'https://github.com/Element84/earth-search','use':'Best-effort catalogue limitations'},
            {'url':'https://github.com/Element84/earth-search/issues/66','use':'Reported legacy metadata-offset inconsistency; not a verified explanation for all legacy products'},
            {'url':'https://doi.org/10.1080/01431160600589179','use':'Xu 2006 original modified normalized difference water index'},
            {'url':'https://www.mdpi.com/2073-4441/9/4/256','use':'Primary evaluation of water indices; thresholds depend on conditions'},
            {'url':'https://global-surface-water.appspot.com/download','use':'Coverage through 2024 checked 2026-11-05; not used as 2025 data'}])
    f.write_new(f.OUT/'protocol.json',proposal)
    print('Protocol SHA-256:',f.digest(f.OUT/'protocol.json'))


if __name__=='__main__':
    prepare()
