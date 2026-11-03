"""Audit public imagery *metadata* on the frozen sites; no imagery downloads or labels."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import gzip
import hashlib
import html
import json
import re
import time
import requests
from shapely.geometry import shape, box
from shapely import union_all, make_valid
from scripts import urban_change_benchmark as b

CONFIG = (
    "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json"
)
PIN = "e3c9bb88b966eece0578162d68ab19b759c5a44f92364b3c4f782da3bdeef62b"
CACHE = b.OUT / "metadata_cache"
FIELDS = "OBJECTID,SRC_DATE,SRC_RES,SRC_DESC,NICE_DESC,MinMapLevel,MaxMapLevel"


def get(url, params=None):
    key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
    path = CACHE / (key + ".json.gz")
    if path.exists():
        return json.loads(gzip.decompress(path.read_bytes()))
    for k in range(3):
        try:
            response = requests.get(url, params=params, timeout=(10, 45))
            response.raise_for_status()
            obj = response.json()
            if "error" in obj:
                raise ValueError(obj["error"])
            CACHE.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as f:
                f.write(gzip.compress(response.content, mtime=0))
            return obj
        except (OSError, requests.RequestException):
            if k == 2:
                raise
            time.sleep(k + 1)


def schedule(config):
    releases = {}
    for key, v in config.items():
        day = date.fromisoformat(v["itemTitle"][-11:-1])
        if day < date(2020, 7, 1) or day > date(2026, 11, 3):
            continue
        half = (day.year, day.month > 6)
        if half not in releases or releases[half][0] < day:
            releases[half] = (day, key, v)
    return [releases[k] for k in sorted(releases)]


def find_layer(url):
    layers = get(url, {"f": "json"})["layers"]
    matching = [
        layer for layer in layers if layer["minScale"] >= 1128 > layer["maxScale"]
    ]
    if len(matching) != 1:
        raise ValueError("Cannot uniquely identify zoom-19 metadata layer")
    return matching[0]["id"]


def candidate(site, features, year):
    patch = box(*site["bounds"])
    parts = {}
    ids = []
    for feature in features:
        p = feature["properties"]
        if not (p["MinMapLevel"] <= 19 <= p["MaxMapLevel"]):
            continue
        geom = make_valid(shape(feature["geometry"]))
        if not geom.intersects(patch):
            continue
        key = (
            str(p["SRC_DATE"]),
            str(p["SRC_DESC"]),
            str(p["NICE_DESC"]),
            p["SRC_RES"],
        )
        parts.setdefault(key, []).append(geom)
        ids.append(p["OBJECTID"])
    if len(parts) != 1:
        return None
    (day, sensor, provider, res), geoms = next(iter(parts.items()))
    if (
        not day.startswith(str(year))
        or not re.search(
            r"WV0?[1-4]|WORLDVIEW|GEOEYE|GE0?1|QUICKBIRD|QB0?2|PLEIADES|P[LH]R",
            sensor,
            re.I,
        )
        or not res
        or not 0 < res <= 2
    ):
        return None
    captured = datetime.strptime(day, "%Y%m%d").date()
    if not union_all(geoms).covers(patch):
        return None
    return dict(
        capture_date=captured.isoformat(),
        sensor=sensor,
        provider=provider,
        resolution_m=res,
        object_ids=sorted(set(ids)),
    )


def query_batch(url, sites):
    rings = []
    for site in sites:
        w, s, e, n = site["bounds"]
        rings.append(
            [
                [round(x, 7), round(y, 7)]
                for x, y in [(w, s), (w, n), (e, n), (e, s), (w, s)]
            ]
        )
    p = dict(
        f="geojson",
        geometry=json.dumps({"rings": rings}, separators=(",", ":")),
        geometryType="esriGeometryPolygon",
        inSR=4326,
        outSR=4326,
        spatialRel="esriSpatialRelIntersects",
        where="1=1",
        outFields=FIELDS,
        returnGeometry="true",
        geometryPrecision=7,
    )
    data = get(url, p)
    if data.get("exceededTransferLimit"):
        if len(sites) == 1:
            raise ValueError("Truncated single-patch query")
        mid = len(sites) // 2
        return query_batch(url, sites[:mid]) + query_batch(url, sites[mid:])
    return [(site, data["features"]) for site in sites]


def main():
    if b.sha256_file(b.OUT / "protocol.json") != PIN:
        raise ValueError("Protocol hash mismatch")
    a = json.loads((b.OUT / "assignment.json").read_text())
    if (
        a["protocol_sha256"] != PIN
        or b.sha256_file(b.OUT / "assignment.json")
        != "f5914a2426b9f066152fcf6042445dc464035a5f34e8d8dbc8eb94986fbe119c"
    ):
        raise ValueError("Assignment drift")
    path = b.OUT / "reference_availability.json"
    if path.exists():
        raise FileExistsError(path)
    sites = a["sites"]
    found = {site["id"]: {} for site in sites}
    logs = []
    for day, key, item in schedule(get(CONFIG)):
        years = [y for y in (2020, 2025) if day >= date(y, 7, 1)]
        need = [s for s in sites if any(str(y) not in found[s["id"]] for y in years)]
        if not need:
            continue
        url = item["metadataLayerUrl"]
        layer = find_layer(url)
        query = f"{url}/{layer}/query"
        # Group neighbouring patches to limit complex disjoint geometries.
        need.sort(key=lambda s: (round(s["lon"], 1), s["lat"]))
        with ThreadPoolExecutor(5) as pool:
            for batch in pool.map(
                lambda v: query_batch(query, v),
                [need[i : i + 10] for i in range(0, len(need), 10)],
            ):
                for site, fs in batch:
                    for year in years:
                        d = found[site["id"]]
                        if str(year) in d:
                            continue
                        m = candidate(site, fs, year)
                        if m:
                            d[str(year)] = dict(
                                **m,
                                release=key,
                                release_date=day.isoformat(),
                                metadata_layer=query,
                                viewer=f"https://livingatlas.arcgis.com/wayback/#active={key}&mapCenter={site['lon']:.7f}%2C{site['lat']:.7f}%2C19",
                            )
        counts = [sum(str(y) in v for v in found.values()) for y in [2020, 2025]]
        print(day, counts, flush=True)
        logs.append(
            dict(
                release=key,
                date=day.isoformat(),
                inspected=len(need),
                cumulative_counts=counts,
            )
        )
    result = dict(
        protocol_sha256=PIN,
        assignment_sha256=b.sha256_file(b.OUT / "assignment.json"),
        snapshots=logs,
        sites=found,
        paired=sum(len(v) == 2 for v in found.values()),
        meaning="metadata candidates only; visual quality and labels unverified",
    )
    b.write_new(path, result)
    rows = []
    for s in sites:
        d = found[s["id"]]
        if len(d) != 2:
            continue

        def link(y):
            v = d[y]
            return f'<a href="{html.escape(v["viewer"])}">{v["capture_date"]} · {html.escape(v["sensor"])}</a>'

        rows.append(
            f"<tr><td>{s['id']}</td><td>{s['lat']:.6f}, {s['lon']:.6f}</td><td>{link('2020')}</td><td>{link('2025')}</td></tr>"
        )
    with (b.OUT / "blinded_review.html").open("x", encoding="utf8") as f:
        f.write(
            '<meta charset="utf-8"><title>Jakarta endpoint review</title><h1>Jakarta endpoint review</h1><p>Metadata candidates, not labels. Use blinded_patches.geojson for exact patch outlines. Confirm capture date, sensor, clarity and footprint for both dates. No scores or split shown.</p><p>'
            + html.escape(b.RULE["labels"])
            + '</p><table cellpadding="6"><tr><th>Patch</th><th>Centre (lat, lon)</th><th>First image</th><th>Second image</th></tr>'
            + "".join(rows)
            + "</table>"
        )
    b.write_new(
        b.OUT / "blank_review.json",
        dict(
            instructions="Make separate copies per reviewer; never enter model scores. Use unassessable when verification fails.",
            reviewer_id=None,
            records=[
                dict(
                    site_id=s["id"],
                    capture_dates_verified=None,
                    land_eligible=None,
                    clear_and_aligned=None,
                    label=None,
                    reason=None,
                    evidence_ids=None,
                )
                for s in sites
                if len(found[s["id"]]) == 2
            ],
        ),
    )
    print("paired:", result["paired"])


if __name__ == "__main__":
    main()
