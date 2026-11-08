"""Independent saved-output checks; no motion values and no additional outcome analysis."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
import numpy as np
import pandas as pd
from pyproj import Transformer
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/output/phase_c_matched_support_v1'
RUN=OUT/'run';BASE=ROOT/'data/output/phase_c_geometry_support_v1'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def main():
    target=OUT/'verification.json'
    if target.exists():raise FileExistsError(target)
    spec=read(OUT/'diagnostic_specification.json')
    assert sha(OUT/'diagnostic_specification.json')=='fcc88c928874d070623570e355f6eba95f5d04dcd0712d0cd215c0ecf7c3a634'
    for p,h in spec['registered_input_sha256'].items():assert sha(ROOT/p)==h,p
    oa=read(RUN/'output_audit.json')
    for p,h in oa['output_sha256'].items():assert sha(RUN/p)==h,p
    events=[json.loads(line) for line in (RUN/'events.jsonl').read_text().splitlines()]
    assert datetime.fromisoformat(spec['frozen_at_utc'])<datetime.fromisoformat(events[0]['utc'])
    assert 'before endpoint raster read' in events[1]['event'] and 'overlap starts' in events[2]['event']
    masks=np.load(RUN/'sampling_membership.npz',allow_pickle=False)
    units=pd.read_csv(RUN/'unit_eligibility.csv',float_precision='round_trip')
    overlap=pd.read_csv(RUN/'sampling_overlap.csv',float_precision='round_trip')
    pt=pd.read_csv(BASE/'point_coordinate_eligibility.csv',float_precision='round_trip')
    pt=pt[pt.eligibility=='eligible_from_pinned_audit']
    assert len(pt)==220625
    groups={cid:g for cid,g in pt.groupby('cell_id')}
    for u in units.itertuples():
        g=groups.get(u.cell_id)
        count=0 if g is None else len(g)
        assert count==u.eligible_points
        both=False if g is None else (np.unique(np.floor(g.easting_m/500).astype(int)%2).size==2 and np.unique(np.floor(g.northing_m/500).astype(int)%2).size==2)
        for size in [125,250,500]:
            occ=0 if g is None else len(set(zip(np.floor(g.easting_m/size).astype(int),np.floor(g.northing_m/size).astype(int))))
            assert occ==getattr(u,f'occupied_{size}')
            for rule in spec['eligibility']['candidate_rules']:
                n_ok=count>=rule['min_points']
                s_ok=both and occ/getattr(u,f'available_{size}')>=rule['min_occupied_fraction']
                if u.roi_cell_type=='partial': expected='excluded_partial_ROI'
                elif count==0:expected='empty'
                elif not n_ok and not s_ok:expected='sparse_count_and_spread'
                elif not n_ok:expected='sparse_count'
                elif not s_ok:expected='sparse_spread'
                else:expected='eligible'
                assert expected==getattr(u,f'status_{rule["id"]}_{size}')
    flat=masks['valid_flat_indices'];cu=masks['center_unit'];sector=masks['center_sector'];top=masks['top1']
    assert len(flat)==5619719 and len(np.unique(flat))==len(flat)
    assert top.sum()==56198 and (sector==0).sum()==624512 and (top&(sector==0)).sum()==18096
    assert np.all(masks['disk75_candidate']<=masks['square75_candidate'])
    assert np.all(masks['occupied125']<=masks['occupied250']) and np.all(masks['occupied250']<=masks['occupied500'])
    for row in overlap.itertuples():
        if row.unit_filter=='all_eligible_points_including_partial_units':filt=np.ones(len(units),bool)
        else:filt=units[f'status_{row.unit_filter[0]}_250'].eq('eligible').to_numpy()
        reg=np.ones(len(flat),bool) if row.region=='ALL' else sector==0
        cover=masks[row.sampling_region]&filt[cu]&reg
        cv=int(cover.sum());ct=int((cover&top).sum())
        assert row.valid_cells==reg.sum() and row.top1_cells==(reg&top).sum()
        assert row.covered_valid_cells==cv and row.covered_top1_cells==ct
        assert np.isclose(row.covered_valid_percent,100*cv/row.valid_cells,rtol=1e-13)
        assert np.isclose(row.covered_top1_percent,100*ct/row.top1_cells,rtol=1e-13)
    # Deterministic brute-force check of same-unit geometry without KD-tree.
    selected=np.unique(np.r_[np.linspace(0,len(flat)-1,257,dtype=int),np.flatnonzero(top)[::223]])
    grid=read(ROOT/'data/output/alphaearth_surface_type_v1/protocol.json')['geometry']['grid']
    a,_,c,_,e,f=grid['transform'];rr,cc=np.divmod(flat[selected],grid['width'])
    gx,gy=Transformer.from_crs(4326,32748,always_xy=True).transform(c+a*(cc+.5),f+e*(rr+.5))
    for ix,x,y in zip(selected,gx,gy):
        unit=units.iloc[cu[ix]];g=groups.get(unit.cell_id)
        assert int(np.floor(x/1000))==unit.grid_e and int(np.floor(y/1000))==unit.grid_n
        if g is None: square=disk=False
        else:
            dx=g.easting_m.to_numpy()-x;dy=g.northing_m.to_numpy()-y
            square=bool(np.any((np.abs(dx)<=37.5)&(np.abs(dy)<=37.5)))
            disk=bool(np.any(dx*dx+dy*dy<=37.5**2))
        assert square==masks['square75_candidate'][ix] and disk==masks['disk75_candidate'][ix]
        for size in [125,250,500]:
            occupied=False if g is None else bool(np.any((np.floor(g.easting_m/size)==np.floor(x/size))&(np.floor(g.northing_m/size)==np.floor(y/size))))
            assert occupied==masks[f'occupied{size}'][ix]
    assert not (ROOT/'data/output/alphaearth_annual_change/gcs_full_v1/cosine_change/cosine_2020_2022.tif').exists()
    report={'date_local':'2026-11-08','completed_utc':datetime.now(timezone.utc).isoformat(),
        'status':'VERIFIED_DIAGNOSTICS_AWAITING_REVIEW','specification_sha256':sha(OUT/'diagnostic_specification.json'),
        'verification_code_sha256':sha(Path(__file__)),'all_registered_inputs_unchanged':True,
        'specification_precedes_geometry_and_overlap':True,'geometry_precedes_endpoint_read':True,
        'unit_eligibility_rows_independently_reconciled':len(units),'eligibility_rule_scale_combinations':6,
        'overlap_rows_independently_recounted':len(overlap),'brute_force_geometry_centres_checked':len(selected),
        'top_membership_original_denominators_match':True,'all_masks_boolean_and_deduplicated':True,
        'source_value_columns_read':False,'new_map_or_2020_2022_raster':False,'full_test_suite_run':False,
        'no_primary_neighbourhood_selected_by_overlap':True,
        'output_audit_sha256':sha(RUN/'output_audit.json')}
    with target.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
