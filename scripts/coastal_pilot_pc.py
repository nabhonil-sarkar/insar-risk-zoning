"""Second-route catalogue and metadata-only audit. No optical pixel downloads."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import threading
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

import requests

from scripts import coastal_pilot_feasibility as f

API="https://planetarycomputer.microsoft.com/api/stac/v1"
ASSETS=("B02","B03","B04","B08","B11","SCL")
TOKEN_LOCK=threading.Lock()
TOKENS={}


def public_token(href):
    """Reuse the provider's public container token; never persist it."""
    u=urlsplit(href);container=(u.netloc,u.path.split('/')[1])
    with TOKEN_LOCK:
        if container not in TOKENS:
            signed=requests.get("https://planetarycomputer.microsoft.com/api/sas/v1/sign",params={"href":href},timeout=40)
            signed.raise_for_status()
            result=urlsplit(signed.json()["href"])
            if result.scheme!=u.scheme or result.netloc!=u.netloc or result.path!=u.path or not result.query:
                raise ValueError("Unexpected public signing response")
            TOKENS[container]=result.query
        return TOKENS[container]


def contract(item):
    p=item["properties"]
    if not math.isfinite(p["eo:cloud_cover"]) or not 0<=p["eo:cloud_cover"]<=100:
        raise ValueError("Invalid catalogue cloud percentage")
    if p["proj:epsg"]!=32748 or p["s2:processing_baseline"] not in ("02.12","03.00","04.00","05.09","05.10","05.11"):
        raise ValueError("Unregistered processing baseline or wrong CRS")
    for key in ASSETS:
        a=item["assets"][key];u=urlsplit(a["href"])
        if u.scheme!="https" or not u.netloc.startswith("sentinel2l2a") or not u.netloc.endswith(".blob.core.windows.net") or u.query:
            raise ValueError("Unexpected unsigned asset URL")
        if a["gsd"]!=(20 if key in ("B11","SCL") else 10):raise ValueError("Unexpected native resolution")
        resolution=a["gsd"];side=109800//resolution
        if a["proj:shape"]!=[side,side] or a["proj:transform"]!=[resolution,0,600000,0,-resolution,9400000]:
            raise ValueError("Unexpected tile geometry")


def fetch_year(year,bbox):
    url=API+"/search"
    params=dict(collections="sentinel-2-l2a",bbox=",".join(map(str,bbox)),datetime=f"{year}-01-01T00:00:00Z/{year}-12-31T23:59:59Z",limit=100)
    entries={};pages=set();size=0
    while url:
        if urlsplit(url).netloc!="planetarycomputer.microsoft.com" or url in pages:raise ValueError("Unsafe/repeated pagination")
        pages.add(url)
        resp=requests.get(url,params=params,timeout=45);resp.raise_for_status();size+=len(resp.content)
        if size>32*1024**2 or len(pages)>30:raise ValueError("Metadata budget exceeded")
        obj=resp.json()
        for item in obj["features"]:
            if item["id"] in entries or item["collection"]!="sentinel-2-l2a" or int(item["properties"]["datetime"][:4])!=year:raise ValueError("Duplicate/wrong item")
            entries[item["id"]]=item
        links=[x for x in obj["links"] if x["rel"]=="next"]
        if links and links[0].get("method","GET")!="GET":raise ValueError("Unexpected pagination method")
        url=links[0]["href"] if links else None;params=None
    return dict(year=year,items=list(entries.values()),metadata_bytes=size,pages=len(pages),
                completeness="Exhausted next links; API supplies no numberMatched. Not a guarantee of complete satellite archive.")


