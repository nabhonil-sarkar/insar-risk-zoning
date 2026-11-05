"""Metadata-only coastal pilot design. No Sentinel-2 pixel acquisition/inference."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import struct
from urllib.parse import urlsplit

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.windows import Window
import requests
from scipy import ndimage
from shapely.geometry import box, shape

from scripts.run_alphaearth_surface_type import digest, write_new, WC_SHA

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/output/coastal_transition_pilot_v1"
COLLECTION = "sentinel-2-c1-l2a"
API = "https://earth-search.aws.element84.com/v1"
ASSETS = ("blue", "green", "red", "nir", "swir16", "scl", "cloud")
MONTHS = (1, 2, 3, 4, 6, 7, 8, 9)
HALO = 160
WC_PATH = Path("C:/Users/Admin/Documents/Codex/2026-08-06/continue-my-jakarta-insar-risk-zoning-2/outputs/Jakarta-portfolio-land-check/qa/worldcover.tif")


def sample_cover(ds, x, y):
    lon, lat = Transformer.from_crs(32748, 4326, always_xy=True).transform(x, y)
    c = np.floor((lon - ds.transform.c) / ds.transform.a).astype(int)
    r = np.floor((lat - ds.transform.f) / ds.transform.e).astype(int)
    if c.min() < 0 or r.min() < 0 or c.max() >= ds.width or r.max() >= ds.height:
        raise ValueError("WorldCover does not cover design envelope")
    win = Window(int(c.min()), int(r.min()), int(np.ptp(c)+1), int(np.ptp(r)+1))
    a = ds.read(1, window=win)
    return a[r-r.min(), c-c.min()], lon, lat


def choose_windows(candidates):
    coast = [c for c in candidates if .2 <= c["sea_fraction"] <= .8 and c["land_fraction"] >= .2]
    water = [c for c in candidates if c["sea_fraction"] >= .98]
    land = [c for c in candidates if c["land_fraction"] >= .98]
    if len(coast) < 4 or not water or not land:
        raise ValueError("Insufficient geometry support; no substitute selection")
    chosen = []
    xs = [c["centre_utm"][0] for c in coast]
    for target in np.linspace(min(xs), max(xs), 4):
        remaining = [c for c in coast if c not in chosen]
        chosen.append(min(remaining, key=lambda c: (abs(c["centre_utm"][0]-target), -c["centre_utm"][1], c["centre_utm"][0])))
    middle = (min(xs)+max(xs))/2
    chosen.append(min(land, key=lambda c: (c["centre_utm"][1], abs(c["centre_utm"][0]-middle), c["centre_utm"][0])))
    chosen.append(min(water, key=lambda c: (-c["centre_utm"][1], abs(c["centre_utm"][0]-middle), c["centre_utm"][0])))
    return [dict(c, id=f"C{i+1}" if i < 4 else "L1" if i == 4 else "W1",
                 role="coastal_mixed" if i < 4 else "baseline_land_control" if i == 4 else "baseline_water_control")
            for i, c in enumerate(chosen)]


def geometry():
    inventory_path = ROOT / "data/output/alphaearth_surface_type_v1/inventory.json"
    if digest(inventory_path) != "cd1fe1b7ee30b523563522371684e3ca40a0a45d86a9a07c722951677566297f" or digest(WC_PATH) != WC_SHA:
        raise ValueError("Baseline input hash mismatch")
    inv = json.loads(inventory_path.read_bytes())
    tr = inv["grid"]["transform"]
    west, _, _, north = inv["roi"]
    east = tr[2] + 953*tr[0]
    south = tr[5] + 656*tr[4]
    roi = [west, south, east, north]
    project = Transformer.from_crs(4326, 32748, always_xy=True)
    unproject = Transformer.from_crs(32748, 4326, always_xy=True)
    xx, yy = project.transform([west, west, east, east], [south, north, south, north])
    x0, x1 = math.ceil(min(xx)/20)*20, math.floor(max(xx)/20)*20
    y0, y1 = math.ceil(min(yy)/20)*20, math.floor(max(yy)/20)*20
    x, y = np.meshgrid(np.arange(x0, x1, 20)+10, np.arange(y1, y0, -20)-10)
    # Clip projected envelope before sampling native WC; longitude-latitude
    # corners stay below the tile's northern edge at -6 degrees.
    with rasterio.open(WC_PATH) as ds:
        cover, lon, lat = sample_cover(ds, x, y)
    inside = (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
    water = (cover == 80) & inside
    labels, _ = ndimage.label(water)  # four-connectivity
    seed = np.unique(labels[water & (lat >= north-.002)])
    counts = np.bincount(labels.ravel())
    seed = seed[(seed > 0) & (counts[seed] >= 1000)]
    sea = np.isin(labels, seed)
    land = np.isin(cover, [10, 20, 30, 40, 50, 60, 70, 90, 95, 100])
    candidates = []
    for left in range(math.ceil(x0/1000)*1000, x1-1000, 1000):
        for bottom in range(math.ceil(y0/1000)*1000, y1-1000, 1000):
            corners = [(left-HALO, bottom-HALO), (left+1000+HALO, bottom-HALO),
                       (left+1000+HALO, bottom+1000+HALO), (left-HALO, bottom+1000+HALO)]
            geo = [unproject.transform(*p) for p in corners]
            if not all(west <= a <= east and south <= b <= north for a, b in geo):
                continue
            col, row = (left-x0)//20, (y1-bottom-1000)//20
            sl = np.s_[row:row+50, col:col+50]
            centre = [left+500, bottom+500]
            core_geo = [unproject.transform(a, b) for a, b in [(left,bottom),(left+1000,bottom),(left+1000,bottom+1000),(left,bottom+1000)]]
            candidates.append(dict(centre_utm=centre, centre_lonlat=list(unproject.transform(*centre)),
                                   core_bounds_utm=[left,bottom,left+1000,bottom+1000],
                                   read_bounds_utm=[left-HALO,bottom-HALO,left+1000+HALO,bottom+1000+HALO],
                                   core_polygon_lonlat=core_geo+[core_geo[0]],
                                   read_polygon_lonlat=geo+[geo[0]],
                                   sea_fraction=float(sea[sl].mean()), water_fraction=float(water[sl].mean()),
                                   land_fraction=float(land[sl].mean())))
    windows = choose_windows(candidates)
    result = dict(schema="coastal_geometry_v1", roi=roi, crs="EPSG:32748", core_side_m=1000,
                  halo_m=HALO, analysis_cell_m=20, windows=windows, candidates=candidates,
                  worldcover_sha256=WC_SHA, phase_a_inventory_sha256=digest(inventory_path),
                  selection="1 km lattice anchored at UTM zero, full core+160 m halo inside original NW sector. 2020 WC sampled at 20 m centres. Sea proxy: four-connected water reaching the northern 0.002-degree ROI strip with >=1000 cells. Coastal candidates have 20-80% sea proxy and >=20% non-water land. Choose four nearest equally spaced easting targets across eligible range, ties northmost then westmost. Controls: >=98% baseline land, southmost then nearest middle easting; >=98% sea proxy, northmost then nearest middle easting. No embedding distances or contemporary imagery used. Coast proxy and controls are not ground truth; not a representative coastline sample.")
    write_new(OUT / "geometry.json", result)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    fig, ax = plt.subplots(figsize=(11, 8), layout="constrained")
    display = np.ma.masked_where(~inside, np.where(water, 0, 1))
    ax.imshow(display, extent=(x0,x1,y0,y1), cmap=matplotlib.colors.ListedColormap(["#77b9d1", "#dedbc1"]), vmin=0,vmax=1)
    for w in windows:
        a,b,c,d = w["core_bounds_utm"]
        ax.add_patch(Rectangle((a,b),c-a,d-b,fill=False,edgecolor="#9d2645",linewidth=2))
        ax.text(a,b-220,w["id"],fontsize=11,color="#7e1531",weight="bold")
    ax.set_title("Proposed six-window pilot on 2020 WorldCover land/water\nFour coastal windows + inland/open-water controls; 1 km cores")
    ax.set_xlabel("Easting, EPSG:32748 (m)");ax.set_ylabel("Northing (m)")
    fig.savefig(OUT / "windows.png",dpi=150);plt.close(fig)
    return result


def fetch_year(year, bbox):
    url = API + "/search"
    params = dict(collections=COLLECTION, bbox=",".join(map(str,bbox)),
                  datetime=f"{year}-01-01T00:00:00Z/{year}-12-31T23:59:59Z", limit=100)
    entries, pages, total_bytes = {}, [], 0
    expected = None
    while url:
        if urlsplit(url).netloc != "earth-search.aws.element84.com" or url in pages:
            raise ValueError("Unsafe/repeated catalogue page")
        pages.append(url)
        response = requests.get(url,params=params,timeout=45)
        response.raise_for_status()
        total_bytes += len(response.content)
        if total_bytes > 32*1024**2 or len(pages)>30:
            raise ValueError("Metadata budget exceeded")
        obj = response.json()
        if expected is None:expected=obj["numberMatched"]
        if obj["numberMatched"] != expected:raise ValueError("Catalogue changed during pagination")
        for item in obj["features"]:
            if item["id"] in entries:raise ValueError("Duplicate catalogue item")
            if item["collection"] != COLLECTION or int(item["properties"]["datetime"][:4]) != year:
                raise ValueError("Wrong collection/year")
            entries[item["id"]]=item
        url=next((x["href"] for x in obj["links"] if x["rel"]=="next"),None)
        params=None
    if len(entries)!=expected or not entries:raise ValueError("Incomplete catalogue")
    return dict(year=year,number_matched=expected,metadata_bytes=total_bytes,pages=pages,
                items=sorted(entries.values(),key=lambda v:v["id"]))


def asset_contract(item):
    p=item["properties"]
    if p["proj:epsg"]!=32748 or p.get("storage:requester_pays") is not False:
        raise ValueError("Wrong CRS or payment contract")
    for key in ASSETS:
        a=item["assets"][key]; m=a["raster:bands"][0]
        if (urlsplit(a["href"]).netloc!="e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com"
                or m["nodata"]!=0 or a["gsd"]!=(20 if key in ("swir16","scl","cloud") else 10)
                or not a["file:checksum"].startswith("1220") or a["file:size"]<=0):
            raise ValueError("Unexpected asset contract")
        if key not in ("scl","cloud") and (m.get("scale")!=.0001 or m.get("offset")!=-.1):
            raise ValueError("Unexpected Collection 1 radiometry")


def select_items(items, windows, validator=asset_contract):
    footprints=[shape({"type":"Polygon","coordinates":[w["read_polygon_lonlat"]]}) for w in windows]
    candidates=[]
    for item in items:
        if not all(shape(item["geometry"]).covers(g) for g in footprints):continue
        validator(item)
        candidates.append(item)
    selected, bins = [], []
    for year in range(2020,2026):
        for month in MONTHS:
            for half in (0,1):
                pool=[v for v in candidates if v["properties"]["datetime"][:7]==f"{year}-{month:02}" and (int(v["properties"]["datetime"][8:10])>15)==bool(half)]
                # One scene per calendar half-month shared by every window;
                # duplicate acquisitions cannot become repeated evidence.
                best=min(pool,key=lambda v:(v["properties"]["eo:cloud_cover"],v["properties"]["datetime"],v["id"])) if pool else None
                bins.append(dict(year=year,month=month,half=half+1,candidates=len(pool),selected=best["id"] if best else None))
                if best:selected.append(best)
    return selected,bins


def inventory():
    geom=json.loads((OUT/"geometry.json").read_bytes())
    all_items=[];yearly=[]
    for year in range(2020,2026):
        p=OUT/f"catalogue_{year}.json"
        if p.exists():obj=json.loads(p.read_bytes())
        else:
            obj=fetch_year(year,geom["roi"]);write_new(p,obj)
        all_items.extend(obj["items"])
        yearly.append(dict(year=year,items=len(obj["items"]),dates=len({v["properties"]["datetime"][:10] for v in obj["items"]}),sha256=digest(p)))
        print(f"catalogue {year}: {len(obj['items'])} items",flush=True)
    selected,bins=select_items(all_items,geom["windows"])
    obj=dict(schema="coastal_catalogue_v1",collection=COLLECTION,geometry_sha256=digest(OUT/"geometry.json"),
             yearly=yearly,selection_bins=bins,selected_items=selected,
             rule="One whole-read-footprint scene per calendar half-month in Jan-Apr and Jun-Sep, minimum scene cloud percent then timestamp then ID. No local pixels inspected, no cloud cutoff, no replacements after acquisition. Half-months lacking whole-footprint support remain absent.",
             limits="Footprint/catalogue availability is not usable clear-pixel coverage. No Sentinel-2 pixel data read.")
    write_new(OUT/"catalogue_selection.json",obj)
    return obj


class HeaderReader:
    """Read only requested TIFF metadata ranges; never rasterio-open remote data."""
    def __init__(self, url, expected_size=None):
        self.url=url; self.size=expected_size; self.bytes=0; self.ranges=[]
        self.session=requests.Session()
        h=self.session.head(url,timeout=40,allow_redirects=False)
        h.raise_for_status()
        size=int(h.headers.get("Content-Length",-1))
        if (size<=0 or (expected_size is not None and size!=expected_size)
                or h.headers.get("Accept-Ranges")!="bytes" or not h.headers.get("ETag")):
            raise ValueError("HEAD metadata mismatch")
        self.size=size
        self.etag=h.headers["ETag"]

    def read(self, offset, length):
        if offset<0 or length<=0 or offset+length>self.size or self.bytes+length>65536:
            raise ValueError("TIFF metadata byte budget/range exceeded")
        with self.session.get(self.url,headers={"Range":f"bytes={offset}-{offset+length-1}","If-Match":self.etag},stream=True,timeout=40,allow_redirects=False) as r:
            if (r.status_code!=206 or r.headers.get("Content-Range")!=f"bytes {offset}-{offset+length-1}/{self.size}"
                    or r.headers.get("ETag")!=self.etag or int(r.headers.get("Content-Length",-1))!=length):
                raise ValueError("Range/ETag gate failed; refusing full-object response")
            data=r.raw.read(length+1)
        if len(data)!=length:raise ValueError("Short/long range response")
        self.bytes+=length;self.ranges.append([offset,length,hashlib.sha256(data).hexdigest()])
        return data


def tiff_layout(read):
    head=read(0,8)
    endian={b"II":"<",b"MM":">"}.get(head[:2])
    if not endian:raise ValueError("Invalid TIFF byte order")
    magic=struct.unpack(endian+"H",head[2:4])[0]
    if magic==42:
        ifd=struct.unpack(endian+"I",head[4:8])[0];size=2;entry=12;inline=4;offsetfmt="I"
    elif magic==43:
        if struct.unpack(endian+"HH",head[4:8])!=(8,0):raise ValueError("Invalid BigTIFF")
        ifd=struct.unpack(endian+"Q",read(8,8))[0];size=8;entry=20;inline=8;offsetfmt="Q"
    else:raise ValueError("Not TIFF")
    n=struct.unpack(endian+("H" if size==2 else "Q"),read(ifd,size))[0]
    if not 1<=n<=100:raise ValueError("Unexpected TIFF directory")
    table=read(ifd+size,n*entry)
    vals={}
    types={3:(2,"H"),4:(4,"I"),16:(8,"Q")}
    for i in range(n):
        raw=table[i*entry:(i+1)*entry]
        tag,typ=struct.unpack(endian+"HH",raw[:4])
        if tag not in (256,257,322,323,324,325):continue
        count=struct.unpack(endian+("I" if inline==4 else "Q"),raw[4:8] if inline==4 else raw[4:12])[0]
        if typ not in types or not 1<=count<=10000:raise ValueError("Unsupported TIFF field")
        width,fmt=types[typ];data=raw[-inline:]
        if count*width>inline:data=read(struct.unpack(endian+offsetfmt,data)[0],count*width)
        vals[tag]=list(struct.unpack(endian+fmt*count,data[:count*width]))
    if set(vals)!={256,257,322,323,324,325}:raise ValueError("Missing tiled TIFF geometry")
    width,height,tw,th=(vals[k][0] for k in (256,257,322,323))
    if min(width,height,tw,th)<=0 or len(vals[324])!=math.ceil(width/tw)*math.ceil(height/th) or len(vals[324])!=len(vals[325]):
        raise ValueError("TIFF tile layout mismatch")
    return dict(width=width,height=height,tile_width=tw,tile_height=th,offsets=vals[324],bytecounts=vals[325])


def block_ids(layout, transform, windows):
    a,b,c,d,e,f=transform
    if b or d or a<=0 or e>=0:raise ValueError("Unexpected native transform")
    ids=set();nx=math.ceil(layout["width"]/layout["tile_width"])
    for w in windows:
        left,bottom,right,top=w["read_bounds_utm"]
        c0,c1=math.floor((left-c)/a),math.ceil((right-c)/a)
        r0,r1=math.floor((top-f)/e),math.ceil((bottom-f)/e)
        if min(c0,r0)<0 or c1>layout["width"] or r1>layout["height"]:raise ValueError("Window outside asset")
        for rr in range(r0//layout["tile_height"],(r1-1)//layout["tile_height"]+1):
            for cc in range(c0//layout["tile_width"],(c1-1)//layout["tile_width"]+1):ids.add(rr*nx+cc)
    return sorted(ids)


def inspect_asset(job):
    item,key,windows=job;asset=item["assets"][key]
    name=hashlib.sha256(asset["href"].encode()).hexdigest()+".json"
    dest=OUT/"header_cache"/name
    if dest.exists():
        result=json.loads(dest.read_bytes())
        if result["catalogue_checksum"]!=asset["file:checksum"] or result["url"]!=asset["href"]:raise ValueError("Header cache drift")
        return result
    reader=HeaderReader(asset["href"],asset["file:size"])
    layout=tiff_layout(reader.read)
    if [layout["height"],layout["width"]]!=asset["proj:shape"]:raise ValueError("Native shape mismatch")
    for off,length,_ in reader.ranges:
        if any(max(off,p)<min(off+length,p+n) for p,n in zip(layout["offsets"],layout["bytecounts"])):
            raise ValueError("Metadata overlaps pixel payload")
    ids=block_ids(layout,asset["proj:transform"],windows)
    result=dict(item=item["id"],asset=key,url=asset["href"],etag=reader.etag,file_size=reader.size,
                catalogue_checksum=asset["file:checksum"],metadata_bytes=reader.bytes,metadata_ranges=reader.ranges,
                native_shape=[layout["height"],layout["width"]],tile_shape=[layout["tile_height"],layout["tile_width"]],
                required_tiles=[dict(index=i,offset=layout["offsets"][i],bytes=layout["bytecounts"][i]) for i in ids],
                requested_pixel_bytes=0,estimated_pixel_bytes=sum(layout["bytecounts"][i] for i in ids))
    write_new(dest,result);reader.session.close()
    return result


def resources():
    selected=json.loads((OUT/"catalogue_selection.json").read_bytes())
    windows=json.loads((OUT/"geometry.json").read_bytes())["windows"]
    (OUT/"header_cache").mkdir(exist_ok=True)
    jobs=[(item,key,windows) for item in selected["selected_items"] for key in ASSETS]
    records=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i,record in enumerate(pool.map(inspect_asset,jobs),1):
            records.append(record)
            if i%42==0:print(f"Verified {i}/{len(jobs)} asset headers; no pixel blocks requested",flush=True)
    payload=sum(r["estimated_pixel_bytes"] for r in records)
    metadata=sum(r["metadata_bytes"] for r in records)
    result=dict(schema="coastal_resources_v1",selection_sha256=digest(OUT/"catalogue_selection.json"),
                assets=records,asset_count=len(records),selected_scene_count=len(selected["selected_items"]),
                compressed_native_tile_payload_bytes=payload,metadata_bytes_read=metadata,
                full_object_bytes_not_to_download=sum(r["file_size"] for r in records),
                pixel_payload_bytes_read=0,required_native_tiles=sum(len(r["required_tiles"]) for r in records),
                proposed_transfer_ceiling_bytes=min(12*1024**3,math.ceil(1.5*payload/1024**3)*1024**3),
                budget_feasible=1.5*payload<=12*1024**3,
                assumptions="Exact compressed native-tile bytes for the union of six core+halo windows, deduplicated per asset, from first full-resolution TIFF IFD only. Excludes overviews and full-object downloads. Header-only HTTP ranges audited disjoint from all native pixel blocks; no reflectance/SCL/cloud pixels decoded. ETags pinned; metadata file checksums are provider declarations, not locally verified full-file hashes. Future acquisition must cap all bytes including retries and metadata, use If-Match, reject HTTP 200 fallback, preserve per-range hashes and never replace failed scenes.",
                runtime_estimate="10-60 minutes with six concurrent range requests and >=10 Mbit/s sustained transfer; network-dependent estimate, not measured pixel throughput. Proposed two-hour acquisition ceiling; stop and report if exceeded. Reserve 2x transfer ceiling + 1 GiB local disk for cache/staging/crops.")
    write_new(OUT/"resources.json",result)
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("geometry","inventory","resources"))
    args=parser.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    result={"geometry":geometry,"inventory":inventory,"resources":resources}[args.action]()
    print("Saved",args.action,flush=True)
