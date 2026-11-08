"""Freeze geometry-only eligibility and sampling-overlap choices before calculation."""
from pathlib import Path
from datetime import datetime, timezone
import json, hashlib
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/output/phase_c_matched_support_v1'
BASE=ROOT/'data/output/phase_c_geometry_support_v1'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def main():
    if OUT.exists():raise FileExistsError(OUT)
    verified=BASE/'verification.json'
    assert sha(verified)=='fcfb08ed1895ea12ec6f79addd2dfd8488e1bd2941f39d98becee3ede3ac57ba'
    old=read(verified)
    pinned=read(BASE/'inventory_specification.json')['registered_input_sha256']
    for p,h in old['output_sha256'].items():
        pinned[(BASE/p).relative_to(ROOT).as_posix()]=h
    pinned[verified.relative_to(ROOT).as_posix()]=sha(verified)
    pinned.update({
        'data/output/alphaearth_seam_v2/protocol.json':'fec005c9b413df6ddcb197746c188183fec9f671743e53fca65a394e927b735d',
        'data/output/alphaearth_seam_v2/results.json':'763bfa06a8f74e823a91b056c0c856f550f0d8cff4ce124c18c2238c1b82920b',
        'docs/Nabhonil_Sarkar_Jakarta_Phase_B_Optical_Feasibility_Supplement.pdf':'a2a3b489879fa9809a3ce1316131c93e0983da9aa5b438ce6dc2984a927b136b',
        'docs/Nabhonil_Sarkar_Jakarta_Phase_B_Optical_Feasibility_Supplement.docx':'3d40747ab89a8f2b668fd674a228f9aa45444599bec12a8d90eec9cc35adcc9d'})
    manifest=read(ROOT/'data/output/alphaearth_annual_change/gcs_full_v1/cosine_change/manifest.json')
    for years in [(2020,2023),(2020,2025)]:
        item=next(v for v in manifest['comparisons'] if v['years']==list(years))
        pinned[f'data/output/alphaearth_annual_change/gcs_full_v1/cosine_change/cosine_{years[0]}_{years[1]}.tif']=item['sha256']
    for year in [2020,2022]:
        pinned[f'data/output/alphaearth_annual_change/gcs_full_v1/Jakarta_GCS20m_on30m_{year}_qint8.tif']=manifest['annual_sha256'][str(year)]
    for p,h in pinned.items():assert sha(ROOT/p)==h,p
    missing=ROOT/'data/output/alphaearth_annual_change/gcs_full_v1/cosine_change/cosine_2020_2022.tif'
    assert not missing.exists()
    spec={
      'schema':'phase_c_matched_support_diagnostic_v1','frozen_at_utc':datetime.now(timezone.utc).isoformat(),
      'date_local':'2026-11-08','status':'FROZEN_DIAGNOSTIC_ONLY_NOT_PHASE_C_ANALYSIS_APPROVAL',
      'authorization':'Owner authorized proposal, geometry eligibility and sampling overlap only. No motion-value loading or aggregation, association, new endpoint raster, acquisition or publication.',
      'prior_knowledge':'Original report concentration and previous geometry inventory are known. No point-neighbourhood/top-1% overlap or new eligibility-retention counts inspected before this specification.',
      'grid':{'crs':'EPSG:32748','size_m':1000,'origin_m':[0,0],
        'membership':'floor(easting/1000),floor(northing/1000); west/south included, east/north excluded; closed geographic ROI first.',
        'roi':[106.45,-6.54,107.22,-6.01],'reuse':'All 5160 prior grid cells; 4872 full and 288 partial. Never redefine geometry.',
        'sector_reporting':'Reuse original raster-row/column thirds. Summarize unit status for every sector with positive-area intersection; boundary units can occur in multiple sectors (not additive). Overlap uses exact embedding-centre sector membership.',
        'partial_policy':'Primary eligibility excludes partial ROI units, reports them explicitly regardless of point count. Raw geometry, masks and all-point overlaps retain partial units; no area rescaling or softened requirements.'},
      'point_neighbourhoods':{
        'recommended_primary_design':'Within-unit union of valid embedding cells selected around eligible published-point coordinates; one vote per unique embedding cell and equal weight per eligible 1 km unit.',
        'size_status':'UNRESOLVED: nominal 75 m support alone does not establish the footprint shape/orientation or positional-error distribution. No scientifically unique primary size is justified by available local provenance; neither convention is selected by overlap.',
        'nominal_support_basis':'Prior authorized inventory provenance identifies nominal 75 m support. Audited CSV and saved records do not supply per-point footprints or a numerical positional-error bound. Native stored embedding support is 20 m sampled on the frozen nominal 30 m grid; this is not independent 30 m source resolution.',
        'fixed_candidates':[
          {'id':'square75_candidate','definition':'UTM-axis-aligned closed square centred on each point, 75 m side: max(abs(dx),abs(dy)) <=37.5 m.'},
          {'id':'disk75_candidate','definition':'Closed Euclidean disk centred on each point, 75 m diameter: dx^2+dy^2 <=37.5^2 m^2.'}],
        'rationale':'Two nominal-resolution-scale geometric conventions expose shape uncertainty without claiming either is a measured footprint or a positional confidence bound. No inflated radius fitted to overlap; selecting primary size requires later scientific review.',
        'cell_inclusion':'Frozen embedding-cell CENTRE in a neighbourhood, inside closed geographic ROI and existing valid support; no fractional-cell areas, all-touched inclusion or interpolation.',
        'unit_clipping':'Point belongs to exactly one 1 km cell. Its neighbourhood can select only centres assigned to THAT same unit. Neighbours across a unit edge cannot contribute. Boolean OR deduplicates centres within a unit; unique unit membership prevents cross-unit duplication.'},
      'subregions':{'sizes_m':[125,250,500],'origin_m':[0,0],
        'membership':'floor(easting/size),floor(northing/size), west/south included. Exact 8x8,4x4,2x2 nesting within each 1 km unit.',
        'occupied':'At least one currently eligible point; withheld points never occupy a subregion. Select existing valid embedding centres in occupied subregions of the same unit, with closed ROI clipping.',
        'spread_denominator':'Number of subregions with positive projected-area intersection with ROI; full units have 64,16,4. Partial-unit fractions descriptive only.',
        'recommended_sensitivity':'Occupied 250 m subregions with primary A_250 eligibility held FIXED. The 125 and 500 m variants are prespecified geometric sensitivity endpoints, never alternative adopted analysis grids.',
        'interpretation':'Sampling regions, not fully measured footprints. Neither occupancy nor deduplication guarantees representative surfaces.'},
      'eligibility':{'candidate_rules':[
          {'id':'A','min_points':10,'min_occupied_fraction':0.25,'recommended':True},
          {'id':'B','min_points':20,'min_occupied_fraction':0.5,'recommended':False}],
        'shared_spread':'Require eligible points in both 500 m easting halves AND both 500 m northing halves of the unit, in addition to occupied-fraction requirement at each tested subgrid.',
        'rationale':'A prevents summaries from one/few locations and requires multiple separated subregions for a limited represented-surface estimand. B doubles the count and occupied-fraction floors as a conservative sensitivity. These pragmatic prospective screens are not literature standards, precision/power guarantees or evidence of independent samples. Neither rule is chosen by retention or overlap.',
        'proposed_primary':'A at 250 m: >=10 eligible points, >=4 of 16 occupied subregions, both halves on both axes, full ROI cell. Recommendation fixed before new counts.',
        'status_order':['excluded_partial_ROI','empty','sparse_count_and_spread','sparse_count','sparse_spread','eligible'],
        'outputs':'All rules x all three subgrid sizes; status counts overall/by all nine sectors, full/partial distinguished, every unit retained in detailed table.'},
      'overlap':{'definition':'Existing 2020–2025 uncapped float32 cosine distance >= NumPy 99th percentile on float64 values, method=linear, over fixed valid ROI; ties included, no rounding. NW is subset of rectangle-wide top-1%, never reranked.',
        'expected':{'valid_ALL':5619719,'top_ALL':56198,'valid_NW':624512,'top_NW':18096,'cutoff':0.3580920195579531},
        'surfaces':['square75_candidate','disk75_candidate','occupied125','occupied250','occupied500'],
        'unit_filters':['all_eligible_points_including_partial_units','A_250_full_units','B_250_full_units'],
        'denominators':'For each region and each fixed surface/filter: total valid centres and existing top-1% centres in that region; covered counts and 100*covered/total for both. Denominators remain fixed after eligibility exclusions. Zero denominator -> null.',
        'separation':'A_250/B_250 unit filters stay fixed across ALL surface alternatives; separate eligibility tables vary subgrid size. No mixing geometry and changing unit eligibility in one overlap comparison.',
        'stop':'Any raster/header/hash or original membership-count/cutoff discrepancy stops before publishing overlap; no alternative rank or mask.'},
      'future_descriptive_proposal':{
        'embedding_statistic':'Median of unique valid embedding differences in the within-unit neighbourhood union; each included embedding centre once. Not calculated here.',
        'motion_statistic':'Median of eligible unique-coordinate vertical-motion observations whose fixed neighbourhood contains at least one included embedding centre in their unit, equal weight per contributing point. Retain all current exclusions. Not calculated here.',
        'unit_weight':'Equal weight per eligible unit in distributions of unit summaries; no inverse-variance weights, point-count weights or interpreted area expansion.',
        'support_limit':'Motion median is point-weighted, embedding median weights the union centres. Dense overlapping neighbourhoods still imply different within-unit weights; document contributor counts and this imperfect support match. Union deduplication does not establish representative sampling.',
        'duplicate_sensitivity':'Additional whole-unit exclusion wherever an already-withheld conflicting coordinate belongs to that same fixed 1 km unit. Exact unit membership, no proximity radius or reinstatement. Proposed only; not applied to outcomes here.',
        'periods':{'primary':'2020–2023 embedding endpoint versus published 2017–2023 motion; period mismatch and unresolved 2022–2023 elevation explicit.',
          'sensitivity':'2020–2022 endpoint excludes the 2022–2023 transition. Map absent; do not generate now.',
          'secondary':'2020–2025 explicitly secondary; extends beyond motion period.',
          'interpretation':'Agreement indicates robustness to endpoint choice, not proof the jump contributes nothing; disagreement indicates sensitivity without identifying cause.'},
        'missing_endpoint_derivation':'After separate approval, verify frozen 2020/2022 GCS qint8 hashes and grid; mask -128, nonfinite/zero-norm vectors before decoded all-axis operations; decode sign(q)*(q/127.5)^2, normalize 64-axis vectors and compute clip(1-dot,0,2) in float64 then store float32 as existing builder. No independent year normalization or resampling. Verify common comparable support against all intended periods and retain support loss explicitly. Do not add adjacent distances to fabricate an endpoint.',
        'source_component':'Vertical IGS14 cm/year; local-frame east–west component remains separate.',
        'allowed_later_scope':'Strictly descriptive support, distributions and unit counts only; no correlations, regression, significance, bootstrap intervals, inferential uncertainty, independent-validation or causal claims. Formal point uncertainties are not independent errors and must not be naively averaged.'},
      'limits':['Surfaces represented by eligible published observations, not assumed unchanged or radar-stable surfaces.',
        'High overlap means extremes fall within specified sampling regions, not deformation measurement at every extreme centre.',
        'Low overlap limits the ability to address the headline concentration; neither high nor low overlap establishes why observations are missing.',
        'Optical feasibility outcomes are not read or used to select Phase C units.'],
      'map_policy':'No new map required; compact complete tables are the primary deliverables.',
      'registered_input_sha256':pinned,'freeze_code_sha256':sha(Path(__file__)),
      'existing_endpoint_maps':['2020–2023','2020–2025'],'missing_endpoint_map':'2020–2022'}
    OUT.mkdir(exist_ok=False)
    with (OUT/'diagnostic_specification.json').open('x',encoding='utf-8') as f:json.dump(spec,f,indent=2,ensure_ascii=False);f.write('\n')
    h=sha(OUT/'diagnostic_specification.json')
    (OUT/'diagnostic_specification.sha256').write_text(h+'\n',encoding='ascii')
    print(h)
if __name__=='__main__':main()
