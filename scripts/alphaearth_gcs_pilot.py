"""Read-only GCS pilot on the frozen Jakarta grid. No annual raster exports."""

import argparse
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.warp import transform, transform_bounds
from shapely.geometry import box

from scripts.prepare_alphaearth_annual_change import (
    DEFAULT_OUTPUT,
    EXPECTED_REFERENCE_SHA256,
    sha256_file,
)

BUCKET = "alphaearth_foundations"
BASE = "satellite_embedding/v1/annual/"
INDEX = BASE + "aef_index.gpkg"
YEARS = list(range(2020, 2026))
REFERENCE = Path("data/raw/embeddings/AlphaEarth_Jakarta_Wide_30m_2023.tif")
CONTRACT_SHA = "a43b2fff3dd8dbfdfe55f3c79be1add90e17360a2918893e43f4e8a25ec74c63"
OUT = DEFAULT_OUTPUT.parent
BANDS = tuple(f"A{i:02}" for i in range(64))
# Two fixed land patches, on opposite sides of the native UTM tile seam.
# Nearest native pixel at each reference centre, as specified in the EE contract.
CENTRES = [(106.465, -6.30), (106.84, -6.20)]
DELTAS = (-2, 0, 2)
ATOL = 1e-7  # Numerical reproduction, not a scientific change threshold.
BYTE_CAP = 192 * 1024**2  # All source TIFF requests combined.


def metadata(name):
    url = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/" + quote(
        name, safe=""
    )
    with urlopen(url + "?fields=name,generation,size,md5Hash", timeout=30) as response:
        return json.load(response)


def media(obj):
    return (
        f"https://storage.googleapis.com/{BUCKET}/"
        + quote(obj["name"])
        + "?generation="
        + obj["generation"]
    )


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, allow_nan=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)


def inventory():
    index = metadata(INDEX)
    with rasterio.open(REFERENCE) as ref:
        bounds = tuple(ref.bounds)
    area = box(*bounds)
    print("Querying the official tile index on the frozen grid...", flush=True)
    table = gpd.read_file("/vsicurl/" + media(index), bbox=bounds, engine="pyogrio")
    if table.crs.to_epsg() != 4326:
        raise ValueError("Unexpected index CRS")
    tiles = []
    for row in table[table.year.isin(YEARS)].sort_values(["year", "path"]).itertuples():
        if not row.geometry.intersection(area).area:
            continue
        prefix = f"gs://{BUCKET}/{BASE}{row.year}/48S/"
        if not row.path.startswith(prefix) or row.crs != "EPSG:32748":
            raise ValueError(f"Unexpected source: {row.path}")
        obj = metadata(row.path.removeprefix(f"gs://{BUCKET}/"))
        tiles.append(
            dict(
                year=int(row.year),
                object=obj,
                crs=row.crs,
                native_bounds=[
                    row.utm_west,
                    row.utm_south,
                    row.utm_east,
                    row.utm_north,
                ],
            )
        )
    if {t["year"] for t in tiles} != set(YEARS) or len(
        {t["object"]["name"] for t in tiles}
    ) != len(tiles):
        raise ValueError("Incomplete or duplicated annual inventory")
    return dict(
        schema="gcs_pilot_v1",
        timestamp=datetime.now(timezone.utc).isoformat(),
        index=index,
        reference_sha256=EXPECTED_REFERENCE_SHA256,
        historical_contract_sha256=CONTRACT_SHA,
        bounds=bounds,
        tiles=tiles,
        projected_grid_envelope=transform_bounds(
            "EPSG:4326", "EPSG:32748", *bounds, densify_pts=101
        ),
        attribution="The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google DeepMind.",
    )


def dequantize(q):
    q = np.asarray(q)
    if q.dtype != np.int8 or q.shape[-1] != 64:
        raise ValueError("Expected signed bytes with 64 axes")
    mask = q == -128
    if np.any(mask.any(axis=-1) != mask.all(axis=-1)):
        raise ValueError("Partial source vector mask")
    x = np.where(mask, np.nan, q.astype(float))
    return np.sign(x) * (x / 127.5) ** 2


class RangeFile(io.RawIOBase):
    """Seekable generation-pinned HTTP file. Never accept a whole-object fallback."""

    def __init__(self, obj, budget):
        self.obj, self.budget, self.pos = obj, budget, 0
        self.size = int(obj["size"])
        self.header = b""

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        pos = (0, self.pos, self.size)[whence] + offset
        if pos < 0:
            raise ValueError("Negative seek")
        self.pos = pos
        return pos

    def read(self, size=-1):
        n = min(size if size >= 0 else self.size, self.size - self.pos)
        if n <= 0:
            return b""
        start = self.pos
        if start + n <= len(self.header):
            self.pos += n
            return self.header[start : self.pos]
        fetch = min(self.size, max(n, 256 * 1024)) if start == 0 else n
        if fetch > 4 * 1024**2 or self.budget[0] + fetch > BYTE_CAP:
            raise ValueError("Bounded pilot transfer limit exceeded")
        end = start + fetch - 1
        request = Request(media(self.obj), headers={"Range": f"bytes={start}-{end}"})
        self.budget[0] += fetch
        with urlopen(request, timeout=45) as resp:
            if (
                resp.status != 206
                or resp.headers.get("Content-Range")
                != f"bytes {start}-{end}/{self.size}"
            ):
                raise IOError("Server did not honor the exact byte range")
            data = resp.read(fetch + 1)
        if len(data) != fetch:
            raise IOError("Incomplete range response")
        if start == 0:
            self.header = data
        self.pos += n
        return data[:n]


