"""One approved, capped coastal pilot; stop at the first applicable failed gate."""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import traceback

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.windows import from_bounds

from scripts import coastal_pilot_feasibility as f
from scripts import coastal_pilot_pc as pc
from scripts import coastal_pilot_rules as rules
from scripts import coastal_inference as inf
from scripts import coastal_restart as restart
from scripts.coastal_transport import Budget, Transport, GateError, metadata_fields, assemble
from scripts.coastal_validation import ValidationError, xml_nodata_contract, require_contract, record_failure

PROTOCOL_SHA='4faf2430c6dbce50fb7e69cdcad9db819953bac6bb90edb2de4376cd38698754'
APPROVAL_SHA='f36011f420ee5e7fbb446af89934a41f29a8585a370cf5be7bd158f984d6c830'
CEILING=3*1024**3
FIXED={
    'docs/Nabhonil_Sarkar_Jakarta_Surface_Differences_2020-2025.pdf':'4ce2a0c85c99ab3780f2e994a4a5c917575244ba0af32ac7f1a039df11c8aa15',
    'data/output/alphaearth_seam_v2/results.json':'763bfa06a8f74e823a91b056c0c856f550f0d8cff4ce124c18c2238c1b82920b',
    'data/output/alphaearth_surface_type_v1/run/results.json':'b5a29d2710701e664160080291c6bc297c7b34617f7f315ae22769377b5de4b9'}


def checked(path,sha):
    if f.digest(path)!=sha:raise GateError(f'Hash mismatch: {path.name}')
    return json.loads(path.read_bytes())


def clean_commit(root):
    status=subprocess.check_output(['git','status','--porcelain','--untracked-files=all'],cwd=root,text=True)
    if status.strip():raise GateError('Executing checkout is not clean')
    return subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()


def preflight(root,out,free_bytes=None,commit_fn=clean_commit,failure_dir=None,attempt=None):
    # All local evidence and approval gates precede any network request.
    protocol=checked(out/'protocol.json',PROTOCOL_SHA)
    approval=checked(out/'approval.json',APPROVAL_SHA)
    if (approval.get('protocol_sha256')!=PROTOCOL_SHA or approval.get('approved') is not True
            or approval.get('total_acquisition_ceiling_bytes')!=CEILING
            or approval.get('minimum_free_disk_bytes')!=7*1024**3 or approval.get('acquisition_wall_seconds')!=7200):
        raise GateError('Approval limits mismatch')
    for name,sha in protocol['evidence_sha256'].items():
        if f.digest(out/name)!=sha:raise GateError('Frozen evidence changed: '+name)
    for name,sha in protocol['preparation_code_sha256'].items():
        if f.digest(root/name)!=sha:raise GateError('Frozen preparation code changed: '+name)
    for name,sha in FIXED.items():
        if f.digest(root/name)!=sha:raise GateError('Protected artifact changed')
    if f.digest(f.WC_PATH)!=f.WC_SHA:raise GateError('Baseline tile changed')
    verification_dir=out
    if attempt is not None:
        restart.contract(out,attempt,PROTOCOL_SHA)
        verification_dir=out/restart.RECORDS
    verification=json.loads((verification_dir/'execution_verification.json').read_bytes())
    if attempt is not None:restart.verify_tests(verification_dir,verification)
    if verification['failed']!=0 or verification['skipped']!=0 or verification['passed']<238:
        raise GateError('Full-suite verification missing/failed')
    if verification['protocol_sha256']!=PROTOCOL_SHA or not verification['methodology_render_reviewed']:
        raise GateError('Protocol/methodology verification missing')
    for name,sha in verification['executing_file_sha256'].items():
        if f.digest(root/name)!=sha:raise GateError('Code/document changed after tests: '+name)
    required={'scripts/run_coastal_pilot.py','scripts/coastal_transport.py','scripts/coastal_inference.py',
              'scripts/coastal_validation.py','tests/test_coastal_execution.py','tests/test_coastal_nodata.py',
              'docs/InSAR_Subsidence_Risk_Zoning_Methodology.docx'}
    if attempt is not None:required.update({'scripts/coastal_restart.py','tests/test_coastal_restart.py'})
    if not required<=verification['executing_file_sha256'].keys():raise GateError('Verification incomplete')
    commit=commit_fn(root)
    if (free_bytes if free_bytes is not None else shutil.disk_usage(out).free)<7*1024**3:
        raise GateError('Less than 7 GiB free disk before acquisition')
    geom=json.loads((out/'geometry.json').read_bytes())
    selection=json.loads((out/'pc_calibrated_selection.json').read_bytes())
    resources=json.loads((out/'pc_resources.json').read_bytes())
    by_id={i['id']:i for i in selection['selected_items']}
    if len(by_id)!=96 or len(resources['scenes'])!=96:raise GateError('Scene list changed')
    for scene in resources['scenes']:
        item=by_id[scene['item']];pc.contract(item)
        raw=(out/'pc_header_cache'/(scene['item']+'.xml')).read_bytes()
        for asset in scene['assets']:
            try:
                xml_nodata_contract(raw,item,scene,asset['asset'])
            except ValidationError as exc:
                if failure_dir is not None:record_failure(failure_dir,exc)
                raise
        if pc.radiometry(raw,item['properties']['s2:processing_baseline'])!=scene['radiometry']:
            raise GateError('Calibration mismatch')
    return protocol,geom,selection,resources,commit


