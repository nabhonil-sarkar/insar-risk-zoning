import io
import json
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from scripts import coastal_inference as inf
from scripts import coastal_pilot_feasibility as f
from scripts import run_coastal_pilot as runner
from scripts.coastal_transport import Budget,Transport,GateError,metadata_fields,assemble
from scripts.coastal_validation import NodataContract


def response(status=206,body=b'1234',**headers):
    r=Mock(status_code=status,headers={'Content-Length':str(len(body)),'Content-Range':'bytes 0-3/10','ETag':'v1',**headers},raw=io.BytesIO(body))
    r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=False)
    return r


def test_budget_counts_attempts_and_deadline(tmp_path):
    now=[0.];b=Budget(100,10,tmp_path/'log',clock=lambda:now[0])
    b.reserve(90)
    with pytest.raises(GateError):b.reserve(11)
    b.reserve(10);now[0]=10
    with pytest.raises(GateError):b.check()


@pytest.mark.parametrize('status,headers',[(200,{}),(412,{}),(206,{'ETag':'v2'}),(206,{'Content-Range':'bytes 1-4/10'}),(206,{'Content-Length':'5'})])
def test_transport_refuses_body_before_read(tmp_path,status,headers):
    r=response(status,**headers);session=Mock();session.request.return_value=r
    t=Transport(Budget(1024**2,100,tmp_path/'log'),session)
    with pytest.raises(GateError):t.request('GET','https://example.invalid',length=4,expected=(0,4,10,'v1'))
    assert r.raw.tell()==0


def test_retry_accounting_and_same_range(tmp_path):
    session=Mock();session.request.side_effect=[response(503,**{'Retry-After':'0'}),response()]
    b=Budget(1024**2,100,tmp_path/'log');t=Transport(b,session,sleep=lambda _:None)
    raw,_=t.request('GET','https://example.invalid',length=4,expected=(0,4,10,'v1'),headers={'Range':'bytes=0-3','If-Match':'v1'})
    assert raw==b'1234' and b.reserved==2*(4+65536) and b.received==4
    assert session.request.call_args_list[0]==session.request.call_args_list[1]


def test_exhausted_retry_and_no_hidden_fallback(tmp_path):
    session=Mock();session.request.side_effect=[response(429,**{'Retry-After':'0'}) for _ in range(3)]
    b=Budget(1024**2,100,tmp_path/'log');t=Transport(b,session,sleep=lambda _:None)
    with pytest.raises(GateError):t.request('GET','https://example.invalid',length=4)
    assert session.request.call_count==3 and b.reserved==3*(4+65536)


def test_budget_fails_before_request(tmp_path):
    session=Mock();t=Transport(Budget(65536,100,tmp_path/'log'),session)
    with pytest.raises(GateError):t.request('GET','https://example.invalid',length=1)
    session.request.assert_not_called()


def test_partial_tiff_lossless_blocks_and_real_georeference():
    a=np.arange(64*64,dtype=np.uint16).reshape(64,64)
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',width=64,height=64,count=1,dtype='uint16',crs='EPSG:32748',
                      transform=from_origin(600000,9400000,20,20),nodata=0,tiled=True,blockxsize=16,blockysize=16,compress='deflate',predictor=2) as ds:ds.write(a,1)
        raw=mem.read()
    read=lambda off,n:raw[off:off+n]
    fields=metadata_fields(read);layout=f.tiff_layout(read)
    tiles={i:read(layout['offsets'][i],layout['bytecounts'][i]) for i in [0,1,4,5]}
    packed=assemble(fields,tiles)
    with MemoryFile(packed) as mem:
        with mem.open() as ds:
            assert ds.crs.to_epsg()==32748
            np.testing.assert_array_equal(ds.read(1,window=rasterio.windows.Window(0,0,32,32)),a[:32,:32])
            assert ds.read(1,window=rasterio.windows.Window(32,32,32,32)).sum()==0
    item={'id':'synthetic','assets':{'B11':{'href':'synthetic','proj:shape':[64,64],'proj:transform':[20,0,600000,0,-20,9400000]}}}
    contract=NodataContract('synthetic','B11','synthetic','synthetic','synthetic')
    runner.verify_native(assemble(fields,{}),item,'B11',contract)
    item['assets']['B11']['proj:transform'][0]=10
    with pytest.raises(GateError):runner.verify_native(packed,item,'B11',contract)


