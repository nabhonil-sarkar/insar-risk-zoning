import json
from unittest.mock import Mock

import pytest

from scripts import coastal_restart as restart
from scripts import run_coastal_pilot as runner
from scripts.coastal_transport import Budget, Transport, GateError
from scripts.coastal_validation import ValidationError
from tests.test_coastal_nodata import fixture


def approval_fixture(tmp_path,monkeypatch):
    d=tmp_path/restart.RECORDS;d.mkdir()
    (tmp_path/'run').mkdir();(tmp_path/'run'/'sentinel').write_text('original evidence')
    prior=d/'prior_evidence.json'
    prior.write_text(json.dumps({'files_sha256':{'run/sentinel':restart.digest(tmp_path/'run'/'sentinel')}}))
    a=dict(approved=True,attempt=restart.ATTEMPT,protocol_sha256=runner.PROTOCOL_SHA,
        total_acquisition_ceiling_bytes=3*1024**3,minimum_free_disk_bytes=7*1024**3,
        acquisition_wall_seconds=7200,prior_reserved_bytes=restart.PRIOR_BYTES,prior_elapsed_seconds=60,
        remaining_transfer_bytes=2948670514,remaining_acquisition_seconds=7140,
        prior_charges=dict(stopped_run=3377970,diagnosis=741532,preparation=268435456),
        prior_evidence_sha256=restart.digest(prior),no_push=True,no_scale_up=True,no_phase_c=True)
    (d/'approval.json').write_text(json.dumps(a))
    monkeypatch.setattr(restart,'APPROVAL_SHA',restart.digest(d/'approval.json'))
    return d,a


def test_carried_budget_exact_remaining_and_deadline(tmp_path):
    now=[100.]
    b=Budget(3*1024**3,7200,tmp_path/'log',clock=lambda:now[0],
             prior_reserved=restart.PRIOR_BYTES,prior_seconds=60)
    assert b.ceiling-b.reserved==2948670514
    b.reserve(2948670514)
    session=Mock();t=Transport(b,session)
    with pytest.raises(GateError):t.request('GET','https://example.invalid',length=1)
    session.request.assert_not_called()
    b.record({'synthetic':True},received=4)
    record=json.loads((tmp_path/'log').read_text())
    assert record['cumulative_reserved_bytes']==3*1024**3
    assert record['attempt_reserved_bytes']==2948670514 and record['prior_reserved_bytes']==restart.PRIOR_BYTES
    assert record['elapsed_seconds']==60 and record['attempt_elapsed_seconds']==0
    now[0]=100+7140
    with pytest.raises(GateError,match='limit'):b.check()


@pytest.mark.parametrize('prior_bytes,prior_seconds',[(-1,0),(100,0),(1.5,0),(0,-1),(0,10),(0,float('nan'))])
def test_invalid_carried_budget_creates_no_log(tmp_path,prior_bytes,prior_seconds):
    with pytest.raises(GateError):Budget(100,10,tmp_path/'log',prior_reserved=prior_bytes,prior_seconds=prior_seconds)
    assert not (tmp_path/'log').exists()


@pytest.mark.parametrize('case',['approval_hash','limits','debits','prior_registry','prior_file','existing_attempt','wrong_attempt'])
def test_restart_failures_precede_network(tmp_path,monkeypatch,case):
    d,a=approval_fixture(tmp_path,monkeypatch)
    if case=='approval_hash':(d/'approval.json').write_text('{}')
    elif case in ('limits','debits'):
        if case=='limits':a['prior_reserved_bytes']=0
        else:a['prior_charges']['preparation']=0
        (d/'approval.json').write_text(json.dumps(a))
        monkeypatch.setattr(restart,'APPROVAL_SHA',restart.digest(d/'approval.json'))
    elif case=='prior_registry':(d/'prior_evidence.json').write_text('{}')
    elif case=='prior_file':(tmp_path/'run'/'sentinel').write_text('changed')
    elif case=='existing_attempt':(tmp_path/restart.ATTEMPT).mkdir()
    network=Mock();monkeypatch.setattr(runner,'Transport',network)
    with pytest.raises(GateError):runner.run(tmp_path,tmp_path,attempt='../escape' if case=='wrong_attempt' else restart.ATTEMPT)
    network.assert_not_called()
    assert not (tmp_path/restart.ATTEMPT/'transfer.jsonl').exists()


@pytest.mark.parametrize('case',['approval','report_hash','failures','errors','skipped','count'])
def test_restart_verification_fail_closed(tmp_path,case):
    attrs=dict(tests='305',failures='0',errors='0',skipped='0')
    if case in attrs:attrs[case]='1'
    if case=='count':attrs['tests']='304'
    path=tmp_path/'tests.xml'
    path.write_text('<testsuites><testsuite '+ ' '.join(f'{k}="{v}"' for k,v in attrs.items())+'/></testsuites>')
    v=dict(restart_approval_sha256=restart.APPROVAL_SHA,tests_xml_sha256=restart.digest(path),passed=305)
    if case=='approval':v['restart_approval_sha256']='wrong'
    if case=='report_hash':v['tests_xml_sha256']='wrong'
    with pytest.raises(GateError):restart.verify_tests(tmp_path,v)


def test_native_failure_in_restart_preserves_original_and_never_acquires(tmp_path,monkeypatch):
    d,a=approval_fixture(tmp_path,monkeypatch)
    (d/'execution_verification.json').write_text('{}')
    item,scene,xml=fixture();item['properties']={'datetime':'2020-01-15T00:00:00Z'}
    # Fixture item gained a datetime: update only its synthetic pinned checksum.
    import hashlib
    scene['item_metadata_sha256']=hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()
    cache=tmp_path/'pc_header_cache';cache.mkdir();(cache/(item['id']+'.xml')).write_bytes(xml)
    protocol={'observations':{'actual_dates_and_baselines':[]}}
    monkeypatch.setattr(runner,'preflight',lambda *args,**kw:(protocol,{'windows':[]},{'selected_items':[item]},{'scenes':[scene]},'clean'))
    monkeypatch.setattr(runner,'FIXED',{})
    monkeypatch.setattr(runner.inf,'all_coverage_rows',lambda *args:[])
    monkeypatch.setattr(runner.inf,'save_coverage',lambda *args:None)
    failure=ValidationError(item,'B03','native_tiff',{'tiff_nodata':[None,0]},{'tiff_nodata':65535})
    monkeypatch.setattr(runner,'inspect_native',Mock(side_effect=failure))
    blocks=Mock();monkeypatch.setattr(runner,'acquire_scene',blocks)
    network=Mock();monkeypatch.setattr(runner,'Transport',network)
    result=runner.run(tmp_path,tmp_path,attempt=restart.ATTEMPT)
    blocks.assert_not_called();network.return_value.read.assert_not_called()
    assert result['status']=='STOP_EXECUTION_GATE' and result['total_reserved_bytes']==restart.PRIOR_BYTES
    assert result['attempt_reserved_bytes']==0 and result['validation_failure']['asset']=='B03'
    assert (tmp_path/'run'/'sentinel').read_text()=='original evidence'
    assert list((d/'validation_failures').glob('validation_failure_*.json'))
    assert (tmp_path/restart.ATTEMPT/'output_audit.json').exists()
    with pytest.raises(GateError,match='already exists'):runner.run(tmp_path,tmp_path,attempt=restart.ATTEMPT)