def verify_native(data,item,key,nodata_contract):
    require_contract(nodata_contract,item,key)
    with MemoryFile(data) as mem:
        with mem.open() as ds:
            a=item['assets'][key]
            expected=dict(count=1,crs=32748,shape=a['proj:shape'],transform=a['proj:transform'],
                          datatype='uint8' if key=='SCL' else 'uint16',tiff_nodata=[None,0])
            actual=dict(count=ds.count,crs=ds.crs.to_epsg() if ds.crs else None,shape=list(ds.shape),
                        transform=list(ds.transform)[:6],datatype=ds.dtypes[0],tiff_nodata=ds.nodata)
            mismatches={k:v for k,v in expected.items() if (actual[k] not in (None,0) if k=='tiff_nodata' else actual[k]!=v)}
            if mismatches:
                raise ValidationError(item,key,'native_tiff',mismatches,{k:actual[k] for k in mismatches})
            return dict(actual,effective_nodata=0,product_xml_sha256=nodata_contract.xml_sha256,
                        product_xml_url=nodata_contract.xml_url)


def inspect_native(job,transport):
    item,asset,nodata_contract=job
    require_contract(nodata_contract,item,asset['asset'])
    transport.head(asset);reads=[];cache={}
    def read(off,n):
        if (off,n) not in cache:
            raw=transport.read(asset,off,n);cache[(off,n)]=raw
            reads.append(dict(offset=off,bytes=n,sha256=hashlib.sha256(raw).hexdigest()))
        return cache[(off,n)]
    # Match every previously registered header range before extra GeoTIFF fields.
    for off,n,sha in asset['metadata_ranges']:
        if hashlib.sha256(read(off,n)).hexdigest()!=sha:raise GateError('Registered header bytes changed')
    layout=f.tiff_layout(read)
    for tile in asset['required_tiles']:
        i=tile['index']
        if tile['offset']!=layout['offsets'][i] or tile['bytes']!=layout['bytecounts'][i]:raise GateError('Native tile range changed')
    fields=metadata_fields(read)
    if any(max(r['offset'],p)<min(r['offset']+r['bytes'],p+n) for r in reads for p,n in zip(layout['offsets'],layout['bytecounts'])):
        raise GateError('Header request overlaps native image data')
    try:
        validation=verify_native(assemble(fields,{}),item,asset['asset'],nodata_contract)
    except ValidationError as exc:
        exc.detail.update(etag=asset.get('etag'),metadata_ranges=reads)
        raise
    return dict(item=item['id'],asset=asset['asset'],fields=fields,ranges=reads,validation=validation)


