"""Reconcile Day 1 outputs, resource accounting, and preserved evidence."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import numpy as np
from scripts.building_change_explore.analyse import OUT


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    verify=json.loads((OUT/'input_verification.json').read_text())
    for path,expected in verify['input_sha256'].items():assert sha(path)==expected,path
    protected=json.loads((OUT/'protected_artifacts.json').read_text())
    root=OUT.parents[2]
    for path,expected in protected['sha256'].items():assert sha(root/path)==expected,path
    local=np.load(OUT/'local_arrays.npz');ref=np.load(OUT/'reference_fractions.npy')
    assert ref.shape==(4,3,1312,953) and np.isfinite(ref).all()
    for end in (2023,2025):assert not np.any(local[f'hot_{end}_1']&~local[f'hot_{end}_5'])
    enrichment_done=(OUT/'enrichment_metrics.json').exists()
    if enrichment_done:
        rows=json.loads((OUT/'enrichment_metrics.json').read_text());assert len(rows)==144
        keys=['baseline_cells','original_extreme_cells','eligible_cells','addition_cells','eligible_extreme_cells','addition_extreme_cells','endpoint_missing_support','endpoint_ambiguous','additional_2021_missing_support','additional_2021_ambiguous']
        for row in rows:
            if row['surface']=='combined':
                strata=[r for r in rows if all(r[k]==row[k] for k in ['threshold','rule','sector','period','top_percent']) and r['surface'] in ['land','water']]
                assert len(strata)==2
                for k in keys:assert row[k]==sum(r[k] for r in strata),(k,row)
            e,a,x,ax=(row[k] for k in ['eligible_cells','addition_cells','eligible_extreme_cells','addition_extreme_cells'])
            if e:assert row['addition_prevalence']==a/e
            if x:assert row['extreme_addition_prevalence']==ax/x
            if a and x:assert np.isclose(row['enrichment'],(ax/x)/(a/e))
    for name,keys,group in [
        ('reference_candidate_metrics.json',['baseline_cells','eligible_cells','endpoint_missing_support','endpoint_ambiguous','additional_2021_missing_support','additional_2021_ambiguous','candidate_addition_cells'],['threshold','rule','sector']),
        ('extreme_support_only.json',['original_extreme_cells','eligible_extreme_cells','extremes_missing_support','extremes_ambiguous','additional_2021_extremes_missing_support','additional_2021_extremes_ambiguous'],['threshold','rule','sector','period','top_percent'])]:
        rows=json.loads((OUT/name).read_text())
        for row in rows:
            if row['surface']=='combined':
                strata=[r for r in rows if r['surface'] in ['land','water'] and all(r[k]==row[k] for k in group)]
                assert len(strata)==2
                for k in keys:assert row[k]==sum(r[k] for r in strata),(name,k,row)
            if name=='extreme_support_only.json':
                assert all(row[k] is None for k in ['addition_extreme_cells','extreme_addition_prevalence','enrichment','addition_capture_fraction'])
    samples=json.loads((OUT/'reference_sample.json').read_text())
    assert len(samples)==24
    for sample in samples:
        r,c=sample['row'],sample['col']
        assert local['split'][r,c]==1 and local['buffer_retained'][r,c]
    review=json.loads((OUT/'reference_review.json').read_text())
    assert not review['reference_usable'] and not enrichment_done
    ledger_path=OUT/'resource_accounting.json';ledger=json.loads(ledger_path.read_text())
    records=[]
    for folder in ['aggregation_probe','aggregation_probe_v2','aggregation_probe_v3','aggregation_tile_probe_v3','reference_chunks','reference_chunks_v4','inspection_windows','export_attempt_history']:
        for path in (OUT/folder).glob('*.json'):
            record=json.loads(path.read_text());records.append({'record_file':str(path.relative_to(OUT)),**record})
    metadata_bytes=sum(r['body_bytes'] for r in ledger['requests'])
    unique_attempts={(r.get('started_utc'),r.get('name',r.get('id'))):r for r in records}
    raster_bytes=sum(r.get('body_bytes',0) for r in unique_attempts.values())
    wheel_bytes=sum(p.stat().st_size for p in (OUT/'dependencies').glob('*.whl'))
    measured=metadata_bytes+raster_bytes+wheel_bytes
    allowance=ledger['unmetered_web_documentation_allowance_bytes']+ledger['package_index_and_auth_allowance_bytes']
    assert measured+allowance<ledger['cap_bytes']
    batches=json.loads((OUT/'batch_export_history.json').read_text())
    assert all(r['final_status']['state'] in ['FAILED','COMPLETED','CANCELLED'] for r in batches)
    end=datetime.now(timezone.utc);start=datetime.fromisoformat(ledger['active_session_2_started_utc'])
    active_minutes=45+(end-start).total_seconds()/60
    ledger.update(measured_metadata_body_bytes=metadata_bytes,measured_aggregate_and_inspection_body_bytes=raster_bytes,dependency_payload_bytes=wheel_bytes,measured_downloaded_payload_bytes_total=measured,accounting_allowance_bytes=allowance,charged_download_bytes_total=measured+allowance,remaining_charged_bytes=ledger['cap_bytes']-measured-allowance,final_years_complete=[2020,2021,2022,2023],final_grid_incomplete_exports=0,historical_failed_batch_exports=len([r for r in batches if r['final_status']['state']=='FAILED']),historical_incomplete_raster_attempts=[r['record_file'] for r in records if not r.get('complete')],active_effort_minutes_charged=active_minutes,effort_accounting='First active session charged 45 minutes including preparation allowance; second active session wall time from 08:24 UTC on 10 November. Overnight interruption excluded. This is conservative effort accounting, not a time-sheet measurement.',finished_utc=end.isoformat())
    ledger['allowance_note']='10 MB for unmetered web-tool documentation; 100 MB for initially unmetered package-index/auth/browser/Earth Engine metadata traffic. Allowances are explicit accounting estimates, not exact or proven upper bounds. All reference/inspection raster payloads are metered. No full-resolution reference raster downloaded.'
    ledger['measured_response_body_bytes']=metadata_bytes+raster_bytes
    ledger['exports_submitted']=[{'year':r['year'],'task_id':r['task_id'],'state':r['final_status']['state']} for r in batches]
    ledger['incomplete_batch_exports']=[r['task_id'] for r in batches if r['final_status']['state']!='COMPLETED']
    ledger['incomplete_exports']=ledger['historical_incomplete_raster_attempts']
    ledger_path.write_text(json.dumps(ledger,indent=2)+'\n')
    audit={'audited_utc':end.isoformat(),'input_hashes_unchanged':True,'accepted_artifact_hashes_unchanged':True,'four_year_grid_complete':True,'reference_support_land_water_counts_reconciled':True,'enrichment_land_water_counts_reconciled':True if enrichment_done else None,'ratio_denominators_reconciled':True if enrichment_done else None,'enrichment_computed':enrichment_done,'all_inspection_sites_in_buffered_development_split':True,'top1_subset_top5':True,'charged_download_bytes':measured+allowance,'measured_payload_bytes':measured,'allowance_bytes':allowance,'cap_bytes':ledger['cap_bytes'],'active_minutes_charged':active_minutes,'historical_batch_failures':len(batches),'remaining_running_batch_tasks':0,'day2_started':False,'output_sha256':{p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.suffix in ['.json','.csv','.png','.npy','.npz','.xml'] and p.name!='output_audit.json'}}
    (OUT/'output_audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    print(json.dumps({k:v for k,v in audit.items() if k!='output_sha256'},indent=2))


if __name__=='__main__':main()
