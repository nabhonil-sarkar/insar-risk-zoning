"""Export 4 m aggregated reference-only development windows and contact sheets."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import threading
import time
import urllib.request
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import Affine
from scipy.ndimage import binary_erosion, shift
from scripts.building_change_explore.aggregate_reference import initialize,OUT
import ee

LOCK=threading.Lock()


def export_sample(sample):
    folder=OUT/'inspection_windows';folder.mkdir(exist_ok=True)
    path=folder/(sample['id']+'.tif');record_path=path.with_suffix('.json')
    if record_path.exists():
        r=json.loads(record_path.read_text())
        if r.get('complete') and path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==r['sha256']:return r
        raise RuntimeError('Incomplete sample export exists')
    x0=math.floor((sample['x']-152)/4)*4;y0=math.ceil((sample['y']+152)/4)*4
    transform=[4,0,x0,0,-4,y0]
    images=[]
    for year in range(2020,2024):
        p=ee.Image(f'GOOGLE/Research/open-buildings-temporal/v1/2f_EPSG_32748_{year}_06_30').select('building_presence')
        good=p.mask().gt(0).And(p.gte(0)).And(p.lte(1));p=p.updateMask(good)
        stack=ee.Image.cat([p.gte(.41).unmask(0,False),p.gte(.34).unmask(0,False),good.unmask(0,False)]).toFloat().setDefaultProjection(p.projection())
        images.append(stack.reduceResolution(ee.Reducer.mean(),False,256).reproject(crs='EPSG:32748',crsTransform=transform).rename([f'positive041_{year}',f'positive034_{year}',f'support_{year}']))
    record={'id':sample['id'],'transform':transform,'started_utc':datetime.now(timezone.utc).isoformat(),'complete':False,'body_bytes':0,'resolution':'4 m area-weighted binary-presence fractions; no native 0.5 m pixels downloaded'}
    started=time.monotonic()
    try:
        url=ee.Image.cat(images).getDownloadURL({'crs':'EPSG:32748','crs_transform':transform,'dimensions':[77,77],'format':'GEO_TIFF','filePerBand':False})
        with urllib.request.urlopen(url,timeout=190) as response,path.open('xb') as stream:
            while True:
                chunk=response.read(65536)
                if not chunk:break
                record['body_bytes']+=len(chunk)
                if record['body_bytes']>2_000_000:raise RuntimeError('Sample size limit')
                stream.write(chunk)
        with rasterio.open(path) as ds:
            assert ds.count==12 and ds.shape==(77,77) and ds.transform==Affine(*transform)
            a=ds.read()
        assert np.isfinite(a).all() and a.min()>=0 and a.max()<=1.000001
        record.update(complete=True,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    except Exception as exc:record['error']=str(exc)
    finally:
        record['elapsed_seconds']=time.monotonic()-started;record_path.write_text(json.dumps(record,indent=2)+'\n')
        with LOCK:
            ledger_path=OUT/'resource_accounting.json';ledger=json.loads(ledger_path.read_text());ledger['measured_response_body_bytes']+=record['body_bytes'];ledger.setdefault('inspection_exports',[]).append(record);ledger_path.write_text(json.dumps(ledger,indent=2)+'\n')
    print(json.dumps(record),flush=True)
    return record


def diagnostics(sample):
    with rasterio.open(OUT/'inspection_windows'/(sample['id']+'.tif')) as ds:a=ds.read().reshape(4,3,77,77);t=ds.transform
    p=a[:,0]>.5;alternative=a[:,1]>.5;good=a[:,2]>=.95
    base=p[0];last=p[3];common=good[0]&good[3]
    take=common.copy();take[:2]=False;take[-2:]=False;take[:,:2]=False;take[:,-2:]=False
    raw_iou=((base&last)&take).sum()/max(1,((base|last)&take).sum())
    best=(raw_iou,0,0)
    for dy in range(-2,3):
        for dx in range(-2,3):
            shifted=shift(last.astype(np.uint8),(dy,dx),order=0,cval=0).astype(bool)
            iou=((base&shifted)&take).sum()/max(1,((base|shifted)&take).sum())
            if iou>best[0]:best=(float(iou),dy,dx)
    gain=last&~base&common;loss=base&~last&common
    core=binary_erosion(last)&~base&common
    return {'id':sample['id'],'baseline_patch_building_4m_cells':int(base.sum()),'endpoint_patch_building_4m_cells':int(last.sum()),'gain_4m_cells':int(gain.sum()),'loss_4m_cells':int(loss.sum()),'gain_retaining_eroded_2023_core_cells':int(core.sum()),'jaccard_no_shift':float(raw_iou),'best_jaccard_within_8m':best[0],'best_shift_m':[best[2]*4,-best[1]*4],'presence_sensitivity_disagreement_fraction':float((p!=alternative).mean()),'missing_support_fraction':float((~good).mean()),'interpretation':'Shift optimum is an alignment diagnostic, not an estimated physical displacement; gain/loss within 308 m window are reference labels only.'}


def sheets(samples,grid):
    t=Affine(*grid['transform']);utm=Transformer.from_crs(4326,32748,always_xy=True)
    for stratum in ['addition','stable_low','stable_high','unstable']:
        rows=[s for s in samples if s['stratum']==stratum]
        fig,axes=plt.subplots(len(rows),4,figsize=(12,3*len(rows)),squeeze=False)
        for i,s in enumerate(rows):
            with rasterio.open(OUT/'inspection_windows'/(s['id']+'.tif')) as ds:a=ds.read().reshape(4,3,77,77);b=ds.bounds
            corners=[t*(s['col'],s['row']),t*(s['col']+1,s['row']),t*(s['col']+1,s['row']+1),t*(s['col'],s['row']+1)]
            corners=np.array([utm.transform(*p) for p in corners])
            for j in range(4):
                ax=axes[i,j];cmap=plt.get_cmap('Greys').copy();cmap.set_bad('#e8b8dd')
                ax.imshow(np.ma.array(a[j,0],mask=a[j,2]<.95),cmap=cmap,vmin=0,vmax=1,extent=[b.left,b.right,b.bottom,b.top]);ax.add_patch(Polygon(corners,fill=False,edgecolor='#e66b16',linewidth=1.5))
                value=s['coverage_041'][j];display=f'{value:.2f}' if value is not None else 'missing'
                ax.set_title(f"{2020+j} · cell cover {display}",fontsize=10);ax.set_xticks([]);ax.set_yticks([])
                if j==0:ax.set_ylabel(s['id']+('\n2020 water' if s['baseline_water'] else '\n2020 land'),fontsize=9)
        fig.suptitle(f"Reference-only development inspection: {stratum.replace('_',' ')}\nDark = building coverage at 4 m; orange = analysis cell; pink = missing support",fontsize=14)
        fig.text(.5,.01,'Rule-selected development locations; June 30 inference dates. These are model outputs, not independent imagery validation.',ha='center',fontsize=9)
        fig.tight_layout(rect=[0,.025,1,.96]);fig.savefig(OUT/f'inspection_{stratum}.png',dpi=130);plt.close(fig)


def main():
    grid=initialize();samples=json.loads((OUT/'reference_sample.json').read_text())
    ledger=json.loads((OUT/'resource_accounting.json').read_text())
    charged=ledger['measured_response_body_bytes']+ledger.get('dependency_payload_bytes',0)+20_000_000
    if charged+50_000_000>ledger['cap_bytes']:raise RuntimeError('Insufficient sample budget')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(export_sample,samples))
    if not all(r['complete'] for r in results):raise RuntimeError('Incomplete inspection exports')
    diag=[diagnostics(s) for s in samples]
    (OUT/'inspection_diagnostics.json').write_text(json.dumps(diag,indent=2)+'\n')
    sheets(samples,grid)


if __name__=='__main__':main()
