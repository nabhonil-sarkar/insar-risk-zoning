"""Geometry-only Phase C inventory. Never loads motion or embedding magnitudes.

Audited eligibility is reconstructed using coordinate columns alone, conditional
on the pinned audit's zero identical duplicates and zero further quality exclusions.
The 1 km grid and 250 m occupancy diagnostics are inspection devices, not adopted
aggregation scales, support thresholds, measurement footprints or independent samples.
"""
from pathlib import Path
import hashlib, json, sys, platform
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from shapely.geometry import Polygon, box, mapping
from shapely.ops import transform
from pyproj import Transformer
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/output/phase_c_geometry_support_v1'
CRS='EPSG:32748'
ROI=(106.45,-6.54,107.22,-6.01)
SECTORS=['NW','N','NE','W','C','E','SW','S','SE']
REGISTERED={
 'data/raw/published_java_15786357/Java_VLM_EW.csv':'f82dd843df5a87a2db990416c9ea2a6a86c6cd77b6c1ba91ebf3f5be9f05cf65',
 'data/output/published_java_15786357/source_audit.json':'0a62c5d9d1d5bf95e783571023f0e7c2dd69a85d6ee56880470bbfa18f1c1f18',
 'data/output/published_java_15786357/mainland_counts.json':'994b4ca869e411527f5292e3d876f519e8ebf9df60031b7e15b34a8528040efa',
 'data/output/v9_qc/dki_kelurahan_official.geojson':'7bb4dd0589cec8bd64e8930c94b1835116701b6148f7b7de183e61196593c540',
 'data/output/alphaearth_surface_type_v1/protocol.json':'34f69075b89b76897ab5405d9d98f9cad14a81c68eef0fc53a5535028a06aaa0',
 'data/output/alphaearth_surface_type_v1/inventory.json':'cd1fe1b7ee30b523563522371684e3ca40a0a45d86a9a07c722951677566297f',
 'data/output/alphaearth_surface_type_v1/output_audit.json':'60ff5b177eae2b591733dc5b238cfcc09a783443b742693ef56555af6f09cf62',
 'data/output/alphaearth_surface_type_v1/run/support.csv':'ab0068d1e00807ce44ac99a27dac5652a0992705f6a87bc14944386279785232',
 'data/output/alphaearth_annual_change/gcs_full_v1/contract.json':'0fac38294b4b2e8ebd1ef2189df0898b4b79ef07ae7b8dcac21aa3e673829862',
 'data/output/alphaearth_annual_change/gcs_full_v1/cosine_change/manifest.json':'6f5a56846626ec2c058472ce4ee8707172c245da6642027f645591668fea3fbb',
 'docs/Nabhonil_Sarkar_Jakarta_Surface_Differences_2020-2025.pdf':'4ce2a0c85c99ab3780f2e994a4a5c917575244ba0af32ac7f1a039df11c8aa15',
 'docs/InSAR_Subsidence_Risk_Zoning_Methodology.docx':'cc457544d819dc45f3723d096dcb8c469b007fc5e0d011aac2e81fde2ae4875e'}
def sha(p):
    with p.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
def read(p): return json.loads((ROOT/p).read_text(encoding='utf-8'))
def write(name,data):
    with (OUT/name).open('x',encoding='utf-8') as f: json.dump(data,f,indent=2,allow_nan=False);f.write('\n')
def csv(name,frame): frame.to_csv(OUT/name,index=False,mode='x')
def densified_rect(bounds):
    x0,y0,x1,y1=bounds
    xs=np.linspace(x0,x1,max(2,int(np.ceil((x1-x0)/.002))+1))
    ys=np.linspace(y0,y1,max(2,int(np.ceil((y1-y0)/.002))+1))
    return Polygon([(x,y0) for x in xs]+[(x1,y) for y in ys[1:]]+[(x,y1) for x in xs[-2::-1]]+[(x0,y) for y in ys[-2:0:-1]])

