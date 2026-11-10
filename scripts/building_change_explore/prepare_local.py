"""Verify frozen inputs and prepare geography/rankings without reference outcomes."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import Affine
from scripts.alphaearth_surface_type import sector_grid
from scripts.run_alphaearth_surface_type import digest, PINS, MANIFEST_SHA, WC_SHA
from scripts.run_alphaearth_tile_seam import sample_cover

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/output/building_change_explore_v1'
FULL = ROOT / 'data/output/alphaearth_annual_change/gcs_full_v1'


def save(name, obj):
    with (OUT/name).open('x',encoding='utf-8') as f:
        json.dump(obj,f,indent=2,allow_nan=False)
        f.write('\n')


def main(worldcover):
    WC = Path(worldcover).resolve()
    if (OUT/'local_arrays.npz').exists():
        raise FileExistsError('Preparation already exists')
    pins = {str(ROOT/p):sha for p,sha in PINS.items()}
    pins[str(FULL/'cosine_change/manifest.json')] = MANIFEST_SHA
    pins[str(WC)] = WC_SHA
    manifest=json.loads((FULL/'cosine_change/manifest.json').read_text())
    for year in range(2020,2024):
        pins[str(FULL/f'Jakarta_GCS20m_on30m_{year}_qint8.tif')] = manifest['annual_sha256'][str(year)]
        pins[str(FULL/f'{year}_qa.json')] = manifest['annual_qa_sha256'][str(year)]
    for entry in manifest['comparisons']:
        if entry['years'] in [[2020,2023],[2020,2025]]:
            pins[str(FULL/f"cosine_change/cosine_{entry['years'][0]}_{entry['years'][1]}.tif")] = entry['sha256']
    pins[str(ROOT/'data/output/alphaearth_seam_v2/results.json')]='763bfa06a8f74e823a91b056c0c856f550f0d8cff4ce124c18c2238c1b82920b'
    pins[str(ROOT/'data/output/alphaearth_surface_type_v1/run/results.json')]='b5a29d2710701e664160080291c6bc297c7b34617f7f315ae22769377b5de4b9'
    for p,expected in pins.items():
        if digest(p)!=expected: raise ValueError(f'Changed input: {p}')
    contract=json.loads((ROOT/'data/output/alphaearth_annual_change/alphaearth_annual_change_contract.json').read_text())
    grid=contract['frozen_reference_grid']; t=Affine(*grid['transform'])
    h,w=grid['height'],grid['width']
    lon=t.c+(np.arange(w)+.5)*t.a; lat=t.f+(np.arange(h)+.5)*t.e
    inside=((lon>=106.45)&(lon<=107.22))[None,:]&((lat>=-6.54)&(lat<=-6.01))[:,None]
    assert inside.sum()==5619719
    sectors=sector_grid((h,w)); pilot=inside&np.isin(sectors,[0,3])
    with rasterio.open(WC) as ds: cover=sample_cover(ds,lon,lat)
    assert not np.ma.getmaskarray(cover)[inside].any()
    cover=np.asarray(cover); assert np.all(np.isin(cover[inside],[10,20,30,40,50,60,70,80,90,95,100]))
    x,y=Transformer.from_crs(4326,32748,always_xy=True).transform(*np.meshgrid(lon[:953],lat[:1312]))
    bx=np.floor(x/1000).astype(np.int32); by=np.floor(y/1000).astype(np.int32)
    gx=np.floor(x/5000).astype(int); gy=np.floor(y/5000).astype(int)
    pairs=np.unique(np.column_stack([gx.ravel(),gy.ravel()]),axis=0)
    split=np.zeros(gx.shape,np.uint8); records=[]
    for a,b in pairs:
        v=int(hashlib.sha256(f'building_change_v1:{a}:{b}'.encode()).hexdigest()[:8],16)%10
        group=0 if v<2 else 1 if v<4 else 2
        split[(gx==a)&(gy==b)]=group
        records.append({'easting_index':int(a),'northing_index':int(b),'split':['test','development','training'][group]})
    buffer=(x%5000>=250)&(x%5000<=4750)&(y%5000>=250)&(y%5000<=4750)
    arrays={'inside':inside[:1312,:953],'cover':cover[:1312,:953],'sectors':sectors[:1312,:953],
            'block_x':bx,'block_y':by,'split':split,'buffer_retained':buffer,'x':x,'y':y}
    rankings=[]; counts=[]
    seam=json.loads((ROOT/'data/output/alphaearth_seam_v2/results.json').read_text())['endpoint_sensitivity']['original']
    for end in (2023,2025):
        with rasterio.open(FULL/f'cosine_change/cosine_2020_{end}.tif') as ds:
            assert ds.transform==t and ds.shape==(h,w) and str(ds.crs)==grid['crs']
            a=ds.read(1); valid=ds.read_masks(1)>0
        assert np.array_equal(valid,inside) and np.isfinite(a[valid]).all()
        for percent in (1,5):
            cutoff=float(np.quantile(a[valid].astype(np.float64),1-percent/100,method='linear'))
            hot=valid&(a>=cutoff)
            if (end,percent)==(2025,1):
                assert cutoff==seam['cutoff'] and hot.sum()==56198 and (hot&(sectors==0)).sum()==18096
            rankings.append({'end':end,'top_percent':percent,'cutoff':cutoff,'valid_cells':int(valid.sum()),'extreme_cells':int(hot.sum()),'equal_cutoff_cells':int((a[valid]==cutoff).sum()),'membership_sha256':hashlib.sha256(np.packbits(hot).tobytes()).hexdigest()})
            arrays[f'hot_{end}_{percent}']=hot[:1312,:953]
            for sid,sector in [(0,'NW'),(3,'W')]:
                for surface in ('combined','land','water'):
                    take=valid&(sectors==sid)
                    if surface!='combined': take &= (cover==80) if surface=='water' else (cover!=80)
                    counts.append({'sector':sector,'period':f'2020-{end}','top_percent':percent,'surface':surface,'valid_cells':int(take.sum()),'extreme_cells':int((hot&take).sum())})
    np.savez_compressed(OUT/'local_arrays.npz',**arrays)
    save('input_verification.json',{'verified_utc':datetime.now(timezone.utc).isoformat(),'input_sha256':pins,'grid':grid,'pilot_shape':[1312,953],'original_membership_reproduced':True,'rankings':rankings})
    save('spatial_assignments.json',{'groups':records,'buffer_m':250,'sample_excluded_from_test':True})
    save('baseline_counts.json',counts)
    with (OUT/'baseline_counts.csv').open('x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(counts[0]));writer.writeheader();writer.writerows(counts)
    print(json.dumps({'verified_inputs':len(pins),'rankings':rankings,'counts':counts},indent=2))


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worldcover', required=True, help='Local pinned WorldCover raster; SHA-256 is checked')
    main(parser.parse_args().worldcover)
