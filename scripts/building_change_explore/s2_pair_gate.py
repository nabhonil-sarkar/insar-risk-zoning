"""One bounded Sentinel-2 interpretability screen; never infer change labels.

Requires the excluded, pinned exploration bundle and optional Earth Engine API.
The historical run's settings and outputs are write-once. Review uses anonymous
cards without scores, baseline class, sector or extreme/control membership.
The completed attempt stopped at sampling: remote screening, acquisition and
rendering below are unexecuted preparation, not demonstrated imagery feasibility.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import Affine

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'data/output/building_change_explore_v1'
OUT = BASE / 's2_pair_gate'
CRS = 'EPSG:32748'
PROJ = [10, 0, 0, 0, -10, 10000000]
TO_UTM = Transformer.from_crs(4326, 32748, always_xy=True)
TO_LL = Transformer.from_crs(32748, 4326, always_xy=True)
GROUPS = ['extreme_land', 'extreme_water', 'control_land', 'control_water']


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def check_time():
    settings = read(OUT / 'settings.json')
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(settings['started_utc'])).total_seconds()
    if elapsed >= 7200:
        raise TimeoutError('Scientific two-hour limit reached; no further acquisition/review')
    return elapsed


def eligible_scene(scene):
    return (scene['valid'] >= .98 and scene['edge_safe'] >= .98
            and scene['clear'] >= .90 and scene['target_clear'] >= .95)


def pair_order(scenes):
    """Fix one same-tile/orbit, seasonal pair; no visual-driven alternatives."""
    pairs = []
    for a in scenes:
        if a['year'] != 2020 or not eligible_scene(a):
            continue
        for b in scenes:
            if b['year'] != 2023 or not eligible_scene(b):
                continue
            # Compare on a non-leap calendar; actual acquisition times retained.
            da = datetime.fromisoformat(a['date'][:10]).replace(year=2001)
            db = datetime.fromisoformat(b['date'][:10]).replace(year=2001)
            delta = abs((da - db).days)
            if delta > 30 or a['tile'] != b['tile'] or a['orbit'] != b['orbit']:
                continue
            rank = (-min(a['clear'], b['clear']), -(a['clear']+b['clear']),
                    delta, abs((da-datetime(2001,8,1)).days)+abs((db-datetime(2001,8,1)).days),
                    a['id'], b['id'])
            pairs.append((rank, a, b))
    return sorted(pairs, key=lambda z: z[0])


def gate_counts(sites, reviews):
    by_id = {r['id']: r for r in reviews}
    rows = []
    for group in GROUPS:
        subset = [s for s in sites if s['group'] == group]
        row = dict(group=group, sites=len(subset), blocks=len({tuple(s['block']) for s in subset}))
        for sector in ['NW', 'W']:
            selected = [s for s in subset if s['sector'] == sector]
            row[sector] = sum(by_id.get(s['id'], {}).get('interpretable') is True for s in selected)
        row['interpretable'] = row['NW'] + row['W']
        row['unassessable'] = len(subset)-row['interpretable']
        row['pass'] = len(subset) == 10 and row['interpretable'] >= 7
        rows.append(row)
    return rows, all(r['pass'] for r in rows)


def allocation_inventory(a):
    """Count the fixed populations before any optional exclusion or image read."""
    rows=[]
    for sector,sid in [('NW',0),('W',3)]:
        for group in GROUPS:
            hot=a['hot_2023_1'] if group.startswith('extreme') else ~a['hot_2023_1']
            surface=a['cover']==80 if group.endswith('water') else a['cover']!=80
            population=a['inside']&(a['sectors']==sid)&hot&surface
            row=dict(sector=sector,group=group,required_sites=5)
            for stage,restriction in [('population',np.ones(population.shape,bool)),
                                      ('development',a['split']==1),
                                      ('buffered_development',(a['split']==1)&a['buffer_retained'])]:
                mask=population&restriction
                row[stage+'_cells']=int(mask.sum())
                row[stage+'_blocks']=len(np.unique(np.column_stack([a['block_x'][mask],a['block_y'][mask]]),axis=0))
            rows.append(row)
    return rows


def initialize():
    OUT.mkdir(exist_ok=False)
    for name in ['inventory', 'pairs', 'cards']:
        (OUT/name).mkdir()
    prior = read(BASE/'v2/resource_accounting.json')
    settings = dict(recorded_utc=now(), started_utc='2026-11-10T16:22:00+00:00',
        local_authorization_date='2026-11-11', scientific_cap_seconds=7200,
        carry_in_charged_bytes=prior['cumulative_charged_bytes'],
        carry_in_measured_bytes=prior['cumulative_measured_payload_bytes'],
        carry_in_active_minutes=prior['cumulative_active_minutes_charged'],
        cap_bytes=1000000000, metadata_documentation_allowance_bytes=20000000,
        selection='Five per sector per group; original rectangle-wide hot_2023_1; all other valid cells controls. Hash-order 1 km blocks using s2_pair_v1:sector:group:bx:by; closest eligible cell to block centre, row/col tie. Distinct blocks globally; non-overlapping 500 m footprints. Fixed development split=1 and original 250 m buffer, tightened to 300 m for full footprint. Exclude prior building inspection blocks and overlapping prior benchmark/coastal inspection footprints. No scores used beyond fixed membership. No replacement sites.',
        footprint='500 x 500 m on the UTM 10 m grid, nearest 10 m centre to sampled cell; 50x50 pixels. Red outline is exact original target cell projected from frozen grid; it is not the 500 m interpretation footprint.',
        broad_features='Resolve contiguous water, vegetation/open land and large impervious/roof/road patterns approximately >=30 m across. Individual buildings, narrow shorelines and target-cell mixtures need not be resolvable; if they prevent locating/interpreting the target, fail. No transformation, no-change or water-transition labels.',
        collections=['COPERNICUS/S2_SR_HARMONIZED', 'COPERNICUS/S2_CLOUD_PROBABILITY'],
        dates='2020 and 2023, June 1 through September 30 inclusive; same MGRS tile and relative orbit; month/day difference <=30 days. Actual scene sensing times retained.',
        quality='Full 500 m footprint: valid RGB/NIR, B8A/B9, SCL and cloud probability >=98%; valid coverage eroded 60 m >=98%; clear >=90%. Target cell clear >=95%. Cloud probability >=40 OR SCL 8/9/10 is cloud-risk; SCL 0/1/3/11 invalid/shadow/snow; projected cloud-shadow risk within 1000 m along 90-solar_azimuth, intersect NIR<0.15 and SCL!=6, plus SCL3. Dilate combined quality risk 40 m. No QA60 dependency. All masks nearest-neighbour; RGB native 10 m; SCL 20 m/B9 60 m limits disclosed.',
        bright_surface_handling='Cloud probability can flag bright roofs/sand. Excluded quality pixels are not counted as proven clouds; inspect unmasked RGB alongside quality mask. Do not override masks or rescue a failed scene.',
        deterministic_pair='Eligible pairs ranked by highest worse-endpoint clear fraction, highest summed clear fraction, lowest month/day difference, closest summed distance to August 1, then scene IDs. Select one pair only. Zero alternative-scene allowance. Inventory all sites before pixel acquisition.',
        review='Anonymous shuffled cards show RGB both years with identical fixed 0..0.30 reflectance stretch and gamma 1/1.4, plus quality overlays, dates and target outline. No score, membership, baseline class, sector or coordinates. Pass only if both images support broad surface interpretation, target is localizable, no consequential residual cloud/shadow/haze/saturation, and identifiable common boundaries align within one 10 m pixel. Featureless windows without an alignment anchor and consequential target mixtures fail as unclear. No alteration after viewing.',
        gate='At least 7/10 interpretable in EACH of four groups. Missing scene/pair, acquisition failures, quality failures and unclear review remain in denominator. Report sector subtotals and block counts. Interpretability is not independent change accuracy or cause.',
        sources=['https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED','https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_CLOUD_PROBABILITY','https://developers.google.com/earth-engine/tutorials/community/sentinel-2-s2cloudless'])
    save(OUT/'settings.json', settings)
    # Snapshot existing evidence only; no history or accepted document is changed.
    preserved = {str(p.relative_to(ROOT)):sha(p) for p in BASE.rglob('*')
                 if p.is_file() and OUT not in p.parents}
    for name, expected in read(BASE/'protected_artifacts.json')['sha256'].items():
        assert sha(ROOT/name) == expected
        preserved[name] = expected
    save(OUT/'preserved_sha256.json', preserved)
    with np.load(BASE/'local_arrays.npz') as source:
        a = {name: source[name] for name in source.files}
    allocation=allocation_inventory(a)
    save(OUT/'allocation_inventory.json',allocation)
    if any(r['buffered_development_blocks']<5 for r in allocation):
        save(OUT/'sampling_stop.json',dict(decision='STOP_INCONCLUSIVE_SAMPLING',recorded_utc=now(),
             reason='Required fixed sector/group quota unavailable in development allocation',
             sample_completed=False,imagery_acquired=False,allocation=allocation))
        raise RuntimeError('Fixed development allocation cannot supply all required site quotas')
    old = read(BASE/'reference_sample.json') + read(BASE/'v2/fresh_sites.json')
    old_blocks = {tuple(s['block']) for s in old}
    exclusions = []
    for s in read(ROOT/'data/output/urban_benchmark_v1/assignment.json')['sites']:
        x,y = TO_UTM.transform(s['lon'],s['lat'])
        exclusions.append((x,y,310))  # Prior 90 m window plus new 250 m half-footprint.
    for name in ['coastal_transition_pilot_v1','coastal_jun_sep_v1']:
        for s in read(ROOT/f'data/output/{name}/protocol.json')['geometry']['windows']:
            exclusions.append((*s['centre_utm'],920))  # Prior 660 m read half-width + new 250 m.
    eligible = a['inside'] & (a['split']==1) & a['buffer_retained']
    eligible &= (a['x']%5000>=300)&(a['x']%5000<=4700)&(a['y']%5000>=300)&(a['y']%5000<=4700)
    for x,y,d in exclusions:
        eligible &= (np.abs(a['x']-x)>=d)|(np.abs(a['y']-y)>=d)
    chosen=[]; used=set(old_blocks)
    for sector,sid in [('NW',0),('W',3)]:
        for group in GROUPS:
            hot = a['hot_2023_1'] if group.startswith('extreme') else ~a['hot_2023_1']
            surface = a['cover']==80 if group.endswith('water') else a['cover']!=80
            mask = eligible & (a['sectors']==sid) & hot & surface
            blocks=np.unique(np.column_stack([a['block_x'][mask],a['block_y'][mask]]),axis=0)
            ordered=sorted(blocks.tolist(),key=lambda b:hashlib.sha256(f's2_pair_v1:{sector}:{group}:{b[0]}:{b[1]}'.encode()).hexdigest())
            count=0
            for b in ordered:
                if tuple(b) in used: continue
                rr,cc=np.where(mask&(a['block_x']==b[0])&(a['block_y']==b[1]))
                dist=(a['x'][rr,cc]-(b[0]+.5)*1000)**2+(a['y'][rr,cc]-(b[1]+.5)*1000)**2
                for k in np.argsort(dist,kind='stable'):
                    r,c=int(rr[k]),int(cc[k]);x=float(a['x'][r,c]);y=float(a['y'][r,c])
                    cx,cy=round(x/10)*10,round(y/10)*10
                    if any(abs(cx-s['cx'])<500 and abs(cy-s['cy'])<500 for s in chosen):continue
                    chosen.append(dict(sector=sector,group=group,row=r,col=c,block=b,x=x,y=y,cx=cx,cy=cy))
                    used.add(tuple(b));count+=1;break
                if count==5:break
            if count!=5:
                save(OUT/'sampling_stop.json',dict(decision='STOP_INCONCLUSIVE_SAMPLING',recorded_utc=now(),
                     reason=f'Cannot fill fixed quota after exclusions: {sector} {group} {count}/5',
                     sample_completed=False,imagery_acquired=False))
                raise RuntimeError(f'Cannot fill fixed quota: {sector} {group} {count}/5')
    chosen.sort(key=lambda s:hashlib.sha256(f"blind_s2_pair_v1:{s['row']}:{s['col']}".encode()).hexdigest())
    t=Affine(*read(BASE/'input_verification.json')['grid']['transform'])
    for i,s in enumerate(chosen,1):
        s['id']=f'P{i:02d}'
        s['target_utm']=[TO_UTM.transform(*(t*p)) for p in [(s['col'],s['row']),(s['col']+1,s['row']),(s['col']+1,s['row']+1),(s['col'],s['row']+1)]]
    save(OUT/'sample_key.json',chosen)
    save(OUT/'blind_sites.json',[{k:v for k,v in s.items() if k not in ['group','sector','block','row','col','x','y']} for s in chosen])
    save(OUT/'selection_audit.json',dict(recorded_utc=now(),sites=len(chosen),distinct_blocks=len(chosen),prior_building_blocks_excluded=len(old_blocks),prior_benchmark_coastal_windows_excluded=len(exclusions),local_arrays_sha256=sha(BASE/'local_arrays.npz'),all_development=True,all_buffered=True,settings_sha256=sha(OUT/'settings.json')))
    print('Frozen 40 sites in 40 blocks; group key saved separately from blind review.')


def connect():
    # The optional API may be in the historical isolated runtime, or installed.
    runtime=BASE/'ee_runtime'
    if runtime.exists():sys.path.insert(0,str(runtime))
    import ee
    project=read(BASE/'reference_provenance.json')['project_access']['id']
    ee.Initialize(project=project)
    ee.data.setDeadline(90000)
    return ee


def quality(ee, image, probability):
    cp=probability.select('probability')
    scl=image.select('SCL')
    valid=image.select(['B2','B3','B4','B8','B8A','B9','SCL']).mask().reduce(ee.Reducer.min()).And(cp.mask()).And(scl.neq(0)).And(scl.neq(1)).unmask(0,False)
    valid=valid.reproject(CRS,PROJ)
    safe=valid.focalMin(radius=60,units='meters',kernelType='circle')
    cloud=cp.gte(40).Or(scl.eq(8)).Or(scl.eq(9)).Or(scl.eq(10)).unmask(0,False).reproject(CRS,PROJ)
    angle=ee.Number(90).subtract(image.get('MEAN_SOLAR_AZIMUTH_ANGLE'))
    projected=cloud.directionalDistanceTransform(angle,100).select('distance').mask()
    dark=image.select('B8').lt(1500).And(scl.neq(6)).unmask(0,False)
    shadow=projected.And(dark).Or(scl.eq(3))
    risk=cloud.Or(shadow).Or(scl.eq(11)).unmask(1,False).focalMax(radius=40,units='meters',kernelType='circle')
    clear=valid.And(safe).And(risk.Not()).unmask(0,False)
    return ee.Image.cat([valid.rename('valid'),safe.rename('edge_safe'),clear.rename('clear')]).toByte()


def bounds(ee,s):
    return ee.Geometry.Rectangle([s['cx']-250,s['cy']-250,s['cx']+250,s['cy']+250],CRS,False)


def inventory():
    check_time()
    if (OUT/'sampling_stop.json').exists():raise RuntimeError('Sampling stopped; no image inventory authorized')
    sites=read(OUT/'blind_sites.json');ee=connect()
    def one(s):
        check_time();path=OUT/'inventory'/f"{s['id']}.json"
        if path.exists():return read(path)
        footprint=bounds(ee,s);target=ee.Geometry.Polygon([s['target_utm']],CRS,False)
        result=dict(id=s['id'],started_utc=now(),scenes=[],complete=False)
        try:
            for year in [2020,2023]:
                check_time()
                sr=ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(footprint).filterDate(f'{year}-06-01',f'{year}-10-01')
                cp=ee.ImageCollection('COPERNICUS/S2_CLOUD_PROBABILITY').filterBounds(footprint).filterDate(f'{year}-06-01',f'{year}-10-01')
                joined=ee.ImageCollection(ee.Join.saveFirst('cloud_probability').apply(sr,cp,ee.Filter.equals(leftField='system:index',rightField='system:index'))).filter(ee.Filter.notNull(['cloud_probability']))
                def summarize(im):
                    im=ee.Image(im);q=quality(ee,im,ee.Image(im.get('cloud_probability')))
                    stats=q.reduceRegion(ee.Reducer.mean(),footprint,crs=CRS,crsTransform=PROJ,maxPixels=20000)
                    target_clear=q.select('clear').reduceRegion(ee.Reducer.mean(),target,crs=CRS,crsTransform=PROJ,maxPixels=1000).get('clear')
                    return ee.Feature(None,stats).set(dict(id=im.get('system:index'),year=year,date=ee.Date(im.get('system:time_start')).format("YYYY-MM-dd'T'HH:mm:ss"),tile=im.get('MGRS_TILE'),orbit=im.get('SENSING_ORBIT_NUMBER'),target_clear=target_clear))
                features=ee.FeatureCollection(joined.toList(joined.size()).map(summarize)).getInfo()
                rows=[f['properties'] for f in features['features']]
                result['scenes'].extend(rows)
            pairs=pair_order(result['scenes'])
            result.update(complete=True,eligible_2020=sum(z['year']==2020 and eligible_scene(z) for z in result['scenes']),eligible_2023=sum(z['year']==2023 and eligible_scene(z) for z in result['scenes']),eligible_pairs=len(pairs),selected=[pairs[0][1],pairs[0][2]] if pairs else [])
        except Exception as exc:result['error']=str(exc)
        result['finished_utc']=now();save(path,result)
        print(json.dumps({k:result.get(k) for k in ['id','complete','eligible_2020','eligible_2023','eligible_pairs','error']}),flush=True)
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(one,sites))
    save(OUT/'inventory_complete.json',dict(completed_utc=now(),sites=len(results),with_candidate_pair=sum(bool(r.get('selected')) for r in results),errors=sum(not r['complete'] for r in results)))


def acquire():
    check_time();assert (OUT/'inventory_complete.json').exists()
    ee=connect();settings=read(OUT/'settings.json');sites=read(OUT/'blind_sites.json')
    # Maximum 80 tiny patches, at most 200 kB per request, budgeted before calls.
    assert settings['carry_in_charged_bytes']+settings['metadata_documentation_allowance_bytes']+80*200000<settings['cap_bytes']
    def one(s):
        check_time();record=OUT/'pairs'/f"{s['id']}.json"
        if record.exists():return read(record)
        inv=read(OUT/'inventory'/f"{s['id']}.json")
        result=dict(id=s['id'],started_utc=now(),downloads=[],complete=False)
        if not inv.get('selected'):
            result.update(reason='no_eligible_pair' if inv['complete'] else 'inventory_error')
            save(record,result);return result
        try:
            for scene in inv['selected']:
                check_time();im=ee.Image('COPERNICUS/S2_SR_HARMONIZED/'+scene['id']);cp=ee.Image('COPERNICUS/S2_CLOUD_PROBABILITY/'+scene['id'])
                export=ee.Image.cat([im.select(['B4','B3','B2']),quality(ee,im,cp),im.select('SCL'),cp.select('probability')]).unmask(0,False).toUint16()
                t=[10,0,s['cx']-250,0,-10,s['cy']+250]
                path=OUT/'pairs'/f"{s['id']}_{scene['year']}.tif"
                d=dict(year=scene['year'],scene=scene,body_bytes=0,complete=False)
                result['downloads'].append(d)
                url=export.getDownloadURL(dict(crs=CRS,crs_transform=t,dimensions=[50,50],format='GEO_TIFF',filePerBand=False))
                with urllib.request.urlopen(url,timeout=95) as response,path.open('xb') as f:
                    while True:
                        chunk=response.read(65536)
                        if not chunk:break
                        d['body_bytes']+=len(chunk)
                        if d['body_bytes']>200000:raise RuntimeError('Patch exceeded fixed byte allowance')
                        f.write(chunk)
                with rasterio.open(path) as ds:
                    assert ds.count==8 and ds.shape==(50,50) and ds.transform==Affine(*t) and str(ds.crs)==CRS
                d.update(complete=True,sha256=sha(path))
            result['complete']=True
        except Exception as exc:result['error']=str(exc)
        result['finished_utc']=now();save(record,result)
        print(json.dumps(dict(id=s['id'],complete=result['complete'],error=result.get('error'))),flush=True)
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(one,sites))


def render():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    for s in read(OUT/'blind_sites.json'):
        r=read(OUT/'pairs'/f"{s['id']}.json")
        if not r['complete']:continue
        fig,axs=plt.subplots(2,2,figsize=(10,10))
        for col,d in enumerate(r['downloads']):
            with rasterio.open(OUT/'pairs'/f"{s['id']}_{d['year']}.tif") as ds:a=ds.read();t=ds.transform
            rgb=np.clip(np.moveaxis(a[:3],0,2)/3000,0,1)**(1/1.4)
            extent=[t.c,t.c+500,t.f-500,t.f]
            for row in [0,1]:
                ax=axs[row,col];ax.imshow(rgb,extent=extent,interpolation='nearest')
                if row:
                    rgba=np.zeros((50,50,4));rgba[a[5]==0]=[1,0,1,.55]
                    ax.imshow(rgba,extent=extent,interpolation='nearest')
                ax.add_patch(Polygon(s['target_utm'],fill=False,edgecolor='red',linewidth=1.3))
                ax.set_axis_off();ax.set_title(d['scene']['date'][:10]+(' | quality exclusions' if row else ' | RGB'))
        fig.suptitle(f"{s['id']} | 500 m footprint; red = original ~30 m target\nSentinel-2 / Copernicus; fixed stretch; magenta = quality exclusion",fontsize=13)
        fig.tight_layout();fig.savefig(OUT/'cards'/f"{s['id']}.png",dpi=120);plt.close(fig)
    print('Anonymous paired cards rendered; no membership key read.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['init','inventory','acquire','render']);args=p.parse_args()
    {'init':initialize,'inventory':inventory,'acquire':acquire,'render':render}[args.action]()
