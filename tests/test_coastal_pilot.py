import struct
from unittest.mock import Mock

import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from scripts import coastal_pilot_feasibility as f
from scripts import coastal_pilot_pc as pc
from scripts import coastal_pilot_rules as r


def xml(pb, offsets=True, quant=10000):
    off = ''.join(f'<BOA_ADD_OFFSET band_id="{i}">-1000</BOA_ADD_OFFSET>' for i in (1,2,3,7,11)) if offsets else ''
    return f'<root><PROCESSING_BASELINE>{pb}</PROCESSING_BASELINE><BOA_QUANTIFICATION_VALUE>{quant}</BOA_QUANTIFICATION_VALUE>{off}</root>'.encode()


@pytest.mark.parametrize('pb,offset', [('02.12',0),('03.00',0),('04.00',-1000),('05.11',-1000)])
def test_calibration(pb, offset):
    assert pc.radiometry(xml(pb, offset != 0), pb)['band_offsets']['B03'] == offset
    assert np.isnan(r.reflectance(np.array([0],dtype='uint16'), offset)[0])
    assert r.reflectance(np.array([2000-offset],dtype='uint16'),offset)[0] == .2


@pytest.mark.parametrize('raw,pb', [(xml('05.11',False),'05.11'),(xml('02.12'),'02.12'),(xml('05.11'),'04.00'),(xml('05.11',quant=1),'05.11')])
def test_bad_radiometry(raw,pb):
    with pytest.raises(ValueError):pc.radiometry(raw,pb)


@pytest.mark.parametrize('big', [False,True])
def test_header_parser_and_union(big):
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',width=64,height=64,count=1,dtype='uint16',transform=from_origin(100,100,1,1),tiled=True,blockxsize=16,blockysize=16,BIGTIFF='YES' if big else 'NO') as ds:
            ds.write(np.ones((1,64,64),dtype='uint16'))
        data=mem.read()
    layout=f.tiff_layout(lambda o,n:data[o:o+n])
    assert layout['width']==64 and len(layout['offsets'])==16
    win={'read_bounds_utm':[0,32,32,64]}
    assert f.block_ids(layout,[1,0,0,0,-1,64],[win,win])==[0,1,4,5]
    with pytest.raises(ValueError):f.block_ids(layout,[1,0,0,0,-1,64],[{'read_bounds_utm':[-1,0,64,64]}])


def test_invalid_tiff():
    with pytest.raises(ValueError):f.tiff_layout(lambda o,n:b'XX'+b'\0'*6)
    with pytest.raises(ValueError):f.tiff_layout(lambda o,n:b'II'+struct.pack('<HI',42,8) if o==0 else b'\xff\xff')


@pytest.mark.parametrize('status,etag,content_range',[(200,'v1','bytes 0-7/100'),(206,'v2','bytes 0-7/100'),(206,'v1','bytes 1-8/100')])
def test_refuse_full_object_or_changed_range(monkeypatch,status,etag,content_range):
    raw=Mock();response=Mock(status_code=status,headers={'ETag':etag,'Content-Range':content_range,'Content-Length':'8'},raw=raw)
    response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    session=Mock();session.head.return_value=Mock(headers={'ETag':'v1','Content-Length':'100','Accept-Ranges':'bytes'})
    session.get.return_value=response
    monkeypatch.setattr(f.requests,'Session',lambda:session)
    reader=f.HeaderReader('https://example.invalid/a')
    with pytest.raises(ValueError):reader.read(0,8)
    raw.read.assert_not_called()
    with pytest.raises(ValueError):reader.read(0,101)


def test_shoreline_cloud_and_sensitivity():
    g=np.full((31,31),.3);s=np.full_like(g,.1);scl=np.full(g.shape,6)
    clear,state=r.date_states(g,s,scl)
    assert state[15,15]==1 and state[0,0]==-1
    scl[15,15]=9
    clear,state=r.date_states(g,s,scl)
    assert not clear[15,18] and clear[15,19] and state[15,19]==-1
    clear_strict,_=r.date_states(g,s,scl,buffer_m=120)
    assert not clear_strict[15,21]
    _,state=r.date_states(np.full_like(g,.105),np.full_like(g,.095),np.full(g.shape,6))
    assert (state==-1).all()
    scl[1,1]=12
    with pytest.raises(ValueError):r.date_states(g,s,scl)