@pytest.mark.parametrize('n,den,gate,expected',[(1999,2500,.8,False),(2000,2500,.8,True),(1749,2500,.7,False),(1750,2500,.7,True),(89,100,.9,False),(90,100,.9,True),(94,100,.95,False),(95,100,.95,True),(0,0,.8,False)])
def test_gate_boundaries(n,den,gate,expected):
    assert inf.fraction_gate(n,den,gate)==expected


def test_geodesic_area_not_nominal_30m():
    a=inf.cell_areas([673000,9317000,674000,9318000])
    assert a.shape==(50,50) and np.all((a>395)&(a<405))
    assert 990000<a.sum()<1010000 and a.sum()!=2500*900


def test_coverage_all_cloud_unknown_and_core_support():
    dates=['2020-01-01','2020-01-20','2020-02-01','2020-02-20','2020-03-01','2020-03-20','2020-04-01','2020-04-20']
    def observation(q):return {'B03':np.full((66,66),.1),'B11':np.full((66,66),.3),'SCL':np.full((66,66),q)}
    window={'id':'C1','core_bounds_utm':[673000,9317000,674000,9318000]}
    rows,arrays=inf.coverage_batch(dates,{'C1':[observation(9)]*8},[window])
    assert all(r['supported_cells']==0 and not r['support_gate_pass'] for r in rows)
    rows,_=inf.coverage_batch(dates,{'C1':[observation(4)]*8},[window])
    assert all(r['supported_cells']==2500 and r['support_gate_pass'] for r in rows)
    allrows=inf.all_coverage_rows(rows,[{'id':'C1'}],[{'year':2020,'season':'Jan-Apr','dates':dates},{'year':2021,'season':'Jan-Apr','dates':dates}])
    assert allrows[-1]['supported_cells'] is None and allrows[-1]['status']=='not_acquired_after_stop'


def test_synthetic_pipeline_persistent_transition(tmp_path):
    seasons=[];observations={}
    for year in range(2020,2026):
        for name,months in [('Jan-Apr',[1,2,3,4]),('Jun-Sep',[6,7,8,9])]:
            dates=[f'{year}-{m:02}-{d:02}' for m in months for d in (1,20)]
            seasons.append(dict(year=year,season=name,dates=dates))
            for d in dates:
                observations[d]={'C1':dict(B03=np.full((66,66),.3 if year>=2023 else .1),B11=np.full((66,66),.1 if year>=2023 else .3),SCL=np.full((66,66),4))}
    windows=[dict(id='C1',role='coastal_mixed',core_bounds_utm=[673000,9317000,674000,9318000])]
    annual,final,gates=inf.classify(observations,windows,seasons,{},tmp_path)
    assert all((a==3).all() for a in final['C1'].values())
    assert all(g['passed'] for g in gates)
    assert all(a['land_to_water_m2']>990000 and a['water_to_land_m2']==0 for a in json.loads((tmp_path/'areas.json').read_bytes()))


def test_control_unknown_and_empty_robustness_fail():
    primary=inf.scenario_id(0,60);alt=inf.scenario_id(.05,120)
    annual={'W1':{sid:np.ones((6,10,10),int) for sid in (primary,alt)}}
    final={'W1':{primary:np.ones((10,10),int),alt:np.ones((10,10),int)}}
    final['W1'][alt].ravel()[:6]=-1
    gates=inf.final_gates(annual,final,{'W1':(np.ones((10,10),bool),1)})
    assert not next(g['passed'] for g in gates if g['gate']=='control' and g['scenario']==alt)
    final['W1'][primary][:]=-1
    gates=inf.final_gates(annual,final,{})
    assert not next(g['passed'] for g in gates if g['gate']=='robustness')


