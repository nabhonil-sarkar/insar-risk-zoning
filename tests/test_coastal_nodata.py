"""Synthetic regressions: nodata provenance, native headers and pre-pixel stops."""

import hashlib
import json
from unittest.mock import Mock

import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from scripts import run_coastal_pilot as runner
from scripts import coastal_pilot_feasibility as f
from scripts import coastal_pilot_rules as rules
from scripts.coastal_validation import ValidationError,xml_nodata_contract,record_failure


def fixture(key='B03',xml_edit=lambda s:s):
    product='S2B_MSIL2A_20200115T030049_N0212_R032_T48MXU_20201002T190103.SAFE'
    item_id=product.replace('_N0212','').removesuffix('.SAFE')
    base='https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/48/M/XU/2020/01/15/'+product
    resolution=20 if key in ('B11','SCL') else 10
    relative=f'GRANULE/L2A_T48MXU_A014930_20200115T031557/IMG_DATA/R{resolution}m/T48MXU_20200115T030049_{key}_{resolution}m'
    item=dict(id=item_id,assets={key:dict(href=base+'/'+relative+'.tif',**{'proj:shape':[64,64],'proj:transform':[resolution,0,600000,0,-resolution,9400000]}),'product-metadata':dict(href=base+'/MTD_MSIL2A.xml')})
    xml=f'<root><PRODUCT_URI>{product}</PRODUCT_URI><IMAGE_FILE>{relative}</IMAGE_FILE><Special_Values><SPECIAL_VALUE_TEXT>NODATA</SPECIAL_VALUE_TEXT><SPECIAL_VALUE_INDEX>0</SPECIAL_VALUE_INDEX></Special_Values><Scene_Classification_ID><SCENE_CLASSIFICATION_TEXT>SC_NODATA</SCENE_CLASSIFICATION_TEXT><SCENE_CLASSIFICATION_INDEX>0</SCENE_CLASSIFICATION_INDEX></Scene_Classification_ID></root>'
    raw=xml_edit(xml).encode()
    scene=dict(item=item_id,item_metadata_sha256=hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest(),product_xml_url=item['assets']['product-metadata']['href'],product_xml_sha256=hashlib.sha256(raw).hexdigest(),assets=[dict(asset=key,url=item['assets'][key]['href'])])
    return item,scene,raw


def tiff(key='B03',nodata=None,**overrides):
    resolution=20 if key in ('B11','SCL') else 10
    profile=dict(driver='GTiff',width=64,height=64,count=1,dtype='uint8' if key=='SCL' else 'uint16',crs='EPSG:32748',transform=from_origin(600000,9400000,resolution,resolution),nodata=nodata,tiled=True,blockxsize=16,blockysize=16)
    profile.update(overrides)
    a=np.full((profile['count'],profile['height'],profile['width']),6 if key=='SCL' else 2000,dtype=profile['dtype'])
    a[:,0,0]=0
    with MemoryFile() as mem:
        with mem.open(**profile) as ds:ds.write(a)
        return mem.read()


@pytest.mark.parametrize('key',['B03','B11','SCL'])
@pytest.mark.parametrize('nodata',[None,0])
def test_absent_and_zero_tags_under_explicit_xml(key,nodata):
    item,scene,raw=fixture(key);contract=xml_nodata_contract(raw,item,scene,key)
    result=runner.verify_native(tiff(key,nodata),item,key,contract)
    assert result['tiff_nodata']==nodata and result['effective_nodata']==0
    assert result['product_xml_sha256']==scene['product_xml_sha256']


@pytest.mark.parametrize('offset',[0,-1000])
def test_decoded_masks_identical_and_zero_masked_before_offset(offset):
    outputs=[]
    for tag in (None,0):
        with MemoryFile(tiff(nodata=tag)) as mem:
            with mem.open() as ds:outputs.append(rules.reflectance(ds.read(1),offset))
    np.testing.assert_array_equal(outputs[0],outputs[1])
    assert np.isnan(outputs[0][0,0]) and outputs[0][1,1]==(2000+offset)/10000


def test_scl_zero_still_excluded_with_missing_tiff_tag():
    item,scene,raw=fixture('SCL');contract=xml_nodata_contract(raw,item,scene,'SCL')
    data=tiff('SCL');runner.verify_native(data,item,'SCL',contract)
    with MemoryFile(data) as mem:
        with mem.open() as ds:q=ds.read(1)
    clear,_=rules.date_states(np.full(q.shape,.3),np.full(q.shape,.1),q)
    assert not clear[0,0] and clear[10,10]