def acquire_scene(scene,item,fields,transport,run,windows,nodata_contracts):
    # Even this lower-level entry point rejects wrong contracts before any blocks.
    for a in scene['assets']:require_contract(nodata_contracts[(scene['item'],a['asset'])],item,a['asset'])
    outputs={w['id']:{} for w in windows};evidence=[]
    dest=run/'acquired'/scene['item'];dest.mkdir(parents=True,exist_ok=False)
    for asset in scene['assets']:
        key=asset['asset'];blocks={};ranges=[]
        for tile in asset['required_tiles']:
            raw=transport.read(asset,tile['offset'],tile['bytes'])
            blocks[tile['index']]=raw
            ranges.append(dict(tile,sha256=hashlib.sha256(raw).hexdigest()))
        packed=assemble(fields[(scene['item'],key)]['fields'],blocks)
        path=dest/(key+'.partial.tif')
        with path.open('xb') as stream:stream.write(packed)
        verify_native(packed,item,key,nodata_contracts[(scene['item'],key)])
        with MemoryFile(packed) as mem:
            with mem.open() as ds:
                for w in windows:
                    win=from_bounds(*w['read_bounds_utm'],ds.transform)
                    if any(abs(v-round(v))>1e-8 for v in (win.col_off,win.row_off,win.width,win.height)):
                        raise GateError('Read grid not aligned')
                    dn=ds.read(1,window=win)
                    if key=='SCL':
                        if dn.shape!=(66,66) or not np.isin(dn,range(12)).all():raise GateError('Invalid native SCL')
                        outputs[w['id']][key]=dn
                    else:
                        rho=rules.reflectance(dn,scene['radiometry']['band_offsets'][key])
                        outputs[w['id']][key+'_native']=rho
                        outputs[w['id']][key]=rules.mean_2x2(rho) if key!='B11' else rho
        evidence.append(dict(asset=key,etag=asset['etag'],unsigned_url=asset['url'],ranges=ranges,
                             partial_file_sha256=f.digest(path),partial_file=str(path.relative_to(run))))
    f.write_new(dest/'manifest.json',dict(item=scene['item'],datetime=item['properties']['datetime'],
                baseline=item['properties']['s2:processing_baseline'],platform=item['properties']['platform'],assets=evidence))
    with (dest/'window_arrays.npz').open('xb') as stream:
        np.savez_compressed(stream,**{wid+'_'+k:v for wid,a in outputs.items() for k,v in a.items()})
    return outputs


def baseline_controls(geom):
    controls={}
    # Repeat only local baseline sampling; no embedding/seam analysis.
    for w in geom['windows']:
        if w['id'] not in ('L1','W1'):continue
        left,bottom,right,top=w['core_bounds_utm']
        x,y=np.meshgrid(np.arange(left,right,20)+10,np.arange(top,bottom,-20)-10)
        with rasterio.open(f.WC_PATH) as ds:wc,_,_=f.sample_cover(ds,x,y)
        # W1 was 100% connected sea in the frozen design; all WC water cells
        # therefore match its baseline eligible sea-proxy support.
        if w['id']=='W1' and w['sea_fraction']!=1:raise GateError('Water-control proxy reconstruction not supported')
        mask=wc==80 if w['id']=='W1' else np.isin(wc,[10,20,30,40,50,60,70,90,95,100])
        controls[w['id']]=(mask,1 if w['id']=='W1' else 0)
    return controls


