"""Bounded native-footprint geometry for building-label v2; no enrichment."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import urllib.request
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.transform import Affine
from pyproj import Transformer, Proj
from shapely.geometry import shape, box, Polygon, GeometryCollection
from shapely.ops import unary_union
from scripts.building_change_explore.analyse import OUT as BASE, labels

OUT=BASE/'v2'
TO_UTM=Transformer.from_crs(4326,32748,always_xy=True)
TO_LL=Transformer.from_crs(32748,4326,always_xy=True)


def now():return datetime.now(timezone.utc).isoformat()
def read(name):return json.loads((OUT/name).read_text())
def write(name,obj):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(obj,f,indent=2,allow_nan=False)
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def initialize_record():
    OUT.mkdir(exist_ok=False)
    prior=json.loads((BASE/'resource_accounting.json').read_text())
    write('resource_accounting.json',dict(started_utc=now(),carry_in_charged_bytes=prior['charged_download_bytes_total'],carry_in_measured_bytes=prior['measured_downloaded_payload_bytes_total'],carry_in_active_minutes=prior['active_effort_minutes_charged'],cap_bytes=prior['cap_bytes'],new_metadata_allowance_bytes=10_000_000,new_browser_allowance_bytes=0,note='Cumulative continuation; Day 1 ledger preserved. New metadata allowance is an estimate, not exact traffic.'))
    protected={str(p.relative_to(BASE)):sha(p) for p in BASE.rglob('*') if p.is_file() and OUT not in p.parents}
    write('day1_preservation.json',protected)
    old=json.loads((BASE/'reference_sample.json').read_text())
    write('settlement_sites.json',[s for s in old if s['stratum']=='addition'])
    write('scope.json',dict(recorded_utc=now(),radius_m=8,thresholds=[.41,.34],geometry='Threshold at native 0.5 m grid; polygonize positive pixel footprints, buffer ONLY 2020 by 8 local ground metres; subtract from 2023 before exact intersection with frozen cell polygon. EPSG32748 buffer radius is multiplied by local projection scale. Circular arcs use 64 segments per quadrant (<0.001 m radial approximation).',patch='256 m square native binary/support patch, 512x512 cells; no full source raster or confidence raster. Far more than 8 m halo around target cell. Outside patch and missing baseline expanded by same radius are unknown.',proposed_rule='Retain original endpoint low2020<=0.10/high2023>=0.40 and support>=0.95. Require surviving footprint >=0.10 of valid comparison area, paired neighbourhood support>=0.95. This is a new additional growth floor, not old 0.40 applied to growth. Settle only on six previously inspected addition sites before fresh evaluation.',limits='One radius, original grid; no enrichment, classifiers, coarsening, threshold rescue, publication or accepted artifact edits.'))


def target_polygon(sample):
    t=Affine(*json.loads((BASE/'input_verification.json').read_text())['grid']['transform'])
    r,c=sample['row'],sample['col']
    return Polygon([TO_UTM.transform(*(t*p)) for p in [(c,r),(c+1,r),(c+1,r+1),(c,r+1)]])


def polygons(mask,transform):
    parts=[shape(g) for g,v in shapes(mask.astype('uint8'),mask=mask.astype(bool),transform=transform) if v]
    return unary_union(parts) if parts else GeometryCollection()


def compare_geometry(baseline,endpoint,valid0,valid3,domain,cell,radius=8):
    # The baseline is deliberately NOT clipped to the target before expansion.
    unknown=domain.difference(valid0).buffer(radius,quad_segs=64)
    known=domain.buffer(-radius).intersection(valid3).difference(unknown).intersection(cell)
    expanded=baseline.buffer(radius,quad_segs=64)
    surviving=endpoint.difference(expanded).intersection(known)
    denominator=known.area
    return dict(cell_area_m2=cell.area,comparison_area_m2=denominator,
                comparison_support_fraction=denominator/cell.area,
                surviving_area_m2=surviving.area,
                surviving_fraction=surviving.area/denominator if denominator else None),surviving,expanded,known


def export_sites(manifest):
    sys.path.insert(0,str(BASE/'ee_runtime'));import ee
    project=json.loads((BASE/'reference_provenance.json').read_text())['project_access']['id']
    ee.Initialize(project=project);ee.data.setDeadline(180000)
    images=[]
    for year in [2020,2023]:
        p=ee.Image(f'GOOGLE/Research/open-buildings-temporal/v1/2f_EPSG_32748_{year}_06_30').select('building_presence')
        good=p.mask().gt(0).And(p.gte(0)).And(p.lte(1));p=p.updateMask(good)
        images.append(ee.Image.cat([p.gte(.41).unmask(0,False),p.gte(.34).unmask(0,False),good.unmask(0,False)]).toByte().setDefaultProjection(p.projection()).rename([f'p041_{year}',f'p034_{year}',f'valid_{year}']))
    image=ee.Image.cat(images)
    folder=OUT/'native_binary';folder.mkdir(exist_ok=True)
    sites=read(manifest)
    ledger=read('resource_accounting.json')
    used=sum(json.loads(p.read_text()).get('body_bytes',0) for p in folder.glob('*.json'))
    assert ledger['carry_in_charged_bytes']+ledger['new_metadata_allowance_bytes']+used+len(sites)*2_000_000<ledger['cap_bytes']
    def export(s):
        path=folder/(s['id']+'.tif');record=path.with_suffix('.json')
        if record.exists():
            old=json.loads(record.read_text());assert old['complete'] and sha(path)==old['sha256'];return old
        t=Affine(.5,0,math.floor((s['x']-128)*2)/2,0,-.5,math.ceil((s['y']+128)*2)/2)
        rec=dict(id=s['id'],started_utc=now(),body_bytes=0,complete=False,transform=list(t)[:6])
        try:
            url=image.getDownloadURL(dict(crs='EPSG:32748',crs_transform=list(t)[:6],dimensions=[512,512],format='GEO_TIFF',filePerBand=False))
            with urllib.request.urlopen(url,timeout=190) as response,path.open('xb') as stream:
                while True:
                    chunk=response.read(65536)
                    if not chunk:break
                    rec['body_bytes']+=len(chunk)
                    if rec['body_bytes']>2_000_000:raise RuntimeError('Patch bound exceeded')
                    stream.write(chunk)
            with rasterio.open(path) as ds:
                a=ds.read();assert ds.transform==t and ds.shape==(512,512) and ds.count==6 and str(ds.crs)=='EPSG:32748'
            assert set(np.unique(a))<={0,1}
            rec.update(complete=True,sha256=sha(path))
        except Exception as exc:rec['error']=str(exc)
        record.write_text(json.dumps(rec,indent=2)+'\n')
        print(json.dumps(rec),flush=True);return rec
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(export,sites))
    assert all(r['complete'] for r in results)


def measure(s):
    with rasterio.open(OUT/'native_binary'/(s['id']+'.tif')) as ds:a=ds.read().reshape(2,3,512,512);t=ds.transform;bounds=ds.bounds
    cell=target_polygon(s);domain=box(*bounds)
    lon,lat=TO_LL.transform(s['x'],s['y']);f=Proj('EPSG:32748').get_factors(lon,lat)
    scale=math.sqrt(f.meridional_scale*f.parallel_scale);radius=8*scale
    assert domain.contains(cell.buffer(radius+1))
    valid0=polygons(a[0,2],t);valid3=polygons(a[1,2],t)
    rows=[]
    for ti,threshold in enumerate([.41,.34]):
        b=polygons(a[0,ti],t);e=polygons(a[1,ti],t)
        result,growth,expanded,known=compare_geometry(b,e,valid0,valid3,domain,cell,radius)
        coverage=s['coverage_041'] if ti==0 else s['coverage_034']
        endpoints=coverage[0]<=.1 and coverage[3]>=.4 and min(s['support'][0],s['support'][3])>=.95
        supported=result['comparison_support_fraction']>=.95
        alarm=supported and result['surviving_fraction']>=.10
        rows.append(dict(id=s['id'],sector=s['sector'],stratum=s['stratum'],block=s['block'],threshold=threshold,**result,
                         ground_surviving_area_m2=result['surviving_area_m2']/scale**2,projection_scale=scale,
                         endpoint_low_high=bool(endpoints),growth_alarm=bool(alarm) if supported else None,
                         v2_candidate=bool(endpoints and alarm) if supported else None,
                         status='supported' if supported else 'unknown_neighbourhood_support',
                         outside_cell_buffer_effect_m2=expanded.intersection(cell).area-b.intersection(cell).buffer(radius,quad_segs=64).intersection(cell).area))
    return rows


def measure_sites(manifest,destination):
    rows=[]
    for s in read(manifest):rows.extend(measure(s))
    write(destination,rows)
    print(json.dumps(rows,indent=2))


def select_fresh():
    assert (OUT/'evaluation_settings.json').exists()
    local=np.load(BASE/'local_arrays.npz');ref=np.load(BASE/'reference_fractions.npy');cv,v,lo,hi,amb=labels(ref)
    old=json.loads((BASE/'reference_sample.json').read_text());used={tuple(s['block']) for s in old};sites=[]
    from scipy.ndimage import minimum_filter
    edge=hi.all(axis=0)&(cv[0]<.85)&(minimum_filter(cv[0],size=3)<.1)
    masks=[('addition',lo[0]&hi[3],5),('stable_built_edge',edge,3),('stable_built_interior',hi.all(axis=0)&(cv[0]>=.85),2),('stable_nonbuilt',lo.all(axis=0),5)]
    for sid,sector in [(0,'NW'),(3,'W')]:
        for stratum,mask,count in masks:
            take=local['inside']&(local['sectors']==sid)&(local['split']==1)&local['buffer_retained']&mask
            blocks=np.unique(np.column_stack([local['block_x'][take],local['block_y'][take]]),axis=0)
            ordered=sorted(blocks.tolist(),key=lambda b:hashlib.sha256(f'v2_fresh:{sector}:{stratum}:{b[0]}:{b[1]}'.encode()).hexdigest())
            selected=0
            for block in ordered:
                if tuple(block) in used:continue
                rr,cc=np.where(take&(local['block_x']==block[0])&(local['block_y']==block[1]))
                order=np.argsort((local['x'][rr,cc]-(block[0]+.5)*1000)**2+(local['y'][rr,cc]-(block[1]+.5)*1000)**2,kind='stable')
                for k in order:
                    r,c=int(rr[k]),int(cc[k]);x,y=float(local['x'][r,c]),float(local['y'][r,c])
                    if all((x-z['x'])**2+(y-z['y'])**2>=1000**2 for z in old+sites):break
                else:continue
                selected+=1;used.add(tuple(block));lon,lat=TO_LL.transform(x,y)
                sites.append(dict(id=f'v2_{sector}_{stratum}_{selected}',sector=sector,stratum=stratum,block=block,row=r,col=c,x=x,y=y,longitude=lon,latitude=lat,coverage_041=cv[:,r,c].tolist(),coverage_034=labels(ref,1)[0][:,r,c].tolist(),support=ref[:,2,r,c].tolist(),split='development'))
                if selected==count:break
            assert selected==count,(sector,stratum,selected)
    write('fresh_sites.json',sites);print(json.dumps(sites,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['init','export','measure','select']);p.add_argument('--manifest');p.add_argument('--output');args=p.parse_args()
    if args.action=='init':initialize_record()
    elif args.action=='export':export_sites(args.manifest)
    elif args.action=='measure':measure_sites(args.manifest,args.output)
    else:select_fresh()
