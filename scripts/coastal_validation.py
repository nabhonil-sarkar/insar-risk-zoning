"""XML-backed nodata validation. No network, pixel reads or inferred sentinels."""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from scripts.coastal_transport import GateError
from scripts.run_alphaearth_surface_type import write_new


def json_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):return {k:json_value(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):return [json_value(v) for v in value]
    return value


class ValidationError(GateError):
    def __init__(self, item, key, stage, expected, actual):
        href=item.get('assets',{}).get(key,{}).get('href','')
        # Never include SAS queries in persisted diagnostics.
        u=urlsplit(href)
        self.detail=dict(item=item.get('id'),asset=key,unsigned_url=u._replace(query='',fragment='').geturl(),
                         stage=stage,expected=json_value(expected),actual=json_value(actual),
                         differing_fields=[k for k in expected if expected[k]!=actual.get(k)])
        super().__init__(f"{stage}: {self.detail['item']} / {key}: "+', '.join(self.detail['differing_fields']))


def record_failure(directory, exc):
    """Write a failure before shared cancellation; safe for parallel workers."""
    raw=json.dumps(exc.detail,sort_keys=True,allow_nan=False).encode()
    path=directory/('validation_failure_'+hashlib.sha256(raw).hexdigest()+'.json')
    try:write_new(path,exc.detail)
    except FileExistsError:
        if json.loads(path.read_bytes())!=exc.detail:raise
    return path


@dataclass(frozen=True)
class NodataContract:
    item_id: str
    asset_key: str
    asset_url: str
    xml_url: str
    xml_sha256: str
    effective_nodata: int = 0


def xml_nodata_contract(raw, item, scene, key):
    """Bind a unique explicit zero declaration to the exact pinned asset/product."""
    def require(field, expected, actual):
        if actual!=expected:raise ValidationError(item,key,'product_xml',{field:expected},{field:actual})
    require('asset_key_registered',True,key in ('B02','B03','B04','B08','B11','SCL'))
    require('resource_item_id',item['id'],scene.get('item'))
    item_sha=hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()
    require('item_metadata_sha256',scene.get('item_metadata_sha256'),item_sha)
    xml_sha=hashlib.sha256(raw).hexdigest()
    require('product_xml_sha256',scene.get('product_xml_sha256'),xml_sha)
    asset=item.get('assets',{}).get(key,{})
    product=item.get('assets',{}).get('product-metadata',{})
    require('product_xml_url',scene.get('product_xml_url'),product.get('href'))
    registered=[a for a in scene.get('assets',[]) if a.get('asset')==key]
    require('registered_asset_count',1,len(registered))
    require('asset_url',registered[0]['url'],asset.get('href'))
    xml_url=product.get('href','');asset_url=asset.get('href','')
    u,v=urlsplit(xml_url),urlsplit(asset_url)
    for label,url in [('xml',u),('asset',v)]:
        require(label+'_public_https_url',True,url.scheme=='https' and url.netloc.startswith('sentinel2l2a')
                and url.netloc.endswith('.blob.core.windows.net') and not url.query and not url.fragment)
    product_path=PurePosixPath(u.path).parent
    require('xml_filename','MTD_MSIL2A.xml',PurePosixPath(u.path).name)
    require('same_product_root',True,v.netloc==u.netloc and v.path.startswith(str(product_path)+'/'))
    relative=v.path[len(str(product_path))+1:]
    require('native_asset_path',True,relative.startswith('GRANULE/') and relative.endswith('.tif')
            and all(x not in ('.','..') for x in relative.split('/')))
    resolution=20 if key in ('B11','SCL') else 10
    require('asset_band_and_resolution',True,f'/R{resolution}m/' in relative
            and relative.endswith(f'_{key}_{resolution}m.tif'))
    try:root=ET.fromstring(raw)
    except ET.ParseError:
        raise ValidationError(item,key,'product_xml',{'xml_parse':'well-formed'},{'xml_parse':'invalid'}) from None
    def tags(name):return [e for e in root.iter() if e.tag.split('}')[-1]==name]
    names=[e.text for name in ('PRODUCT_URI','PRODUCT_URI_2A') for e in tags(name)]
    require('product_uri',[product_path.name],names)
    require('product_stac_identity',item['id'],re.sub(r'_N\d{4}(?=_R)','',product_path.name.removesuffix('.SAFE')))
    images=[e.text for name in ('IMAGE_FILE','IMAGE_FILE_2A') for e in tags(name)]
    require('xml_asset_image_reference_count',1,images.count(relative.removesuffix('.tif')))

    def zero_declaration(parent,label_tag,index_tag,label):
        declarations=[]
        for node in tags(parent):
            labels=[e.text for e in node if e.tag.split('}')[-1]==label_tag]
            indices=[e.text for e in node if e.tag.split('}')[-1]==index_tag]
            # Every record must be unambiguous, including malformed extra records.
            require(parent+'_field_counts',[1,1],[len(labels),len(indices)])
            if (labels[0] or '').strip().upper()==label:
                declarations.append(dict(label=labels[0],index=indices[0]))
        require(label+'_declarations',[dict(label=label,index='0')],declarations)
    zero_declaration('Special_Values','SPECIAL_VALUE_TEXT','SPECIAL_VALUE_INDEX','NODATA')
    if key=='SCL':
        zero_declaration('Scene_Classification_ID','SCENE_CLASSIFICATION_TEXT','SCENE_CLASSIFICATION_INDEX','SC_NODATA')
    return NodataContract(item['id'],key,asset_url,xml_url,xml_sha)


def require_contract(contract, item, key):
    expected=dict(item_id=item.get('id'),asset_key=key,asset_url=item.get('assets',{}).get(key,{}).get('href'),effective_nodata=0)
    actual={k:getattr(contract,k,None) for k in expected} if isinstance(contract,NodataContract) else {}
    if actual!=expected:raise ValidationError(item,key,'nodata_contract',expected,actual)