def pilot(inv):
    budget, records = [0], []
    with rasterio.open(REFERENCE) as ref:
        if ref.descriptions != BANDS:
            raise ValueError("Reference band order")
        points = []
        for lon, lat in CENTRES:
            r, c = ref.index(lon, lat)
            points.extend((r + dr, c + dc) for dr in DELTAS for dc in DELTAS)
        for tile in (t for t in inv["tiles"] if t["year"] == 2023):
            obj = tile["object"]
            xy = [ref.xy(r, c) for r, c in points]
            xs, ys = transform(ref.crs, tile["crs"], *zip(*xy))
            west, south, east, north = tile["native_bounds"]
            hits = [
                (pt, x, y)
                for pt, x, y in zip(points, xs, ys)
                if west < x < east and south < y < north
            ]
            if not hits:
                continue
            filename = Path(obj["name"]).name

            def opener(path, mode="rb"):
                if Path(path).name != filename:
                    raise FileNotFoundError(path)
                return RangeFile(obj, budget)

            with (
                rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"),
                rasterio.open(filename, opener=opener, driver="GTiff") as src,
            ):
                if (
                    src.descriptions != BANDS
                    or set(src.dtypes) != {"int8"}
                    or src.nodata != -128
                    or src.crs.to_string() != tile["crs"]
                    or src.res != (10, 10)
                    or sorted((src.bounds.bottom, src.bounds.top)) != [south, north]
                    or sorted((src.bounds.left, src.bounds.right)) != [west, east]
                ):
                    raise ValueError("Unexpected source metadata")
                ij = [src.index(x, y) for _, x, y in hits]
                rows, cols = zip(*ij)
                window = ((min(rows), max(rows) + 1), (min(cols), max(cols) + 1))
                if max(max(rows) - min(rows), max(cols) - min(cols)) > 64:
                    raise ValueError("Pilot window too large")
                print(
                    f"Reading {len(hits)} reference locations from {filename}...",
                    flush=True,
                )
                patch = src.read(window=window)
                print(
                    f"Cumulative source TIFF requests: {budget[0]:,} bytes", flush=True
                )
                for (r, c), x, y in hits:
                    i, j = src.index(x, y)
                    q = patch[:, i - min(rows), j - min(cols)]
                    decoded = dequantize(q)
                    original = ref.read(
                        window=((r, r + 1), (c, c + 1)), masked=True
                    ).filled(np.nan)[:, 0, 0]
                    common = (
                        np.isfinite(original).all()
                        and np.isfinite(decoded).all()
                        and np.linalg.norm(original) > 0
                        and np.linalg.norm(decoded) > 0
                    )
                    err = float(np.max(np.abs(original - decoded))) if common else None
                    records.append(
                        dict(
                            reference_rc=[int(r), int(c)],
                            source_rc=[int(i), int(j)],
                            source=obj["name"],
                            max_abs_error=err,
                            passed=err is not None and err <= ATOL,
                        )
                    )
    if sorted(tuple(v["reference_rc"]) for v in records) != sorted(points):
        raise ValueError("Missing or multiply covered pilot cells")
    return dict(
        schema="gcs_pilot_v1",
        method="native nearest at reference pixel centre; no aggregation or overview",
        centres=CENTRES,
        deltas=DELTAS,
        atol=ATOL,
        byte_cap=BYTE_CAP,
        requested_tiff_bytes=budget[0],
        samples=records,
        decision="sample_match_only"
        if all(v["passed"] for v in records)
        else "hold_do_not_mix",
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=["inventory", "pilot"])
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args()
    inv_path = args.out / "gcs_v1_inventory.json"
    result_path = args.out / "gcs_v1_pilot.json"
    if (inv_path if args.stage == "inventory" else result_path).exists():
        p.error("Output already exists; use --out with a new directory for a new run.")
    if (
        sha256_file(REFERENCE) != EXPECTED_REFERENCE_SHA256
        or sha256_file(DEFAULT_OUTPUT) != CONTRACT_SHA
    ):
        raise ValueError("Frozen input checksum mismatch")
    if args.stage == "inventory":
        result = inventory()
        write_new(inv_path, result)
        print({y: sum(t["year"] == y for t in result["tiles"]) for y in YEARS})
    else:
        inv = json.loads(inv_path.read_text(encoding="utf-8"))
        if (
            inv.get("schema") != "gcs_pilot_v1"
            or inv.get("reference_sha256") != EXPECTED_REFERENCE_SHA256
            or inv.get("historical_contract_sha256") != CONTRACT_SHA
        ):
            raise ValueError("Incompatible inventory contract")
        result = pilot(inv)
        result["inventory_sha256"] = sha256_file(inv_path)
        write_new(result_path, result)
        print(result["decision"], result["requested_tiff_bytes"])
        if result["decision"] == "hold_do_not_mix":
            raise SystemExit(2)


if __name__ == "__main__":
    main()
