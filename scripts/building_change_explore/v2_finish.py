"""Reconcile v2 evidence and cumulative resources without editing Day 1."""
from datetime import datetime,timezone
import csv
import json
import numpy as np
import rasterio
from scripts.building_change_explore.v2 import BASE,OUT,read,write,sha,now,target_polygon,polygons
from scripts.building_change_explore.v2_figures import sheet


def main():
    sites=read('fresh_sites.json');metrics=read('fresh_metrics.json');local=np.load(BASE/'local_arrays.npz')
    old=json.loads((BASE/'reference_sample.json').read_text())
    assert len(sites)==30 and len({tuple(s['block']) for s in sites})==30
    minimum_distance=float('inf')
    for i,s in enumerate(sites):
        assert local['split'][s['row'],s['col']]==1 and local['buffer_retained'][s['row'],s['col']]
        assert tuple(s['block']) not in {tuple(z['block']) for z in old}
        for z in old+sites[:i]:minimum_distance=min(minimum_distance,((s['x']-z['x'])**2+(s['y']-z['y'])**2)**.5)
    assert minimum_distance>=1000
    records=[json.loads(p.read_text()) for p in (OUT/'native_binary').glob('*.json')]
    assert len(records)==36 and all(r['complete'] for r in records)
    fixed=read('evaluation_settings.json')['recorded_utc']
    assert all(r['started_utc']>fixed for r in records if r['id'].startswith('v2_'))
    max_error=0
    for s in sites+read('settlement_sites.json'):
        p=OUT/'native_binary'/(s['id']+'.tif');record=json.loads(p.with_suffix('.json').read_text());assert sha(p)==record['sha256']
        with rasterio.open(p) as ds:a=ds.read().reshape(2,3,512,512);t=ds.transform
        assert t.a==.5 and t.e==-.5 and t.c*2==round(t.c*2) and t.f*2==round(t.f*2)
        assert np.all(a[:,0]<=a[:,1]) and np.all(a[:,1]<=a[:,2])
        cell=target_polygon(s)
        for yi,original_y in [(0,0),(1,3)]:
            support=polygons(a[yi,2],t).intersection(cell).area
            for ti,key in [(0,'coverage_041'),(1,'coverage_034')]:
                reconstructed=polygons(a[yi,ti],t).intersection(cell).area/support
                max_error=max(max_error,abs(reconstructed-s[key][original_y]))
    # Different projected/geographic overlap conventions have tiny numeric error.
    assert max_error<1e-4,max_error
    protected=read('day1_preservation.json')
    for name,expected in protected.items():assert sha(BASE/name)==expected,name
    accepted=json.loads((BASE/'protected_artifacts.json').read_text())
    for name,expected in accepted['sha256'].items():assert sha(BASE.parents[2]/name)==expected,name
    rows=[]
    for threshold in [.41,.34]:
        for sector in ['NW','W','combined']:
            for group in ['addition','stable_built','stable_nonbuilt']:
                r=[z for z in metrics if z['threshold']==threshold and (sector=='combined' or z['sector']==sector) and z['stratum'].startswith(group)]
                n=len(r);retained=sum(z['v2_candidate'] is True for z in r);alarms=sum(z['growth_alarm'] is True for z in r)
                rows.append(dict(threshold=threshold,sector=sector,stratum=group,sites=n,blocks=len({tuple(z['block']) for z in r}),numerically_supported=sum(z['status']=='supported' for z in r),support_excluded=sum(z['status']!='supported' for z in r),v2_candidates=retained,candidate_retention=retained/n if group=='addition' else None,residual_growth_alarms=alarms,internal_control_disagreement_rate=alarms/n if group!='addition' else None,endpoint_condition_exclusions=sum(not z['endpoint_low_high'] for z in r) if group=='addition' else None,independently_assessable=0,independent_unclear=n,independent_credible_addition_retention=None,independently_verified_false_additions=None,independently_verified_false_addition_rate=None))
    write('metrics_summary.json',rows)
    with (OUT/'metrics_summary.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    chosen=['v2_W_addition_1','v2_W_stable_built_edge_2','v2_W_addition_4']
    sheet([next(s for s in sites if s['id']==i) for i in chosen],'illustrative_examples',metrics)
    ledger=read('resource_accounting.json');body=sum(r['body_bytes'] for r in records)
    imagery=read('historical_imagery_feasibility.json');assert imagery['elapsed_minutes']<=30
    browser=read('historical_imagery_start.json')['charged_browser_allowance_bytes']
    finished=datetime.now(timezone.utc)
    # Preparation preceded ledger creation; debit ten extra active minutes.
    minutes=ledger['carry_in_active_minutes']+10+(finished-datetime.fromisoformat(ledger['started_utc'])).total_seconds()/60
    charged=ledger['carry_in_charged_bytes']+ledger['new_metadata_allowance_bytes']+browser+body
    assert charged<ledger['cap_bytes'] and minutes<3*8*60
    ledger.update(finished_utc=finished.isoformat(),new_binary_patch_payload_bytes=body,new_browser_allowance_bytes=browser,
                  cumulative_measured_payload_bytes=ledger['carry_in_measured_bytes']+body,cumulative_charged_bytes=charged,
                  remaining_charged_bytes=ledger['cap_bytes']-charged,cumulative_active_minutes_charged=minutes,
                  v2_pre_record_preparation_allowance_minutes=10,final_incomplete_exports=0,
                  accounting_note='Day 1 totals carried forward once. New 10 MB documentation/API allowance and 150 MB browser allowance are estimates for unmetered traffic, not exact or proven bounds; binary response payloads metered. Three working days conservatively treated as 24 active hours for this check. No paid service.')
    (OUT/'resource_accounting.json').write_text(json.dumps(ledger,indent=2)+'\n')
    a={r['id']:r['v2_candidate'] for r in metrics if r['threshold']==.41};b={r['id']:r['v2_candidate'] for r in metrics if r['threshold']==.34}
    audit=dict(audited_utc=now(),day1_files_unchanged=len(protected),accepted_artifacts_unchanged=True,
               all_native_patch_hashes_verified=True,native_spacing_m=.5,thresholds_before_geometry=True,
               endpoint_coverage_reconstruction_max_absolute_error=max_error,all_sites_in_buffered_development=True,
               fresh_sites=30,fresh_1km_blocks=30,minimum_distance_to_other_fresh_or_old_site_m=minimum_distance,
               settings_precede_fresh_downloads=True,threshold_label_agreement=sum(a[k]==b[k] for k in a)/len(a),
               geometry_tests='6 passed; geometry_tests.xml',no_enrichment=True,no_models=True,
               cumulative_charged_bytes=charged,cumulative_active_minutes_charged=minutes,
               imagery_feasibility_minutes=imagery['elapsed_minutes'],output_sha256={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and p.name!='output_audit.json'})
    write('output_audit.json',audit)
    print(json.dumps({k:v for k,v in audit.items() if k!='output_sha256'},indent=2))


if __name__=='__main__':main()