def inventory(calibrated=False):
    geom=json.loads((f.OUT/"geometry.json").read_bytes());items=[];yearly=[]
    for year in range(2020,2026):
        path=f.OUT/f"pc_catalogue_{year}.json"
        if path.exists():obj=json.loads(path.read_bytes())
        else:obj=fetch_year(year,geom["roi"]);f.write_new(path,obj)
        eligible=[v for v in obj["items"] if float(v["properties"]["s2:processing_baseline"])>=5]
        items.extend(obj["items"] if calibrated else eligible)
        yearly.append(dict(year=year,catalogue_items=len(obj["items"]),pb5_items=len(eligible),pb5_distinct_dates=len({v["properties"]["datetime"][:10] for v in eligible}),sha256=f.digest(path)))
        print(f"PC {year}: {len(obj['items'])} items, {len(eligible)} PB>=05",flush=True)
    # De-duplicate processing versions before cloud selection: latest generation
    # per acquisition timestamp/platform/tile, then lexical ID. No multiple votes.
    unique={}
    for v in items:
        p=v["properties"];key=(p["datetime"],p["platform"],p["s2:mgrs_tile"])
        if key not in unique or (p["s2:generation_time"],v["id"])>(unique[key]["properties"]["s2:generation_time"],unique[key]["id"]):unique[key]=v
    selected,bins=f.select_items(list(unique.values()),geom["windows"],contract)
    obj=dict(schema="coastal_pc_catalogue_v1",route="Microsoft Planetary Computer sentinel-2-l2a; per-product XML calibration, mixed processing baselines" if calibrated else "Microsoft Planetary Computer sentinel-2-l2a; PB>=05.00 only",
             geometry_sha256=f.digest(f.OUT/"geometry.json"),yearly=yearly,selection_bins=bins,selected_items=selected,
             limitations="Catalogue footprint support only. No cloud probability asset; SCL cloud/shadow screening proposed. Raw DNs require verified product XML offsets/quantification, no harmonization assumed from collection name. C1 Earth Search 2022 gap retained separately; no mixing of providers.")
    f.write_new(f.OUT/("pc_calibrated_selection.json" if calibrated else "pc_selection.json"),obj)


def radiometry(raw, expected_baseline):
    root=ET.fromstring(raw)
    tags=lambda name:[el for el in root.iter() if el.tag.split('}')[-1]==name]
    q=tags("BOA_QUANTIFICATION_VALUE")
    offsets=tags("BOA_ADD_OFFSET")
    baseline=tags("PROCESSING_BASELINE")
    if len(baseline)!=1 or baseline[0].text!=expected_baseline:
        raise ValueError("XML/catalogue baseline mismatch")
    values={int(v.attrib["band_id"]):float(v.text) for v in offsets}
    old=float(expected_baseline)<4
    offset=0 if old else -1000
    if (len(q)!=1 or float(q[0].text)!=10000 or len(values)!=len(offsets)
            or (old and offsets) or (not old and any(values.get(i)!=-1000 for i in (1,2,3,7,11)))):
        raise ValueError("Unexpected product quantification/offset metadata")
    return dict(processing_baseline=expected_baseline,quantification=10000,band_offsets={k:offset for k in ASSETS if k!="SCL"},formula=f"(DN+({offset}))/10000 after masking DN=0",source="Product XML and ESA PB<04 zero-offset convention; B02,B03,B04,B08,B11 zero-based IDs 1,2,3,7,11. Calibration aligns DN scale, not processing algorithms or geolocation.")