@pytest.mark.parametrize('change',[
    lambda s:s.replace('NODATA','UNKNOWN'),
    lambda s:s.replace('<SPECIAL_VALUE_INDEX>0','<SPECIAL_VALUE_INDEX>1'),
    lambda s:s.replace('<SPECIAL_VALUE_INDEX>0','<SPECIAL_VALUE_INDEX>NaN'),
    lambda s:s.replace('</Special_Values>','<SPECIAL_VALUE_INDEX>0</SPECIAL_VALUE_INDEX></Special_Values>'),
    lambda s:s.replace('</root>',s[s.index('<Special_Values>'):s.index('</Special_Values>')+len('</Special_Values>')]+'</root>'),
    lambda s:s.replace('<SCENE_CLASSIFICATION_INDEX>0','<SCENE_CLASSIFICATION_INDEX>1'),
    lambda s:s.replace('</Scene_Classification_ID>','<SCENE_CLASSIFICATION_INDEX>0</SCENE_CLASSIFICATION_INDEX></Scene_Classification_ID>'),
])
def test_bad_xml_stops_before_any_asset_or_block_request(change):
    item,scene,raw=fixture('SCL',change);transport=Mock();block=Mock()
    with pytest.raises(ValidationError) as error:
        contract=xml_nodata_contract(raw,item,scene,'SCL')
        runner.inspect_native((item,scene['assets'][0],contract),transport)
        block()
    transport.head.assert_not_called();transport.read.assert_not_called();block.assert_not_called()
    assert error.value.detail['item']==item['id'] and error.value.detail['asset']=='SCL'
    assert error.value.detail['differing_fields']


@pytest.mark.parametrize('case',['xml_hash','item_hash','scene_id','xml_url','asset_url','product_uri','image_reference','duplicate_reference','other_product','wrong_band'])
def test_wrong_asset_product_association_is_rejected(case):
    item,scene,raw=fixture();transport=Mock();block=Mock()
    if case=='xml_hash':scene['product_xml_sha256']='0'*64
    elif case=='item_hash':scene['item_metadata_sha256']='0'*64
    elif case=='scene_id':scene['item']='different'
    elif case=='xml_url':scene['product_xml_url']+='other'
    elif case=='asset_url':scene['assets'][0]['url']+='other'
    elif case=='product_uri':raw=raw.replace(b'<PRODUCT_URI>S2B',b'<PRODUCT_URI>S2A')
    elif case=='image_reference':raw=raw.replace(b'_B03_10m</IMAGE_FILE>',b'_B04_10m</IMAGE_FILE>')
    elif case=='duplicate_reference':raw=raw.replace(b'</root>',raw[raw.index(b'<IMAGE_FILE>'):raw.index(b'</IMAGE_FILE>')+13]+b'</root>')
    elif case=='other_product':item['assets']['B03']['href']=item['assets']['B03']['href'].replace('N0212','N0300')
    elif case=='wrong_band':
        item['assets']['B03']['href']=item['assets']['B03']['href'].replace('_B03_10m','_B04_10m')
        raw=raw.replace(b'_B03_10m',b'_B04_10m')
    if case not in ('xml_hash','item_hash','scene_id','xml_url','asset_url'):
        # Isolate association checks rather than merely testing checksum rejection.
        scene['product_xml_sha256']=hashlib.sha256(raw).hexdigest()
        scene['item_metadata_sha256']=hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()
        scene['assets'][0]['url']=item['assets']['B03']['href']
    with pytest.raises(ValidationError):
        contract=xml_nodata_contract(raw,item,scene,'B03')
        runner.inspect_native((item,scene['assets'][0],contract),transport);block()
    transport.head.assert_not_called();transport.read.assert_not_called();block.assert_not_called()


@pytest.mark.parametrize('overrides,field',[
    ({'nodata':65535},'tiff_nodata'),
    ({'nodata':float('nan'),'dtype':'float32'},'tiff_nodata'),
    ({'crs':'EPSG:32749'},'crs'),
    ({'crs':None},'crs'),
    ({'transform':from_origin(600000.000001,9400000,10,10)},'transform'),
    ({'width':80},'shape'),
    ({'dtype':'int16'},'datatype'),
    ({'count':2},'count'),
])
def test_native_mismatch_stops_at_metadata_and_persists_named_fields(tmp_path,overrides,field):
    item,scene,xml=fixture();contract=xml_nodata_contract(xml,item,scene,'B03');raw=tiff(**overrides)
    layout=f.tiff_layout(lambda o,n:raw[o:o+n]);ranges=[]
    def metadata_only_read(asset,off,n):
        assert all(not(max(off,p)<min(off+n,p+k)) for p,k in zip(layout['offsets'],layout['bytecounts']))
        ranges.append((off,n));return raw[off:off+n]
    asset=dict(asset='B03',url=item['assets']['B03']['href'],etag='synthetic',metadata_ranges=[],required_tiles=[])
    transport=Mock();transport.read.side_effect=metadata_only_read;block=Mock()
    with pytest.raises(ValidationError) as error:
        runner.inspect_native((item,asset,contract),transport);block()
    block.assert_not_called()
    assert ranges and field in error.value.detail['differing_fields']
    path=record_failure(tmp_path,error.value);record_failure(tmp_path,error.value)
    record=json.loads(path.read_bytes())
    assert record['item']==item['id'] and record['asset']=='B03'
    assert field in record['expected'] and field in record['actual']


def test_wrong_contract_rejected_by_block_acquisition_entry(tmp_path):
    item,scene,xml=fixture();other,other_scene,other_xml=fixture('B11')
    contract=xml_nodata_contract(other_xml,other,other_scene,'B11')
    transport=Mock()
    with pytest.raises(ValidationError):runner.acquire_scene(scene,item,{},transport,tmp_path,[],{(item['id'],'B03'):contract})
    transport.read.assert_not_called()
    assert not list(tmp_path.iterdir())