def test_wrong_protocol_or_approval_stops_before_any_network(tmp_path,monkeypatch):
    (tmp_path/'protocol.json').write_text('{}')
    network=Mock();monkeypatch.setattr(runner,'Transport',network)
    with pytest.raises(GateError,match='Hash mismatch'):runner.preflight(tmp_path,tmp_path)
    network.assert_not_called()
    monkeypatch.setattr(runner,'PROTOCOL_SHA',f.digest(tmp_path/'protocol.json'))
    (tmp_path/'approval.json').write_text('{}')
    with pytest.raises(GateError,match='Hash mismatch'):runner.preflight(tmp_path,tmp_path)
    network.assert_not_called()


def test_native_preflight_etag_failure_before_payload():
    t=Mock();t.head.side_effect=GateError('ETag changed')
    item={'id':'synthetic','assets':{'B11':{'href':'synthetic'}}}
    contract=NodataContract('synthetic','B11','synthetic','synthetic','synthetic')
    with pytest.raises(GateError):runner.inspect_native((item,{'asset':'B11'},contract),t)
    t.head.assert_called_once()
    t.read.assert_not_called()


@pytest.mark.parametrize('case',['disk','dirty','tests','methodology','code'])
def test_local_execution_prerequisites_fail_closed(tmp_path,monkeypatch,case):
    protocol={'evidence_sha256':{},'preparation_code_sha256':{}}
    approval=dict(protocol_sha256='sha',approved=True,total_acquisition_ceiling_bytes=runner.CEILING,minimum_free_disk_bytes=7*1024**3,acquisition_wall_seconds=7200)
    required=['scripts/run_coastal_pilot.py','scripts/coastal_transport.py','scripts/coastal_inference.py','scripts/coastal_validation.py','tests/test_coastal_execution.py','tests/test_coastal_nodata.py','docs/InSAR_Subsidence_Risk_Zoning_Methodology.docx']
    verification=dict(failed=1 if case=='tests' else 0,skipped=0,passed=263,protocol_sha256='sha',methodology_render_reviewed=case!='methodology',executing_file_sha256={k:'bad' if case=='code' else 'sha' for k in required})
    (tmp_path/'execution_verification.json').write_text(json.dumps(verification))
    monkeypatch.setattr(runner,'checked',lambda p,sha:protocol if p.name=='protocol.json' else approval)
    monkeypatch.setattr(runner,'PROTOCOL_SHA','sha');monkeypatch.setattr(runner,'FIXED',{})
    monkeypatch.setattr(f,'digest',lambda _: 'sha');monkeypatch.setattr(f,'WC_SHA','sha')
    def commit(root):
        if case=='dirty':raise GateError('dirty')
        return 'clean'
    network=Mock();monkeypatch.setattr(runner,'Transport',network)
    with pytest.raises(GateError):runner.preflight(tmp_path,tmp_path,free_bytes=0 if case=='disk' else 7*1024**3,commit_fn=commit)
    network.assert_not_called()


def test_no_new_requests_after_a_concurrent_gate_failure(tmp_path):
    b=Budget(1024**2,100,tmp_path/'log');b.stop('ETag failed')
    session=Mock();t=Transport(b,session)
    with pytest.raises(GateError):t.request('GET','https://example.invalid',length=4)
    session.request.assert_not_called()


def test_existing_run_is_never_overwritten(tmp_path,monkeypatch):
    (tmp_path/'run').mkdir();(tmp_path/'run'/'sentinel').write_text('keep')
    monkeypatch.setattr(runner,'preflight',lambda *a,**kw:({}, {}, {}, {}, 'commit'))
    with pytest.raises(FileExistsError):runner.run(tmp_path,tmp_path)
    assert (tmp_path/'run'/'sentinel').read_text()=='keep'