def inspect_item(item):
    contract(item)
    dest=f.OUT/"pc_header_cache"/(item["id"]+".json")
    if dest.exists():
        cached=json.loads(dest.read_bytes())
        if cached.get("item_metadata_sha256")!=__import__('hashlib').sha256(json.dumps(item,sort_keys=True).encode()).hexdigest():
            raise ValueError("Header cache item drift")
        if f.digest(dest.with_suffix(".xml"))!=cached["product_xml_sha256"]:raise ValueError("XML cache drift")
        return cached
    query=public_token(item["assets"]["B03"]["href"])
    # Container-scoped public read token is deliberately not saved or printed.
    xmlurl=item["assets"]["product-metadata"]["href"]
    with requests.get(xmlurl+"?"+query,timeout=40,stream=True) as resp:
        resp.raise_for_status();raw=resp.raw.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError("XML metadata budget exceeded")
    rm=radiometry(raw,item["properties"]["s2:processing_baseline"])
    windows=json.loads((f.OUT/"geometry.json").read_bytes())["windows"]
    records=[]
    for key in ASSETS:
        a=item["assets"][key];reader=f.HeaderReader(a["href"]+"?"+query)
        layout=f.tiff_layout(reader.read)
        if [layout["height"],layout["width"]]!=a["proj:shape"]:raise ValueError("Native header/catalogue geometry mismatch")
        if any(p<=0 or m<=0 or p+m>reader.size for p,m in zip(layout["offsets"],layout["bytecounts"])):
            raise ValueError("TIFF pixel range outside object")
        for off,n,_ in reader.ranges:
            if any(max(off,p)<min(off+n,p+m) for p,m in zip(layout["offsets"],layout["bytecounts"])):raise ValueError("Metadata overlaps native pixels")
        ids=f.block_ids(layout,a["proj:transform"],windows)
        records.append(dict(asset=key,url=a["href"],etag=reader.etag,file_size=reader.size,metadata_bytes=reader.bytes,
                            metadata_ranges=reader.ranges,tile_shape=[layout["tile_height"],layout["tile_width"]],
                            required_tiles=[dict(index=i,offset=layout["offsets"][i],bytes=layout["bytecounts"][i]) for i in ids],
                            estimated_pixel_bytes=sum(layout["bytecounts"][i] for i in ids)))
        reader.session.close()
    result=dict(item=item["id"],item_metadata_sha256=__import__('hashlib').sha256(json.dumps(item,sort_keys=True).encode()).hexdigest(),radiometry=rm,product_xml_sha256=__import__('hashlib').sha256(raw).hexdigest(),
                product_xml_url=xmlurl,xml_bytes=len(raw),assets=records,pixel_bytes_read=0)
    xmlpath=dest.with_suffix(".xml")
    with xmlpath.open("xb") as stream:stream.write(raw)
    f.write_new(dest,result)
    return result


def resources():
    selection=json.loads((f.OUT/"pc_calibrated_selection.json").read_bytes())
    (f.OUT/"pc_header_cache").mkdir(exist_ok=True)
    records=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i,record in enumerate(pool.map(inspect_item,selection["selected_items"]),1):
            records.append(record)
            if i%8==0:print(f"Verified XML and six native TIFF headers: {i}/{len(selection['selected_items'])} scenes",flush=True)
    payload=sum(a["estimated_pixel_bytes"] for r in records for a in r["assets"])
    metadata=sum(r["xml_bytes"]+sum(a["metadata_bytes"] for a in r["assets"]) for r in records)
    obj=dict(schema="coastal_pc_resources_v1",selection_sha256=f.digest(f.OUT/"pc_calibrated_selection.json"),scenes=records,
             compressed_native_tile_payload_bytes=payload,metadata_bytes_read=metadata,pixel_bytes_read=0,
             full_objects_bytes_not_to_download=sum(a["file_size"] for r in records for a in r["assets"]),
             required_native_tiles=sum(len(a["required_tiles"]) for r in records for a in r["assets"]),
             proposed_transfer_ceiling_bytes=math.ceil(1.5*payload/1024**3)*1024**3,
             budget_feasible=1.5*payload<=12*1024**3,
             byte_estimate="Exact sum of required compressed native TIFF tile byte counts, union of the six core+160 m halo windows per asset. No overviews or full-file fallback. Not a full-file checksum verification. Metadata ranges were disjoint from native image blocks; no pixels acquired/decoded.",
             runtime_estimate="10-60 minutes at >=10 Mbit/s sustained throughput with six parallel range requests; two-hour hard acquisition wall-time ceiling. Reserve twice the transfer ceiling plus 1 GiB for local disk. Throughput is an assumption, not a measured imagery transfer.")
    f.write_new(f.OUT/"pc_resources.json",obj)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['inventory','calibrated-inventory','resources']);a=p.parse_args()
    {'inventory':inventory,'calibrated-inventory':lambda:inventory(True),'resources':resources}[a.action]()
