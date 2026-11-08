"""Authorized geometry eligibility and endpoint extreme-membership overlap only."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,json,platform,sys
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from shapely.geometry import box
from scipy.spatial import cKDTree
from pyproj import Transformer
import rasterio
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/output/phase_c_geometry_support_v1'
OUT=ROOT/'data/output/phase_c_matched_support_v1'
SPEC_HASH='fcc88c928874d070623570e355f6eba95f5d04dcd0712d0cd215c0ecf7c3a634'
SECTORS=['NW','N','NE','W','C','E','SW','S','SE']
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,obj):
    with p.open('x',encoding='utf-8') as f:json.dump(obj,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')
def event(message):
    with (OUT/'run/events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'utc':datetime.now(timezone.utc).isoformat(),'event':message})+'\n')
def fixed_geometry_checks():
    point=np.array([[0.,0.],[0.,0.]])
    centres=np.array([[37.5,0],[37.5,37.5],[37.50001,0],[0,0]])
    kd=cKDTree(point)
    square=kd.query(centres,p=np.inf)[0]<=37.5
    disk=kd.query(centres,p=2)[0]<=37.5
    assert square.tolist()==[True,True,False,True]
    assert disk.tolist()==[True,False,False,True]
    assert np.array_equal(square,cKDTree(point[:1]).query(centres,p=np.inf)[0]<=37.5)
    # A neighbourhood crossing a unit edge cannot vote in its neighbour's unit.
    xy=np.array([[999.,500.],[1000.,500.]])
    assert np.floor(xy[:,0]/1000).astype(int).tolist()==[0,1]
    assert ((cKDTree([[999.,500.]]).query(xy)[0]<=37.5)&(np.floor(xy[:,0]/1000)==0)).tolist()==[True,False]

def main():
    assert sha(OUT/'diagnostic_specification.json')==SPEC_HASH
    spec=read(OUT/'diagnostic_specification.json')
    run=OUT/'run'
    if run.exists():raise FileExistsError(run)
    for p,h in spec['registered_input_sha256'].items():assert sha(ROOT/p)==h,p
    fixed_geometry_checks()
    run.mkdir(exist_ok=False)
    write(run/'execution_provenance.json',{'specification_sha256':SPEC_HASH,'runner_sha256':sha(Path(__file__)),
        'started_utc':datetime.now(timezone.utc).isoformat(),'date_local':'2026-11-08','python':sys.version,
        'platform':platform.platform(),'numpy':np.__version__,'pandas':pd.__version__,'rasterio':rasterio.__version__,
        'input_hashes_passed':len(spec['registered_input_sha256']),'synthetic_geometry_invariants_passed':True,
        'motion_value_columns_loaded':False,'new_acquisition_requests':0,'full_test_suite_run':False})
    event('Frozen specification and all registered hashes verified; geometry only starts')
    points=pd.read_csv(BASE/'point_coordinate_eligibility.csv',float_precision='round_trip')
    assert points.source_rows.sum()==312374
    ep=points[points.eligibility=='eligible_from_pinned_audit'].copy()
    assert len(ep)==220625 and len(points)-len(ep)==40661
    cells=pd.read_csv(BASE/'grid_support_1km.csv',float_precision='round_trip').sort_values(['grid_e','grid_n']).reset_index(drop=True)
    unitkeys=(cells.grid_e.to_numpy()*100000+cells.grid_n.to_numpy()).astype(np.int64)
    def unitindex(e,n):
        key=e*100000+n;idx=np.searchsorted(unitkeys,key)
        assert (idx<len(unitkeys)).all() and np.array_equal(unitkeys[idx],key)
        return idx
    pi=unitindex(ep.grid_e.to_numpy(),ep.grid_n.to_numpy())
    ep['unit_idx']=pi
    assert np.array_equal(np.bincount(pi,minlength=len(cells)),cells.eligible_points)
    ep['half_e']=np.floor(ep.easting_m/500).astype(int)%2
    ep['half_n']=np.floor(ep.northing_m/500).astype(int)%2
    halfe=ep.groupby('unit_idx').half_e.nunique().reindex(range(len(cells)),fill_value=0).to_numpy()
    halfn=ep.groupby('unit_idx').half_n.nunique().reindex(range(len(cells)),fill_value=0).to_numpy()
    cells['both_easting_halves']=halfe==2;cells['both_northing_halves']=halfn==2
    geo=gpd.read_file(BASE/'candidate_grid.geojson').to_crs(32748).set_index('cell_id').loc[cells.cell_id]
    sectors=gpd.read_file(BASE/'study_sectors.geojson').to_crs(32748)
    roi=sectors.geometry.union_all()
    subkeys={};occupied={}
    for size in [125,250,500]:
        se=np.floor(ep.easting_m/size).astype(np.int64).to_numpy()
        sn=np.floor(ep.northing_m/size).astype(np.int64).to_numpy()
        key=se*1000000+sn
        subkeys[size]=np.unique(key)
        sg=pd.DataFrame({'i':pi,'key':key}).groupby('i').key.nunique()
        cells[f'occupied_{size}']=sg.reindex(range(len(cells)),fill_value=0).to_numpy()
        nsub=1000//size
        available=np.full(len(cells),nsub*nsub,dtype=int)
        for i in np.flatnonzero(cells.roi_cell_type.eq('partial')):
            ce,cn=cells.loc[i,['grid_e','grid_n']]
            available[i]=sum(box(ce*1000+ee*size,cn*1000+nn*size,ce*1000+(ee+1)*size,cn*1000+(nn+1)*size).intersection(roi).area>1e-8
                for ee in range(nsub) for nn in range(nsub))
        cells[f'available_{size}']=available
        cells[f'occupied_fraction_{size}']=cells[f'occupied_{size}']/available
        assert (cells[f'occupied_{size}']<=available).all()
        for rule in spec['eligibility']['candidate_rules']:
            countok=cells.eligible_points>=rule['min_points']
            spreadok=(cells[f'occupied_fraction_{size}']>=rule['min_occupied_fraction'])&(halfe==2)&(halfn==2)
            cells[f'status_{rule["id"]}_{size}']=np.select([
                cells.roi_cell_type.eq('partial'),cells.eligible_points.eq(0),~countok&~spreadok,~countok,~spreadok],
                ['excluded_partial_ROI','empty','sparse_count_and_spread','sparse_count','sparse_spread'],default='eligible')
    full=cells.roi_cell_type.eq('full').to_numpy()
    for size in [125,250,500]:
        assert np.all((cells[f'status_B_{size}']=='eligible') <= (cells[f'status_A_{size}']=='eligible'))
    assert np.array_equal(cells.occupied_250,cells.occupied_250m_subcells)
    cells['has_withheld_coordinate']=cells.withheld_conflicting_points>0
    # Construct frozen embedding centre geometry. No outcome raster opened yet.
    grid=read(ROOT/'data/output/alphaearth_surface_type_v1/protocol.json')['geometry']['grid']
    a,_,c,_,e,f=grid['transform'];h,w=grid['height'],grid['width']
    cols=np.arange(w);rows=np.arange(h)
    xx,yy=np.meshgrid(c+a*(cols+.5),f+e*(rows+.5))
    valid=(xx>=106.45)&(xx<=107.22)&(yy>=-6.54)&(yy<=-6.01)
    flat=np.flatnonzero(valid);assert len(flat)==5619719
    tx=Transformer.from_crs(4326,32748,always_xy=True)
    gx,gy=tx.transform(xx.ravel()[flat],yy.ravel()[flat]);del xx,yy
    center_unit=unitindex(np.floor(gx/1000).astype(int),np.floor(gy/1000).astype(int))
    assert np.array_equal(np.bincount(center_unit,minlength=len(cells)),cells.embedding_valid_centres)
    row,col=np.divmod(flat,w)
    center_sector=np.searchsorted([656,1312],row,side='right')*3+np.searchsorted([953,1906],col,side='right')
    masks={}
    for size in [125,250,500]:
        key=np.floor(gx/size).astype(np.int64)*1000000+np.floor(gy/size).astype(np.int64)
        masks[f'occupied{size}']=np.isin(key,subkeys[size],assume_unique=False)
    assert np.all(masks['occupied125']<=masks['occupied250']) and np.all(masks['occupied250']<=masks['occupied500'])
    assert masks['occupied250'].sum()==3640253
    masks['square75_candidate']=np.zeros(len(flat),bool)
    masks['disk75_candidate']=np.zeros(len(flat),bool)
    order=np.argsort(center_unit,kind='stable');starts=np.searchsorted(center_unit[order],np.arange(len(cells)+1))
    pg={i:g[['easting_m','northing_m']].to_numpy() for i,g in ep.groupby('unit_idx')}
    contributors={k:np.zeros(len(cells),int) for k in ['square75_candidate','disk75_candidate']}
    for i in range(len(cells)):
        ids=order[starts[i]:starts[i+1]]
        if i not in pg or not len(ids):continue
        cxy=np.column_stack([gx[ids],gy[ids]])
        pkd=cKDTree(pg[i]);ckd=cKDTree(cxy)
        for name,p in [('square75_candidate',np.inf),('disk75_candidate',2)]:
            masks[name][ids]=pkd.query(cxy,k=1,p=p)[0]<=37.5
            contributors[name][i]=int((ckd.query(pg[i],k=1,p=p)[0]<=37.5).sum())
    assert np.all(masks['disk75_candidate']<=masks['square75_candidate'])
    for name,mask in masks.items():cells[f'covered_centres_{name}']=np.bincount(center_unit[mask],minlength=len(cells))
    for name,count in contributors.items():cells[f'contributing_points_{name}']=count
    cells.to_csv(run/'unit_eligibility.csv',index=False,mode='x')
    summaries=[]
    intersects={'ALL':np.ones(len(cells),bool)}
    for rec in sectors.itertuples():intersects[rec.sector]=shapely.area(shapely.intersection(geo.geometry.to_numpy(),rec.geometry))>1e-6
    for rule in ['A','B']:
        for size in [125,250,500]:
            status=cells[f'status_{rule}_{size}']
            for sector,ix in intersects.items():
                for celltype in ['full','partial']:
                    keep=ix&cells.roi_cell_type.eq(celltype).to_numpy()
                    r={'rule':rule,'subgrid_m':size,'sector':sector,'roi_cell_type':celltype,'units':int(keep.sum())}
                    for label in spec['eligibility']['status_order']:r[label]=int(((status==label)&keep).sum())
                    assert sum(r[k] for k in spec['eligibility']['status_order'])==r['units']
                    summaries.append(r)
    eligibility=pd.DataFrame(summaries)
    eligibility.to_csv(run/'eligibility_by_sector.csv',index=False,mode='x')
    overview=[]
    for rule in ['A','B']:
        for size in [125,250,500]:
            for sector in ['ALL','NW']:
                rowsum=eligibility[(eligibility.rule==rule)&(eligibility.subgrid_m==size)&(eligibility.sector==sector)]
                values=rowsum[list(spec['eligibility']['status_order'])].sum()
                overview.append({'rule':rule,'subgrid_m':size,'sector':sector,'total_units':int(rowsum.units.sum()),
                    'excluded_partial':int(values.excluded_partial_ROI),'empty_full':int(values['empty']),
                    'sparse_full':int(values.sparse_count_and_spread+values.sparse_count+values.sparse_spread),'eligible_full':int(values.eligible)})
    pd.DataFrame(overview).to_csv(run/'eligibility_overview.csv',index=False,mode='x')
    write(run/'geometry_checks.json',{'eligible_points':len(ep),'withheld_points':40661,'units':len(cells),
        'full_units':int(full.sum()),'partial_units':int((~full).sum()),'valid_centres':len(flat),
        'nested_subregion_masks_verified':True,'disk_subset_square_verified':True,
        'counts_match_prior_geometry_inventory':True,'A_250_recommended_before_retention':True,
        'ambiguous_neighbourhood_geometry_remains_unresolved':True,
        'point_contributors':{k:int(v.sum()) for k,v in contributors.items()},
        'units_containing_withheld_coordinate':int(cells.has_withheld_coordinate.sum())})
    event('Geometry masks and all eligibility tables completed and saved before endpoint raster read')
    # Only now recover the previously defined top-1% membership, without motion.
    endpoint=ROOT/'data/output/alphaearth_annual_change/gcs_full_v1/cosine_change/cosine_2020_2025.tif'
    with rasterio.open(endpoint) as ds:
        assert ds.width==w and ds.height==h and ds.crs.to_epsg()==4326
        assert list(ds.transform)[:6]==grid['transform']
        z=ds.read(1,masked=True)
    values=np.asarray(z.data,dtype=np.float64)
    actual=~np.ma.getmaskarray(z)&np.isfinite(values)&(values>=0)&(values<=2)&valid
    assert np.array_equal(actual,valid)
    cutoff=float(np.percentile(values[actual],99,method='linear'))
    top=values.ravel()[flat]>=cutoff
    nw=center_sector==0
    observed=(len(flat),int(top.sum()),int(nw.sum()),int((top&nw).sum()))
    assert observed==(5619719,56198,624512,18096),observed
    assert cutoff==spec['overlap']['expected']['cutoff'],cutoff
    stored=read(ROOT/'data/output/alphaearth_seam_v2/results.json')['endpoint_sensitivity']['original']
    assert cutoff==stored['cutoff'] and top.sum()==stored['extreme_share']['d'] and (top&nw).sum()==stored['extreme_share']['n']
    del values,z,actual
    event('Exact report threshold, tie rule and ALL/NW membership counts reproduced; overlap starts')
    filters={'all_eligible_points_including_partial_units':np.ones(len(cells),bool),
        'A_250_full_units':cells.status_A_250.eq('eligible').to_numpy(),
        'B_250_full_units':cells.status_B_250.eq('eligible').to_numpy()}
    overlap=[]
    for name in spec['overlap']['surfaces']:
        for filt,unitkeep in filters.items():
            covered=masks[name]&unitkeep[center_unit]
            for region,regionmask in [('ALL',np.ones(len(flat),bool)),('NW',nw)]:
                v=int(regionmask.sum());t=int((top&regionmask).sum())
                cv=int((covered&regionmask).sum());ct=int((covered&top&regionmask).sum())
                overlap.append({'sampling_region':name,'unit_filter':filt,'region':region,'valid_cells':v,'top1_cells':t,
                    'covered_valid_cells':cv,'covered_valid_percent':100*cv/v,'covered_top1_cells':ct,'covered_top1_percent':100*ct/t})
    pd.DataFrame(overlap).to_csv(run/'sampling_overlap.csv',index=False,mode='x')
    np.savez_compressed(run/'sampling_membership.npz',valid_flat_indices=flat,center_unit=center_unit,center_sector=center_sector,
        top1=top,**masks)
    write(run/'results.json',{'status':'DIAGNOSTICS_COMPLETE_AWAITING_OWNER_REVIEW','date_local':'2026-11-08',
        'specification_sha256':SPEC_HASH,'endpoint_cutoff':cutoff,
        'baseline_counts':dict(zip(['valid_ALL','top_ALL','valid_NW','top_NW'],observed)),
        'neighbourhood_primary_size_status':'UNRESOLVED; co-equal fixed nominal-75 m conventions, neither selected by overlap',
        'recommended_design':'Within-unit point-neighbourhood union, unique valid embedding centres, full 1 km units screened by A_250, equal unit weighting; exact neighbourhood convention requires review.',
        'recommended_sampling_sensitivity':'Occupied 250 m subregions, same A_250 unit set; 125/500 m and rule B all reported as fixed geometric stress checks.',
        'eligibility_overview':overview,'overlap':overlap,'motion_values_read':False,'motion_aggregates_computed':False,
        'motion_embedding_associations_computed':False,'new_2020_2022_raster_generated':False,'new_map_generated':False})
    for p,h in spec['registered_input_sha256'].items():assert sha(ROOT/p)==h,p
    assert sha(OUT/'diagnostic_specification.json')==SPEC_HASH
    event('All input/specification hashes unchanged; stopped for review without motion analysis')
    write(run/'output_audit.json',{'date_local':'2026-11-08','specification_sha256':SPEC_HASH,
        'input_hashes_unchanged':True,'runner_sha256':sha(Path(__file__)),
        'output_sha256':{p.name:sha(p) for p in run.iterdir() if p.is_file()}})
    print(pd.DataFrame(overview).to_string(index=False))
    print(pd.DataFrame(overlap).to_string(index=False))

if __name__=='__main__':main()
