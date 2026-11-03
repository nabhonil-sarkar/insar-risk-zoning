"""Freeze actual Sentinel-2 Collection 1 L2A candidate scenes; not clear-pixel counts."""

from urllib.parse import urlsplit
import requests
from scripts import urban_change_benchmark as b
from scripts.audit_urban_reference import PIN


def inventory(year):
    url = "https://earth-search.aws.element84.com/v1/search"
    params = dict(
        collections="sentinel-2-c1-l2a",
        bbox=",".join(map(str, b.ROI)),
        datetime=f"{year}-06-01T00:00:00Z/{year}-09-30T23:59:59Z",
        limit=50,
    )
    entries = {}
    expected = None
    pages = set()
    while url:
        if urlsplit(url).netloc != "earth-search.aws.element84.com" or url in pages:
            raise ValueError("Unsafe or repeated next link")
        pages.add(url)
        resp = requests.get(url, params=params, timeout=45)
        resp.raise_for_status()
        obj = resp.json()
        if expected is None:
            expected = obj["numberMatched"]
        for item in obj["features"]:
            p = item["properties"]
            assets = {}
            for key, name in [
                ("red", "B04"),
                ("nir", "B08"),
                ("swir16", "B11"),
                ("scl", "SCL"),
            ]:
                a = item["assets"][key]
                meta = a["raster:bands"][0]
                if not a["href"].endswith("/" + name + ".tif") or "nodata" not in meta:
                    raise ValueError("Unexpected asset contract")
                if key != "scl" and (
                    "scale" not in meta or a["eo:bands"][0]["name"] != name
                ):
                    raise ValueError("Unknown radiometry")
                assets[key] = dict(
                    href=a["href"],
                    nodata=meta["nodata"],
                    scale=meta.get("scale", 1),
                    offset=meta.get("offset", 0),
                    native_metres=meta["spatial_resolution"],
                )
            if item["id"] in entries:
                raise ValueError("Duplicate scene")
            entries[item["id"]] = dict(
                id=item["id"],
                updated=p.get("updated"),
                datetime=p["datetime"],
                geometry=item["geometry"],
                cloud_cover=p["eo:cloud_cover"],
                assets=assets,
            )
        url = next(
            (link["href"] for link in obj["links"] if link["rel"] == "next"), None
        )
        params = None
    if len(entries) != expected or not entries:
        raise ValueError("Incomplete scene inventory")
    return sorted(
        entries.values(), key=lambda v: (v["datetime"][:10], v["cloud_cover"], v["id"])
    )


def main():
    if b.sha256_file(b.OUT / "protocol.json") != PIN:
        raise ValueError("Protocol drift")
    path = b.OUT / "sentinel2_inventory.json"
    if path.exists():
        raise FileExistsError(path)
    scenes = {str(y): inventory(y) for y in (2020, 2025)}
    b.write_new(
        path, dict(protocol_sha256=PIN, collection="sentinel-2-c1-l2a", scenes=scenes)
    )
    print({k: len(v) for k, v in scenes.items()})


if __name__ == "__main__":
    main()
