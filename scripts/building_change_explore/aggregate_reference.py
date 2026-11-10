"""Export thresholded, area-weighted Open Buildings fractions on the frozen grid.

No raw reference raster is downloaded. Native projection and bestEffort=False
preserve threshold-before-aggregation; fractional output-pixel overlap weights.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import urllib.request

import numpy as np
import rasterio
from rasterio.transform import Affine

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'data/output/building_change_explore_v1'
sys.path.insert(0,str(OUT/'ee_runtime'))
import ee

LOCK=threading.Lock()
LEDGER=OUT/'resource_accounting.json'
BANDS=['positive_area_fraction_041','positive_area_fraction_034','valid_area_fraction']


def initialize():
    project=json.loads((OUT/'reference_provenance.json').read_text())['project_access']['id']
    ee.Initialize(project=project)
    ee.data.setDeadline(180000)
    return json.loads((OUT/'input_verification.json').read_text())['grid']


def aggregate(year,transform):
    source=ee.Image(f'GOOGLE/Research/open-buildings-temporal/v1/2f_EPSG_32748_{year}_06_30').select('building_presence')
    native=source.projection()
    p=source
    good=p.mask().gt(0).And(p.gte(0)).And(p.lte(1))
    p=p.updateMask(good)
    stack=ee.Image.cat([p.gte(.41).unmask(0,False),p.gte(.34).unmask(0,False),good.unmask(0,False)]).rename(BANDS).toFloat().setDefaultProjection(native)
    # Direct exports are partitioned into small target-grid windows. This avoids
    # the batch service's fixed internal tile size without changing reduction.
    return stack.reduceResolution(reducer=ee.Reducer.mean(),bestEffort=False,maxPixels=16384).toFloat()


def download(image,grid,year,row,col,height,width,folder):
    target=folder/f'{year}_r{row}_c{col}_h{height}_w{width}.tif'
    record_path=target.with_suffix('.json')
    if target.exists() and record_path.exists():
        old=json.loads(record_path.read_text())
        if old.get('complete') and hashlib.sha256(target.read_bytes()).hexdigest()==old['sha256']:
            return old
        if not old.get('complete'):
            target=target.with_name(target.stem+'_attempt2.tif');record_path=target.with_suffix('.json')
    elif record_path.exists():
        old=json.loads(record_path.read_text())
        if not old.get('complete'):
            target=target.with_name(target.stem+'_attempt2.tif');record_path=target.with_suffix('.json')
    if record_path.exists():
        old=json.loads(record_path.read_text())
        if old.get('complete') and target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==old['sha256']:return old
        raise RuntimeError(f'Two-attempt limit or unexpected existing evidence: {record_path}')
    t=Affine(*grid['transform'])*Affine.translation(col,row)
    record={'year':year,'row':row,'col':col,'height':height,'width':width,'name':target.name,'started_utc':datetime.now(timezone.utc).isoformat(),'complete':False,'body_bytes':0}
    record_path.write_text(json.dumps(record,indent=2)+'\n')
    started=time.monotonic()
    try:
        url=image.getDownloadURL({'crs':'EPSG:4326','crs_transform':list(t)[:6],'dimensions':[width,height],'format':'GEO_TIFF','filePerBand':False})
        request=urllib.request.Request(url,headers={'Accept-Encoding':'identity'})
        # A single bounded retry is allowed for transient service availability.
        for attempt in range(2):
            try:
                response=urllib.request.urlopen(request,timeout=190)
                break
            except urllib.error.HTTPError as exc:
                record['body_bytes']+=len(exc.read(65536))
                record.setdefault('http_failures',[]).append({'status':exc.code,'attempt':attempt+1})
                if exc.code not in (429,500,502,503,504) or attempt:raise
                time.sleep(3)
        with response,target.open('xb') as stream:
            while True:
                chunk=response.read(65536)
                if not chunk: break
                record['body_bytes']+=len(chunk)
                if record['body_bytes']>32_000_000: raise RuntimeError('Export size bound exceeded')
                stream.write(chunk)
        with rasterio.open(target) as ds:
            assert ds.shape==(height,width) and ds.transform.almost_equals(t,precision=1e-12) and str(ds.crs)=='EPSG:4326' and ds.count==3
            a=ds.read()
        assert np.isfinite(a).all() and a.min()>=-1e-6 and a.max()<=1.000001
        assert (a[0]<=a[1]+1e-6).all() and (a[1]<=a[2]+1e-6).all()
        record.update(complete=True,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),band_min=a.min(axis=(1,2)).tolist(),band_max=a.max(axis=(1,2)).tolist())
    except Exception as exc:
        record['error']=str(exc)
    finally:
        record['elapsed_seconds']=time.monotonic()-started
        record_path.write_text(json.dumps(record,indent=2)+'\n')
        with LOCK:
            ledger_path=LEDGER; ledger=json.loads(ledger_path.read_text())
            ledger['measured_response_body_bytes']+=record['body_bytes']
            ledger.setdefault('aggregate_exports',[]).append({'file':str(target.relative_to(OUT)),**record})
            ledger['incomplete_exports']=[x['file'] for x in ledger['aggregate_exports'] if not x['complete']]
            ledger_path.write_text(json.dumps(ledger,indent=2)+'\n')
    print(json.dumps(record),flush=True)
    return record


def main():
    global LEDGER
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['probe','pilot'])
    parser.add_argument('--chunk',type=int,default=128)
    parser.add_argument('--folder',default=None)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--years',type=int,nargs='+',default=list(range(2020,2024)))
    parser.add_argument('--ledger',default='resource_accounting.json')
    args=parser.parse_args()
    if not (1<=args.workers<=8 and 1<=args.chunk<=128 and set(args.years)<=set(range(2020,2024))):
        raise ValueError('Require 1–8 workers, 1–128 cell chunks, and only 2020–2023')
    grid=initialize(); folder=OUT/(args.folder or ('aggregation_probe' if args.mode=='probe' else 'reference_chunks'));folder.mkdir(exist_ok=True)
    LEDGER=OUT/args.ledger
    ledger=json.loads(LEDGER.read_text())
    charged=ledger['measured_response_body_bytes']+ledger.get('dependency_payload_bytes',0)+ledger['unmetered_web_documentation_allowance_bytes']+ledger.get('package_index_and_auth_allowance_bytes',0)
    # Pilot raw float output ~60 MB; reserve 150 MB for TIFF overhead and one bounded failed set.
    if charged+150_000_000>ledger['cap_bytes']: raise RuntimeError('Insufficient remaining cap')
    images={y:aggregate(y,grid['transform']) for y in args.years}
    jobs=[]
    for y in images:
        if args.mode=='probe': jobs.append((y,800,400,32,32))
        else:
            for r in range(0,1312,args.chunk):
                for c in range(0,953,args.chunk):jobs.append((y,r,c,min(args.chunk,1312-r),min(args.chunk,953-c)))
    failures=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(download,images[y],grid,y,r,c,h,w,folder) for y,r,c,h,w in jobs]
        for future in as_completed(futures):
            result=future.result()
            if not result['complete']:
                failures.append(result)
                for pending in futures: pending.cancel()
                break
    if failures: raise RuntimeError(f'Aggregation stopped: {len(failures)} failure(s)')


if __name__=='__main__':main()