def test_native_nodata_propagates():
    a=np.ones((4,4));a[0,0]=np.nan
    b=r.mean_2x2(a)
    assert np.isnan(b[0,0]) and b[1,1]==1


def test_season_support_and_ambiguous_denominator():
    dates=['2020-01-01','2020-02-01','2020-03-05','2020-04-01','2020-04-15']
    clear=np.ones((5,3),bool);state=np.ones((5,3),dtype=int)
    clear[1:,1]=False;state[1:,1]=-1;state[:2,2]=-1
    support,classes=r.season_state(dates,clear,state)
    assert support.tolist()==[True,False,True]
    assert classes.tolist()==[1,-1,-1]
    state[0,0]=-1
    assert r.season_state(dates,clear,state)[1][0]==1
    with pytest.raises(ValueError):r.season_state([dates[0]]*5,clear,state)


def test_inadequate_months_span_and_empty():
    for dates in [['2020-01-01','2020-01-15','2020-04-01'],['2020-01-31','2020-02-15','2020-03-01']]:
        support,_=r.season_state(dates,np.ones((3,1),bool),np.ones((3,1),int))
        assert not support[0]
    support,state=r.season_state(['2020-01-01'],np.zeros((1,1),bool),np.full((1,1),-1))
    assert not support[0] and state[0]==-1


def test_persistence_transient_missing_and_edges():
    histories=np.array([[0,0,0,1,1,1],[1,1,0,0,0,0],[0,1,0,0,0,0],[0,1,1,1,1,1],[1,1,1,1,1,1],[0,0,-1,1,1,1]]).T
    assert r.persistence(histories).tolist()==[3,2,-2,-3,1,-1]
    assert r.annual_state([0,1,-1],[1,1,0]).tolist()==[-1,1,-1]
    with pytest.raises(ValueError):r.persistence(histories[:5])


def test_no_geometry_replacement_and_no_overwrite(tmp_path):
    with pytest.raises(ValueError):f.choose_windows([])
    p=tmp_path/'evidence.json';f.write_new(p,{'x':1})
    with pytest.raises(FileExistsError):f.write_new(p,{'x':2})
    assert '1' in p.read_text()


def test_catalogue_selection_uses_metadata_and_keeps_empty_bins():
    polygon={'type':'Polygon','coordinates':[[[0,0],[2,0],[2,2],[0,2],[0,0]]]}
    def item(name,day,cloud):
        return dict(id=name,geometry=polygon,properties={'datetime':f'2020-01-{day:02}T00:00:00Z','eo:cloud_cover':cloud})
    items=[item('a',1,60),item('b',5,10),item('c',20,90)]
    chosen,bins=f.select_items(items,[{'read_polygon_lonlat':polygon['coordinates'][0]}],lambda _:None)
    assert [i['id'] for i in chosen]==['b','c']
    assert len(bins)==96 and sum(b['selected'] is None for b in bins)==94


def test_bad_asset_contract():
    with pytest.raises(ValueError):pc.contract({'properties':{'eo:cloud_cover':float('nan')}})
    with pytest.raises(ValueError):pc.contract({'properties':{'eo:cloud_cover':0,'proj:epsg':32748,'s2:processing_baseline':'99.00'}})


def test_signing_token_reused_per_container(monkeypatch):
    monkeypatch.setattr(pc,'TOKENS',{})
    href='https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/first.tif'
    get=Mock(return_value=Mock(json=lambda:{'href':href+'?public-test-token'}))
    monkeypatch.setattr(pc.requests,'get',get)
    assert pc.public_token(href)=='public-test-token'
    assert pc.public_token(href.replace('first','second'))=='public-test-token'
    assert get.call_count==1