def main():
    if OUT.exists(): raise FileExistsError(f'Exclusive output already exists: {OUT}')
    for p,h in REGISTERED.items():
        if sha(ROOT/p)!=h: raise ValueError(f'Registered hash mismatch: {p}')
    audit=read('data/output/published_java_15786357/source_audit.json')
    mainland=read('data/output/published_java_15786357/mainland_counts.json')
    assert audit['duplicate_rows_identical']==0
    assert audit['withheld_nonpositive_or_missing_sd_or_rate']==0
    assert tuple(audit['roi'])==ROI
    # Read only coordinates; the other four CSV columns are never materialized.
    chunks=[]
    for chunk in pd.read_csv(ROOT/'data/raw/published_java_15786357/Java_VLM_EW.csv',
            usecols=['Longitude','Latitude'],chunksize=200000,float_precision='round_trip'):
        chunks.append(chunk.loc[chunk.Longitude.between(ROI[0],ROI[2]) & chunk.Latitude.between(ROI[1],ROI[3])])
    coords=pd.concat(chunks,ignore_index=True)
    assert len(coords)==audit['roi_rows']==312374
    counts=coords.groupby(['Longitude','Latitude'],sort=True).size().rename('source_rows').reset_index()
    assert len(counts)==audit['unique_locations']==261286
    counts['eligibility']=np.where(counts.source_rows==1,'eligible_from_pinned_audit','withheld_conflicting_coordinate')
    assert int((counts.source_rows>1).sum())==audit['conflicting_locations']==40661
    eligible=counts.source_rows.eq(1).to_numpy()
    assert eligible.sum()==audit['eligible_unique_vertical_locations']==220625
    projector=Transformer.from_crs(4326,CRS,always_xy=True)
    inv=Transformer.from_crs(CRS,4326,always_xy=True)
    x,y=projector.transform(counts.Longitude.to_numpy(),counts.Latitude.to_numpy())
    counts['easting_m']=x;counts['northing_m']=y
    counts['grid_e']=np.floor(x/1000).astype(int);counts['grid_n']=np.floor(y/1000).astype(int)
    counts['cell_id']=['E%d_N%d'%(e,n) for e,n in zip(counts.grid_e,counts.grid_n)]
    protocol=read('data/output/alphaearth_surface_type_v1/protocol.json')
    grid=protocol['geometry']['grid'];a,_,c,_,e,f=grid['transform']
    width,height=grid['width'],grid['height']
    col_edges=np.r_[0,np.cumsum([len(i) for i in np.array_split(np.arange(width),3)])]
    row_edges=np.r_[0,np.cumsum([len(i) for i in np.array_split(np.arange(height),3)])]
    cols=np.floor((counts.Longitude.to_numpy()-c)/a).astype(int).clip(0,width-1)
    rows=np.floor((counts.Latitude.to_numpy()-f)/e).astype(int).clip(0,height-1)
    secindex=np.searchsorted(row_edges[1:-1],rows,side='right')*3+np.searchsorted(col_edges[1:-1],cols,side='right')
    counts['sector']=np.asarray(SECTORS)[secindex]
    roi=transform(projector.transform,densified_rect(ROI))
    sectors=[]
    for i,name in enumerate(SECTORS):
        rr,cc=divmod(i,3)
        bounds=(max(ROI[0],c+a*col_edges[cc]),max(ROI[1],f+e*row_edges[rr+1]),
                min(ROI[2],c+a*col_edges[cc+1]),min(ROI[3],f+e*row_edges[rr]))
        sectors.append(transform(projector.transform,densified_rect(bounds)))
    boundary=gpd.read_file(ROOT/'data/output/v9_qc/dki_kelurahan_official.geojson').to_crs(4326)
    boundary.geometry=shapely.make_valid(boundary.geometry.to_numpy())
    city_geoms={name:shapely.union_all(g.geometry.to_numpy()) for name,g in boundary.groupby('wadmkk')}
    membership=np.zeros(len(counts),int);city_labels=np.full(len(counts),'outside_available_mainland_DKI',dtype=object)
    city_results={}
    for name,geom in city_geoms.items():
        if name.startswith('JAKARTA '):
            inside=shapely.intersects_xy(geom,counts.Longitude,counts.Latitude)
            membership+=inside;city_labels[inside]=name
            city_results[name]=int((inside & eligible).sum())
    assert city_results==mainland['by_city']
    assert int(((membership>0)&eligible).sum())==48883
    assert not np.any(membership>1)
    counts['mainland_DKI']=membership>0;counts['municipality']=city_labels
    all_admin=shapely.union_all(list(city_geoms.values()))
    counts['in_available_boundary_dataset']=shapely.intersects_xy(all_admin,counts.Longitude,counts.Latitude)
    admin_proj=transform(projector.transform,all_admin)
    # Fixed zero-origin 1 km candidate cells; retain every positive ROI intersection.
    minx,miny,maxx,maxy=roi.bounds
    all_cells=[];polygons=[]
    for nn in range(int(np.floor(miny/1000)),int(np.floor(maxy/1000))+1):
        for ee in range(int(np.floor(minx/1000)),int(np.floor(maxx/1000))+1):
            whole=box(ee*1000,nn*1000,(ee+1)*1000,(nn+1)*1000)
            clip=whole.intersection(roi)
            if clip.area<=1e-8: continue
            polygons.append(clip)
            all_cells.append({'cell_id':f'E{ee}_N{nn}','grid_e':ee,'grid_n':nn,
                'roi_area_m2':clip.area,'roi_fraction':clip.area/1e6,
                'roi_cell_type':'full' if abs(clip.area-1e6)<=.01 else 'partial'})
    cells=pd.DataFrame(all_cells)
    assert np.isclose(cells.roi_area_m2.sum(),roi.area,rtol=1e-10)
    ep=counts.loc[eligible].copy(); wp=counts.loc[~eligible].copy()
    ep['sub_e']=np.floor(ep.easting_m/250).astype(int);ep['sub_n']=np.floor(ep.northing_m/250).astype(int)
    ep['sub_id']=ep.sub_e.astype(str)+'_'+ep.sub_n.astype(str)
    g=ep.groupby('cell_id')
    metrics=g.agg(eligible_points=('source_rows','size'),occupied_250m_subcells=('sub_id','nunique'),
        min_e=('easting_m','min'),max_e=('easting_m','max'),min_n=('northing_m','min'),max_n=('northing_m','max'))
    metrics['point_easting_span_m']=metrics.pop('max_e')-metrics.pop('min_e')
    metrics['point_northing_span_m']=metrics.pop('max_n')-metrics.pop('min_n')
    cells=cells.merge(metrics,on='cell_id',how='left').merge(wp.groupby('cell_id').size().rename('withheld_conflicting_points'),on='cell_id',how='left')
    for field in ['eligible_points','occupied_250m_subcells','withheld_conflicting_points']:cells[field]=cells[field].fillna(0).astype(int)
    cells['eligible_count_bin']=pd.cut(cells.eligible_points,[-1,0,4,9,24,49,np.inf],labels=['0','1–4','5–9','10–24','25–49','50+']).astype(str)
    available_sub=[]
    for rec in cells.itertuples():
        n=0
        for sn in range(4):
            for se in range(4):
                geom=box(rec.grid_e*1000+se*250,rec.grid_n*1000+sn*250,rec.grid_e*1000+(se+1)*250,rec.grid_n*1000+(sn+1)*250)
                n+=int(geom.intersection(roi).area>1e-8)
        available_sub.append(n)
    cells['roi_intersecting_250m_subcells']=available_sub
    cells['occupied_subcell_fraction']=cells.occupied_250m_subcells/cells.roi_intersecting_250m_subcells
    # Derive existing valid-centre geometry from the pinned support census: every
    # ROI centre is valid. No raster, embedding band, difference or motion value read.
    support=pd.read_csv(ROOT/'data/output/alphaearth_surface_type_v1/run/support.csv')
    assert support.missing_count.sum()==0 and support.unclassified_count.sum()==0
    manifest=read('data/output/alphaearth_annual_change/gcs_full_v1/cosine_change/manifest.json')
    assert manifest['inside_roi_centres']==5619719
    assert all(v['joint_valid']==5619719 for v in manifest['comparisons'])
    cx=c+a*(np.arange(width)+.5);cy=f+e*(np.arange(height)+.5)
    inside_x=(cx>=ROI[0])&(cx<=ROI[2]);inside_y=(cy>=ROI[1])&(cy<=ROI[3])
    assert int(inside_x.sum()*inside_y.sum())==5619719
    center_counts={};center_occupied_sub_counts={}
    occupied=set(zip(ep.sub_e,ep.sub_n))
    raster_sector_counts={s:0 for s in SECTORS}
    for r0 in range(0,height,128):
        rr=np.arange(r0,min(r0+128,height));rr=rr[inside_y[rr]]
        if not len(rr):continue
        cc=np.flatnonzero(inside_x)
        xx,yy=np.meshgrid(cx[cc],cy[rr]);gx,gy=projector.transform(xx.ravel(),yy.ravel())
        ge=np.floor(gx/1000).astype(int);gn=np.floor(gy/1000).astype(int)
        ids=np.stack([ge,gn],axis=1);u,n=np.unique(ids,axis=0,return_counts=True)
        for pair,count in zip(u,n):center_counts[tuple(pair)]=center_counts.get(tuple(pair),0)+int(count)
        sube=np.floor(gx/250).astype(int);subn=np.floor(gy/250).astype(int)
        mask=np.fromiter(((se,sn) in occupied for se,sn in zip(sube,subn)),dtype=bool,count=len(sube))
        u,n=np.unique(ids[mask],axis=0,return_counts=True)
        for pair,count in zip(u,n):center_occupied_sub_counts[tuple(pair)]=center_occupied_sub_counts.get(tuple(pair),0)+int(count)
        rs=np.repeat(np.searchsorted(row_edges[1:-1],rr,side='right'),len(cc))
        cs=np.tile(np.searchsorted(col_edges[1:-1],cc,side='right'),len(rr))
        for si,ct in enumerate(np.bincount(rs*3+cs,minlength=9)):raster_sector_counts[SECTORS[si]]+=int(ct)
    cells['embedding_valid_centres']=[center_counts.get((r.grid_e,r.grid_n),0) for r in cells.itertuples()]
    cells['embedding_centres_in_point_occupied_250m_subcells']=[center_occupied_sub_counts.get((r.grid_e,r.grid_n),0) for r in cells.itertuples()]
    assert cells.embedding_valid_centres.sum()==5619719
    assert cells.eligible_points.sum()==220625 and cells.withheld_conflicting_points.sum()==40661
    # Actual point-sector membership is exact; grid-sector intersections may overlap.
    summaries=[]
    for name,geom in [('ALL',roi)]+list(zip(SECTORS,sectors)):
        subset=ep if name=='ALL' else ep[ep.sector==name]
        withheld=wp if name=='ALL' else wp[wp.sector==name]
        ix=np.array([p.intersection(geom).area>1e-6 for p in polygons])
        ids=set(cells.loc[ix,'cell_id']);occ=set(subset.cell_id)
        assert occ<=ids
        subgroup=subset.groupby('cell_id').size()
        pcounts=np.array([subgroup.get(cid,0) for cid in cells.loc[ix,'cell_id']])
        geom_area=geom.area
        available_area=geom.intersection(admin_proj).area
        summaries.append({'sector':name,'eligible_points':len(subset),'withheld_conflicting_locations':len(withheld),
            'eligible_in_mainland_DKI':int(subset.mainland_DKI.sum()),
            'eligible_outside_mainland_DKI':int((~subset.mainland_DKI).sum()),
            'embedding_valid_centres':5619719 if name=='ALL' else raster_sector_counts[name],
            'intersecting_1km_cells':int(ix.sum()),'occupied_1km_cells':len(occ),'empty_1km_cells':int((pcounts==0).sum()),
            'cells_with_1_to_4_points':int(((pcounts>=1)&(pcounts<=4)).sum()),
            'cells_with_5_to_9_points':int(((pcounts>=5)&(pcounts<=9)).sum()),
            'median_points_all_intersecting_cells':float(np.median(pcounts)),
            'median_points_occupied_cells':float(np.median(pcounts[pcounts>0])) if len(occ) else None,
            'roi_geometry_area_km2':geom_area/1e6,'available_admin_geometry_area_km2':available_area/1e6,
            'available_admin_fraction_of_geometry':available_area/geom_area})
    summary=pd.DataFrame(summaries)
    assert summary.iloc[1:].eligible_points.sum()==220625
    assert summary.iloc[1:].embedding_valid_centres.sum()==5619719
    for name in SECTORS:
        saved=support[(support.sector==name)&(support.class_code!=0)]
        assert int(saved.joint_count.sum())==raster_sector_counts[name]
    OUT.mkdir(exist_ok=False)
    write('inventory_specification.json',{
        'date':'2026-11-07','scope':'Geometry and support inventory only; no Phase C association protocol adopted',
        'crs':CRS,'grid_size_m':1000,'grid_origin_easting_northing_m':[0,0],
        'grid_membership':'floor(projected easting/1000), floor(projected northing/1000); west/south included, east/north excluded. Closed geographic ROI first.',
        'roi_projection':'Geographic rectangle boundary densified at <=0.002 degree then projected. Areas are projected geometric area, not measured support area.',
        'partial_cells':'All positive-area ROI intersections retained; full if area differs from 1000000 m2 by <=0.01 m2 (numerical tolerance only).',
        'sectors':'Original raster np.array_split into 3 row and 3 column groups, north/west first. Pixel-edge geographic polygons clipped to ROI. Boundary points assigned east/south.',
        'sector_row_edges':row_edges.tolist(),'sector_column_edges':col_edges.tolist(),
        'sector_grid_counts':'Cells intersecting a sector; points counted using exact sector membership. Boundary cells can appear in two sectors; cell counts are not additive across sectors.',
        'count_bins':['0','1–4','5–9','10–24','25–49','50+'],'bins_are_acceptance_thresholds':False,
        'spread_diagnostics':'Within each candidate cell, easting/northing point spans and occupied zero-origin 250 m subcells (4x4). Empty spans are null. Subcell occupancy is geometric spread, not a footprint or measured-area fraction.',
        'support_matching_diagnostic':'Count existing valid embedding centres in 250 m subcells containing >=1 eligible point. Coarse co-location only; does not establish measured support at centres or representativeness.',
        'eligibility':'Use coordinates alone. Pinned audit certifies no identical duplicate rows and no additional nonpositive/missing SD/rate exclusions; all repeated coordinates withheld. Reconcile exact counts before use.',
        'embedding_support':'Derived from frozen grid centre clip and pinned all-ROI-valid support census for all seven comparisons; no raster pixels read.',
        'boundary_terms':'Existing local official DKI kelurahan dataset only. Redistribution terms not established in the local records reviewed; no new boundary search or download.',
        'prohibited_reads':'No motion, uncertainty or embedding-difference value columns loaded for computation; no raster data-band reads.',
        'registered_input_sha256':REGISTERED,'code_sha256':sha(Path(__file__)),
        'environment':{'python':sys.version,'platform':platform.platform(),'numpy':np.__version__,'pandas':pd.__version__,'shapely':shapely.__version__}})
    csv('sector_support.csv',summary)
    csv('grid_support_1km.csv',cells)
    csv('point_coordinate_eligibility.csv',counts)
    admin_rows=[]
    for name,geom in city_geoms.items():
        projected=transform(projector.transform,geom)
        inside=shapely.intersects_xy(geom,ep.Longitude,ep.Latitude)
        admin_rows.append({'municipality':name,'boundary_features':int((boundary.wadmkk==name).sum()),
            'eligible_points':int(inside.sum()),'roi_intersection_geometry_km2':projected.intersection(roi).area/1e6})
    csv('administrative_extent.csv',pd.DataFrame(admin_rows))
    geo=gpd.GeoDataFrame(cells,geometry=polygons,crs=CRS)
    geo.to_crs(4326).to_file(OUT/'candidate_grid.geojson',driver='GeoJSON')
    sector_geo=gpd.GeoDataFrame({'sector':SECTORS},geometry=sectors,crs=CRS)
    sector_geo.to_crs(4326).to_file(OUT/'study_sectors.geojson',driver='GeoJSON')
    write('results.json',{'status':'GEOMETRY_SUPPORT_INVENTORY_AWAITING_REVIEW',
        'roi_source_rows':312374,'distinct_coordinates':261286,'withheld_conflicting_locations':40661,'eligible_points':220625,
        'mainland_DKI_points':48883,'outside_mainland_DKI_points':171742,
        'boundary_features':len(boundary),'boundary_municipalities':list(city_geoms),
        'full_1km_cells':int((cells.roi_cell_type=='full').sum()),'partial_1km_cells':int((cells.roi_cell_type=='partial').sum()),
        'grid_count_bins':cells.eligible_count_bin.value_counts().to_dict(),
        'occupied_cells':int((cells.eligible_points>0).sum()),'empty_cells':int((cells.eligible_points==0).sum()),
        'occupied_full_cell_subcell_fraction_quantiles':cells.loc[(cells.roi_cell_type=='full')&(cells.eligible_points>0),'occupied_subcell_fraction'].quantile([0,.25,.5,.75,1]).to_dict(),
        'embedding_centres_in_empty_1km_cells':int(cells.loc[cells.eligible_points==0,'embedding_valid_centres'].sum()),
        'embedding_centres_in_point_occupied_250m_subcells':int(cells.embedding_centres_in_point_occupied_250m_subcells.sum()),
        'sector_support':summary.to_dict('records'),'no_deformation_aggregation':True,'no_association_or_overlay_analysis':True,
        'no_additional_grid_scales_evaluated':True,'no_optical_results_used_for_selection':True})
    # Two geometry-only panels; point marks have no physical footprint interpretation.
    fig,axes=plt.subplots(1,2,figsize=(15.8,7.5))
    palette=['#ffffff','#fff1b8','#f6cc78','#74b5b0','#387e96','#164c70']
    cats=['0','1–4','5–9','10–24','25–49','50+']
    for ax in axes:
        ax.set_aspect('equal');ax.set_xlim(minx-1000,maxx+1000);ax.set_ylim(miny-1000,maxy+1000)
        ax.set_xlabel('UTM easting (km)');ax.set_ylabel('UTM northing (km)')
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v,p:f'{v/1000:.0f}'))
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v,p:f'{v/1000:.0f}'))
        ax.tick_params(labelsize=9)
    geo.plot(ax=axes[0],facecolor='none',edgecolor='#d5d9dd',linewidth=.15)
    boundary.to_crs(CRS).boundary.plot(ax=axes[0],color='#b5a0b7',linewidth=.25)
    axes[0].scatter(ep.easting_m,ep.northing_m,s=.15,c='#156a79',alpha=.65,rasterized=True,zorder=3)
    geo.plot(ax=axes[1],color=[palette[cats.index(v)] for v in cells.eligible_count_bin],edgecolor='#bfc6cc',linewidth=.17)
    gpd.GeoSeries([admin_proj.intersection(roi)],crs=CRS).boundary.plot(ax=axes[1],color='#b24b61',linewidth=.9)
    for ax in axes:
        sector_geo.boundary.plot(ax=ax,color='#343b40',linewidth=.9)
        for name,geom in zip(SECTORS,sectors):
            cent=geom.centroid
            ax.text(cent.x,geom.bounds[3]-1700,name,ha='center',va='center',fontsize=11,fontweight='bold',
                    bbox={'facecolor':'white','alpha':.85,'edgecolor':'none','pad':1.5},zorder=5)
    axes[0].set_title('Eligible point locations and available DKI boundaries',fontsize=11)
    axes[1].set_title('Eligible point count per candidate 1 km cell',fontsize=11)
    axes[0].legend(handles=[Line2D([],[],color='#156a79',marker='.',linestyle='none',label='Eligible locations (symbol size is not footprint)'),
        Line2D([],[],color='#b5a0b7',label='Available kelurahan boundaries')],loc='lower left',fontsize=7.5)
    patches=[matplotlib.patches.Patch(facecolor=col,edgecolor='#999999',label=cat) for col,cat in zip(palette,cats)]
    axes[1].legend(handles=patches,title='Points per cell · display bins only',ncol=3,loc='lower left',fontsize=8,title_fontsize=8)
    fig.suptitle('Jakarta Phase C geometry and observation support inventory',fontsize=17,y=.97)
    fig.text(.5,.064,'Study sectors retain the original raster divisions. Red outline: extent of the available DKI polygons within the ROI.',ha='center',fontsize=9)
    fig.text(.5,.038,'Counts and occupied cells are not measured area coverage. No motion values, embedding differences or optical outcomes are mapped.',ha='center',fontsize=9)
    fig.text(.5,.012,'EPSG:32748 · 1 km grid anchored at (0, 0) m · partial ROI cells retained · source: audited Java 2017–2023 coordinates',ha='center',fontsize=8,color='#444444')
    fig.subplots_adjust(left=.065,right=.99,top=.89,bottom=.16,wspace=.16)
    fig.savefig(OUT/'geometry_support.png',dpi=180)
    fig.savefig(OUT/'geometry_support.pdf')
    plt.close(fig)
    write('output_audit.json',{'date':'2026-11-07','code_sha256':sha(Path(__file__)),
        'registered_inputs_verified':len(REGISTERED),'counts_reconciled':True,'grid_partition_area_reconciled':True,
        'sector_and_existing_support_census_reconciled':True,'source_columns_loaded':['Longitude','Latitude'],
        'raster_pixel_reads':0,'acquisition_requests':0,'test_suite_run':False,
        'output_sha256':{p.name:sha(p) for p in OUT.iterdir() if p.is_file()}})
    print(summary.to_string(index=False))
    print(json.dumps(read(OUT.relative_to(ROOT)/'results.json'),indent=2))

if __name__=='__main__':main()
