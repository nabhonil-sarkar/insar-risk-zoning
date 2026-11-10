"""Day 1 reference-only inspection and, after a quality gate, enrichment."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import numpy as np
import rasterio

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'data/output/building_change_explore_v1'


def write(name,obj):
    with (OUT/name).open('x',encoding='utf-8') as f: json.dump(obj,f,indent=2,allow_nan=False)


def labels(ref,threshold_index=0):
    support=ref[:,2]
    coverage=np.divide(ref[:,threshold_index],support,out=np.full_like(support,np.nan),where=support>0)
    valid=(support>=.95)&np.isfinite(coverage)
    low=valid&(coverage<=.10)
    high=valid&(coverage>=.40)
    ambiguous=valid&~(low|high)
    return coverage,valid,low,high,ambiguous


def assemble():
    ref=np.full((4,3,1312,953),np.nan,np.float32)
    occupied=np.zeros((4,1312,953),np.uint8)
    folder=OUT/'reference_chunks_v4'
    selected={}
    for p in sorted(folder.glob('*.json')):
        j=json.loads(p.read_text());key=(j['year'],j['row'],j['col'])
        if j.get('complete'):
            if key in selected:
                old_path,old=selected[key]
                with rasterio.open(old_path.with_suffix('.tif')) as d:before=d.read();before_transform=d.transform
                with rasterio.open(p.with_suffix('.tif')) as d:after=d.read();after_transform=d.transform
                assert before_transform==after_transform and np.allclose(before,after,atol=1e-6,rtol=0),f'Conflicting duplicate export: {p}'
            selected[key]=(p,j)
    for p,j in selected.values():
        f=p.with_suffix('.tif')
        assert hashlib.sha256(f.read_bytes()).hexdigest()==j['sha256']
        y=j['year']-2020;r=j['row'];c=j['col'];h=j['height'];w=j['width']
        with rasterio.open(f) as ds: a=ds.read()
        ref[y,:,r:r+h,c:c+w]=a; occupied[y,r:r+h,c:c+w]+=1
    assert (occupied==1).all() and np.isfinite(ref).all()
    assert np.all(ref[:,0]<=ref[:,1]+1e-6) and np.all(ref[:,1]<=ref[:,2]+1e-6)
    for f in (OUT/'aggregation_probe').glob('*.json'):
        j=json.loads(f.read_text());y=j['year']-2020;r=j['row'];c=j['col'];h=j['height'];w=j['width']
        with rasterio.open(f.with_suffix('.tif')) as ds: probe=ds.read()
        assert np.allclose(probe,ref[y,:,r:r+h,c:c+w],atol=1e-6,rtol=0)
    np.save(OUT/'reference_fractions.npy',ref)
    return ref


def block_counts(mask,local):
    if not mask.any(): return {'blocks':0,'blocks_ge3':0,'largest_block_share':None}
    _,n=np.unique(np.column_stack([local['block_x'][mask],local['block_y'][mask]]),axis=0,return_counts=True)
    return {'blocks':len(n),'blocks_ge3':int((n>=3).sum()),'largest_block_share':float(n.max()/mask.sum())}


def reference_only():
    ref=assemble(); local=np.load(OUT/'local_arrays.npz'); cv,v,lo,hi,amb=labels(ref)
    primary=lo[0]&hi[3]; stable_low=lo.all(axis=0);stable_high=hi.all(axis=0)
    changes_bin=(lo!=lo[0]).any(axis=0)|(hi!=hi[0]).any(axis=0)
    unstable=v.all(axis=0)&changes_bin&~primary
    records=[];summary=[]
    def finite_list(values):return [float(z) if np.isfinite(z) else None for z in values]
    for sid,sector in [(0,'NW'),(3,'W')]:
        geo=local['inside']&(local['sectors']==sid)
        add=geo&primary
        summary.append({'sector':sector,'cells':int(geo.sum()),'endpoint_supported':int((geo&v[0]&v[3]).sum()),'all_year_supported':int((geo&v.all(axis=0)).sum()),'endpoint_ambiguous':int((geo&v[0]&v[3]&(amb[0]|amb[3])).sum()),'primary_additions':int(add.sum()),'persistent_additions':int((add&lo[1]).sum()),**block_counts(add,local)})
        for stratum,mask in [('stable_low',stable_low),('stable_high',stable_high),('addition',primary),('unstable',unstable)]:
            take=geo&mask&(local['split']==1)&local['buffer_retained']
            blocks=np.unique(np.column_stack([local['block_x'][take],local['block_y'][take]]),axis=0)
            ordered=sorted(blocks.tolist(),key=lambda b:hashlib.sha256(f'sample_v1:{sector}:{stratum}:{b[0]}:{b[1]}'.encode()).hexdigest())
            for b in ordered[:3]:
                rr,cc=np.where(take&(local['block_x']==b[0])&(local['block_y']==b[1]))
                d=(local['x'][rr,cc]-(b[0]+.5)*1000)**2+(local['y'][rr,cc]-(b[1]+.5)*1000)**2
                k=np.argmin(d);r=int(rr[k]);c=int(cc[k])
                records.append({'id':f'{sector}_{stratum}_{len([z for z in records if z["sector"]==sector and z["stratum"]==stratum])+1}','sector':sector,'stratum':stratum,'block':b,'row':r,'col':c,'x':float(local['x'][r,c]),'y':float(local['y'][r,c]),'coverage_041':finite_list(cv[:,r,c]),'coverage_034':finite_list(labels(ref,1)[0][:,r,c]),'support':ref[:,2,r,c].tolist(),'baseline_water':bool(local['cover'][r,c]==80),'split':'development','review':'pending'})
    write('reference_quality_counts.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'summary':summary,'sample_count':len(records),'enrichment_examined':False})
    write('reference_sample.json',records)
    print(json.dumps({'summary':summary,'samples':records},indent=2))


def ratio(n,d):return float(n/d) if d else None


def metrics(eligible,addition,extreme,local):
    assert not np.any(addition&~eligible)
    e=int(eligible.sum());a=int(addition.sum());x=int((eligible&extreme).sum());ax=int((addition&extreme).sum())
    prevalence=ratio(a,e);extreme_prevalence=ratio(ax,x)
    return {'eligible_cells':e,'addition_cells':a,'eligible_extreme_cells':x,'addition_extreme_cells':ax,'addition_prevalence':prevalence,'extreme_addition_prevalence':extreme_prevalence,'enrichment':ratio(extreme_prevalence,prevalence) if prevalence and extreme_prevalence is not None else None,'addition_capture_fraction':ratio(ax,a),**block_counts(addition,local),'extreme_addition_blocks':block_counts(addition&extreme,local)['blocks']}


def enrichment():
    gate=json.loads((OUT/'reference_review.json').read_text())
    if not gate.get('reference_usable'):raise RuntimeError('Reference-quality gate did not pass')
    ref=np.load(OUT/'reference_fractions.npy');local=np.load(OUT/'local_arrays.npz');rows=[]
    for ti,threshold in enumerate([.41,.34]):
        cv,v,lo,hi,amb=labels(ref,ti)
        endpoint=v[0]&v[3];clear=(lo[0]|hi[0])&(lo[3]|hi[3]);primary=lo[0]&hi[3]
        for rule in ['endpoint','persistence_2021_low','endpoint_common_2021_support']:
            eligible=clear.copy();addition=primary.copy()
            if rule!='endpoint':eligible &=lo[1]|hi[1];addition &=eligible
            if rule=='persistence_2021_low':addition &=lo[1]
            for sid,sector in [(0,'NW'),(3,'W')]:
                for surface in ['combined','land','water']:
                    geo=local['inside']&(local['sectors']==sid)
                    if surface!='combined':geo &= (local['cover']==80) if surface=='water' else (local['cover']!=80)
                    for end in [2023,2025]:
                        for top in [1,5]:
                            hot=local[f'hot_{end}_{top}'];e=geo&eligible;a=geo&addition
                            row={'threshold':threshold,'rule':rule,'sector':sector,'surface':surface,'period':f'2020-{end}','top_percent':top,'baseline_cells':int(geo.sum()),'original_extreme_cells':int((geo&hot).sum()),'endpoint_missing_support':int((geo&~endpoint).sum()),'endpoint_ambiguous':int((geo&endpoint&~clear).sum()),'additional_2021_exclusions':int((geo&clear&~eligible).sum()),'extremes_missing_support':int((geo&hot&~endpoint).sum()),'extremes_ambiguous':int((geo&hot&endpoint&~clear).sum()),**metrics(e,a,hot,local)}
                            extra_missing=geo&clear&~v[1] if rule!='endpoint' else np.zeros_like(geo)
                            extra_ambiguous=geo&clear&amb[1] if rule!='endpoint' else np.zeros_like(geo)
                            row.update(additional_2021_missing_support=int(extra_missing.sum()),additional_2021_ambiguous=int(extra_ambiguous.sum()),additional_2021_extremes_missing_support=int((extra_missing&hot).sum()),additional_2021_extremes_ambiguous=int((extra_ambiguous&hot).sum()))
                            assert row['baseline_cells']==row['eligible_cells']+row['endpoint_missing_support']+row['endpoint_ambiguous']+row['additional_2021_missing_support']+row['additional_2021_ambiguous']
                            assert row['original_extreme_cells']==row['eligible_extreme_cells']+row['extremes_missing_support']+row['extremes_ambiguous']+row['additional_2021_extremes_missing_support']+row['additional_2021_extremes_ambiguous']
                            if surface=='combined' and rule=='endpoint' and ti==0:
                                blocks=np.unique(np.column_stack([local['block_x'][a],local['block_y'][a]]),axis=0)
                                vals=[]
                                for bx,by in blocks:
                                    retain=~((local['block_x']==bx)&(local['block_y']==by))
                                    # Recalculate ratio counts only; full block recount per deletion is unnecessary.
                                    en=int((e&retain).sum());an=int((a&retain).sum());xn=int((e&hot&retain).sum());axn=int((a&hot&retain).sum())
                                    if an and xn:vals.append((axn/xn)/(an/en))
                                row['leave_one_addition_block_out_min_enrichment']=min(vals) if vals else None
                            rows.append(row)
    write('enrichment_metrics.json',rows)
    fields=sorted(set().union(*(r.keys() for r in rows)))
    with (OUT/'enrichment_metrics.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    print(json.dumps([r for r in rows if r['surface']=='combined' and r['threshold']==.41 and r['rule']=='endpoint'],indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['reference','enrichment']);a=p.parse_args()
    reference_only() if a.mode=='reference' else enrichment()
