"""Reference-only trajectory and delivery-tile diagnostics, before enrichment."""
import json
import numpy as np
from scripts.building_change_explore.analyse import OUT,labels,block_counts


def main():
    local=np.load(OUT/'local_arrays.npz');ref=np.load(OUT/'reference_fractions.npy')
    _,v,lo,hi,amb=labels(ref)
    add=lo[0]&hi[3];labels_code=np.where(~v,3,np.where(lo,0,np.where(hi,2,1)))
    patterns=(labels_code*np.array([64,16,4,1])[:,None,None]).sum(axis=0)
    x=local['x'];y=local['y'];source_records=[];near=[]
    for year in range(2020,2024):
        manifest=json.loads((OUT/f'provider_{year}_manifest.json').read_text())
        distance=np.full(x.shape,np.inf)
        for tileset in manifest['tilesets']:
            assert tileset['crs']=='EPSG:32748'
            for source in tileset['sources']:
                a=source['affineTransform'];dims=source['dimensions']
                left=a['translateX'];right=left+a['scaleX']*dims['width'];top=a['translateY'];bottom=top+a['scaleY']*dims['height']
                if right<x.min()-50 or left>x.max()+50 or top<y.min()-50 or bottom>y.max()+50:continue
                source_records.append({'year':year,'uri':manifest['uriPrefix']+source['uris'][0],'bounds_utm':[left,bottom,right,top]})
                dy=y-np.clip(y,bottom,top);dx=x-np.clip(x,left,right)
                for xx in [left,right]:distance=np.minimum(distance,np.hypot(x-xx,dy))
                for yy in [bottom,top]:distance=np.minimum(distance,np.hypot(y-yy,dx))
        near.append(distance<=30)
    edge=np.logical_or.reduce(near)
    rows=[]
    for sid,sector in [(0,'NW'),(3,'W')]:
        geo=local['inside']&(local['sectors']==sid)
        p,n=np.unique(patterns[geo],return_counts=True)
        def decode(number):return ''.join('LAHM'[(int(number)//factor)%4] for factor in [64,16,4,1])
        q={'sector':sector,'trajectory_key':'L=low <=0.10; A=ambiguous; H=high >=0.40; M=missing support. Ordered 2020,2021,2022,2023.','trajectories':{decode(k):int(c) for k,c in zip(p,n)},'primary_additions':int((geo&add).sum()),'addition_high_2021_low_2022':int((geo&add&hi[1]&lo[2]).sum()),'addition_missing_intermediate':int((geo&add&~(v[1]&v[2])).sum()),'delivery_boundary_cells_within_30m':int((geo&edge).sum()),'additions_within_30m_delivery_boundary':int((geo&edge&add).sum()),'nonboundary_cells':int((geo&~edge).sum()),'nonboundary_additions':int((geo&~edge&add).sum())}
        rows.append(q)
    result={'diagnostics':rows,'source_tiles':source_records,'boundary_limitation':'COG delivery boundaries from provider manifests are not necessarily the internal model inference tile boundaries. The latter are unavailable in these metadata. Boundary proximity does not prove an artifact.','enrichment_examined':False}
    (OUT/'reference_only_diagnostics.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps([{k:v for k,v in r.items() if k!='trajectories'} for r in rows],indent=2))


if __name__=='__main__':main()