def run(root=f.ROOT,out=f.OUT,attempt=None):
    carried=restart.contract(out,attempt,PROTOCOL_SHA) if attempt is not None else {}
    verification_dir=out/restart.RECORDS if attempt is not None else out
    # A separate append-only failure area preserves local preflight details too.
    failure_dir=verification_dir/'validation_failures';failure_dir.mkdir(exist_ok=True)
    protocol,geom,selection,resources,commit=preflight(root,out,failure_dir=failure_dir,attempt=attempt)
    run=out/(attempt or 'run');run.mkdir(exist_ok=False)
    f.write_new(run/'execution.json',dict(protocol_sha256=PROTOCOL_SHA,approval_sha256=APPROVAL_SHA,
        restart_approval_sha256=restart.APPROVAL_SHA if attempt else None,attempt=attempt or 'run',
        prior_reserved_bytes=carried.get('prior_reserved_bytes',0),prior_elapsed_seconds=carried.get('prior_elapsed_seconds',0),
        commit=commit,verification_sha256=f.digest(verification_dir/'execution_verification.json'),free_disk_bytes=shutil.disk_usage(out).free))
    budget=Budget(CEILING,7200,run/'transfer.jsonl',prior_reserved=carried.get('prior_reserved_bytes',0),
                  prior_seconds=carried.get('prior_elapsed_seconds',0));transport=Transport(budget)
    measured=[];support_arrays={};observations={};fields={};result={}
    by_id={i['id']:i for i in selection['selected_items']}
    scenes={s['item']:s for s in resources['scenes']}
    date_item={i['properties']['datetime'][:10]:i for i in selection['selected_items']}
    nodata_contracts={}
    for scene in resources['scenes']:
        raw=(out/'pc_header_cache'/(scene['item']+'.xml')).read_bytes()
        for asset in scene['assets']:
            nodata_contracts[(scene['item'],asset['asset'])]=xml_nodata_contract(raw,by_id[scene['item']],scene,asset['asset'])
    def guarded(function,*args):
        try:
            budget.check()
            return function(*args)
        except Exception as exc:
            if isinstance(exc,ValidationError):record_failure(failure_dir,exc)
            budget.stop(str(exc) if isinstance(exc,GateError) else type(exc).__name__)
            raise
    try:
        jobs=[(by_id[s['item']],a,nodata_contracts[(s['item'],a['asset'])]) for s in resources['scenes'] for a in s['assets']]
        # Verify every source's version AND actual geometry before ANY pixels.
        with ThreadPoolExecutor(max_workers=6) as pool:
            for n,record in enumerate(pool.map(lambda job:guarded(inspect_native,job,transport),jobs),1):
                fields[(record['item'],record['asset'])]=record
                if n%48==0:print(f'Preflight native metadata {n}/576; no pixels',flush=True)
        f.write_new(run/'native_metadata.json',list(fields.values()))
        for season in protocol['observations']['actual_dates_and_baselines']:
            budget.check();dates=season['dates'];batch={w['id']:[] for w in geom['windows']}
            # Date order is fixed; parallelism affects delivery only.
            with ThreadPoolExecutor(max_workers=6) as pool:
                pending=[pool.submit(guarded,acquire_scene,scenes[date_item[d]['id']],date_item[d],fields,transport,run,geom['windows'],nodata_contracts) for d in dates]
                for d,future in zip(dates,pending):
                    observed=future.result();observations[d]=observed
                    for wid,a in observed.items():batch[wid].append(a)
            rows,arrays=inf.coverage_batch(dates,batch,geom['windows']);measured.extend(rows)
            for k,v in arrays.items():support_arrays[f"{season['year']}_{season['season']}_{k}"]=v
            f.write_new(run/f"coverage_{season['year']}_{season['season']}.json",rows)
            print(f"Coverage {season['year']} {season['season']}: "+', '.join(f"{r['window']}/{r['buffer_m']}m={r['support_fraction']:.1%}" for r in rows),flush=True)
            if not all(r['support_gate_pass'] for r in rows):
                result=dict(status='STOP_TEMPORAL_SUPPORT',failed_rows=[r for r in rows if not r['support_gate_pass']],
                            transitions_inferred=False,reason='Frozen >=80% support gate failed; later dates not acquired; no transition classification or replacement.')
                break
        if not result:
            annual,final,gates=inf.classify(observations,geom['windows'],protocol['observations']['actual_dates_and_baselines'],baseline_controls(geom),run)
            failed=[g for g in gates if g['passed'] is False]
            result=dict(status='STOP_INTERPRETATION_GATE' if failed else 'BOUNDED_PILOT_OWNER_REVIEW',failed_gates=failed,transitions_inferred=True,scale_up_authorized=False)
            inf.deliver_states(annual,final,geom['windows'],observations,date_item,run,include_examples=not failed)
    except Exception as exc:
        # Never expose signed URLs from request exceptions in the audit.
        message=budget.stop_reason or (str(exc) if isinstance(exc,GateError) else type(exc).__name__)
        result=dict(status='STOP_EXECUTION_GATE',reason=message,transitions_inferred=False,
                    error_type=type(exc).__name__,acquired_complete_dates=sorted(observations))
        if isinstance(exc,ValidationError):result['validation_failure']=exc.detail
        print('Stopped:',message,flush=True)
    finally:
        rows=inf.all_coverage_rows(measured,geom['windows'],protocol['observations']['actual_dates_and_baselines'])
        inf.save_coverage(run,rows,support_arrays)
        result.update(protocol_sha256=PROTOCOL_SHA,commit=commit,acquired_complete_dates=sorted(observations),
                      body_bytes_received=budget.received,total_reserved_bytes=budget.reserved,
                      acquisition_elapsed_seconds=budget.clock()-budget.start,ceiling_bytes=CEILING,
                      prior_reserved_bytes=budget.prior_reserved,prior_elapsed_seconds=budget.prior_seconds,
                      attempt_reserved_bytes=budget.reserved-budget.prior_reserved,
                      attempt_elapsed_seconds=budget.clock()-budget.attempt_start,
                      restart_approval_sha256=restart.APPROVAL_SHA if attempt else None,
                      immutable_inputs_unchanged=all(f.digest(root/name)==sha for name,sha in FIXED.items()),
                      no_scale_up=True,no_phase_c=True)
        f.write_new(run/'results.json',result)
        manifest={str(p.relative_to(run)).replace('\\','/'):f.digest(p) for p in sorted(run.rglob('*')) if p.is_file()}
        f.write_new(run/'output_audit.json',dict(files_sha256=manifest))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt',choices=[restart.ATTEMPT])
    args=parser.parse_args()
    print(json.dumps(run(attempt=args.attempt),indent=2))
