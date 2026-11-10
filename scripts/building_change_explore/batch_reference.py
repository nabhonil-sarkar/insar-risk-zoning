"""Monitor and download the four private aggregate Earth Engine assets."""
import argparse
from datetime import datetime, timezone
import json
from scripts.building_change_explore.aggregate_reference import OUT,initialize,download,aggregate
from rasterio.transform import Affine
import ee


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['submit','status','download']);a=p.parse_args()
    grid=initialize(); path=OUT/'batch_exports_v3.json'
    if a.mode=='submit':
        if path.exists():raise FileExistsError(path)
        t=Affine(*grid['transform'])
        rect=ee.Geometry.Rectangle([t.c,t.f+t.e*1312,t.c+t.a*953,t.f],proj='EPSG:4326',geodesic=False)
        records=[]
        project=json.loads((OUT/'reference_provenance.json').read_text())['project_access']['id']
        for year in range(2020,2024):
            asset=f'projects/{project}/assets/building_change_explore_v1_{year}_20261110_v3'
            task=ee.batch.Export.image.toAsset(image=aggregate(year,grid['transform']),description=f'building_change_day1_{year}_v3',assetId=asset,region=rect,crs='EPSG:4326',crsTransform=grid['transform'],maxPixels=10000000,shardSize=64,pyramidingPolicy={'.default':'mean'})
            task.start();records.append({'year':year,'asset':asset,'task_id':task.id,'submitted_utc':datetime.now(timezone.utc).isoformat(),'status':task.status()})
            path.write_text(json.dumps(records,indent=2)+'\n')
    else: records=json.loads(path.read_text())
    states=ee.data.getTaskStatus([r['task_id'] for r in records])
    for r,status in zip(records,states):r['status']=status
    path.write_text(json.dumps(records,indent=2)+'\n')
    ledger_path=OUT/'resource_accounting.json';ledger=json.loads(ledger_path.read_text())
    ledger['exports_submitted']=[{'year':r['year'],'task_id':r['task_id'],'asset':r['asset'],'state':r['status']['state']} for r in records]
    ledger['incomplete_batch_exports']=[r['task_id'] for r in records if r['status']['state']!='COMPLETED']
    ledger_path.write_text(json.dumps(ledger,indent=2)+'\n')
    print(json.dumps({'checked_utc':datetime.now(timezone.utc).isoformat(),'tasks':ledger['exports_submitted']},indent=2),flush=True)
    if a.mode=='download':
        if any(r['status']['state']!='COMPLETED' for r in records): raise RuntimeError('Batch exports not all complete')
        folder=OUT/'reference_batch';folder.mkdir(exist_ok=True)
        for r in records:
            result=download(ee.Image(r['asset']),grid,r['year'],0,0,1312,953,folder)
            if not result['complete']:raise RuntimeError(result['error'])


if __name__=='__main__':main()
