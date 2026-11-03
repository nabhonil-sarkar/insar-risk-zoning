"""Build the six pinned GCS-only Jakarta rasters. 2023 must pass before other years."""

import bisect
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import os
from pathlib import Path
import tempfile
import threading
import time

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.io import MemoryFile
import requests

from scripts import alphaearth_gcs_pilot as g
from scripts import alphaearth_overview_check as ov
from scripts import alphaearth_six_year_sample as edge

OUT = g.OUT / "gcs_full_v1"
CACHE = OUT / "ranges"
VOLUME = edge.OUT / "full_grid_volume.json"
OVDIR = g.OUT / "overview_v1"
PINS = {
    **ov.PINS,
    VOLUME: "2e6277b4ac82ac66d80254f4c39e4cc0636953d5fd70fce1d9acf96d4a4a261b",
    edge.OUT
    / "protocol.json": "aeb1a2c3e2763f3964c9c6bcf5bf8914063dc30370e5412e0bb2b190137ed07e",
    edge.OUT
    / "comparison.json": "5a8d4d67e6d63a17ba10ba9c9fe82d652e0c7eeefe4aa98f3d3064223ad7b8aa",
    OVDIR
    / "holdout.json": "25b9a272190e799b59439e10114087ced4b810d45f22725c41dd58cd7c6bc6e5",
    OVDIR
    / "confirmation.json": "1fcd1d31ac73dff348a3b929189cee2f3178b758c09a55d63bf5a04d5c3d01a5",
}
ATTR = "The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google DeepMind."
RULE = dict(
    schema="gcs_full_v1",
    years=g.YEARS,
    roi=edge.RULE["roi"],
    geometry="frozen EPSG:4326 reference pixel centres; closed ROI; exactly one native tile per included centre",
    sampling="pinned 20 m stored overview; inverse affine floor; keep provider bytes without interpolation; A00..A63",
    encoding="int8; -128 nodata for all axes, zero vectors excluded; decode sign(q)*(q/127.5)^2 before use",
    gate="exact grid and band labels; no partial masks or overlapping/unassigned interior centres; valid support on both sides of seam and every interior border; all registered transect checks, plus 72 decoded checks in 2023; never mix legacy values",
    source_hashes={p.as_posix(): h for p, h in PINS.items()},
    attribution=ATTR,
)
_local = threading.local()


def verify_inputs():
    hashes = {
        **PINS,
        **{
            edge.OUT / f"{y}.json": h
            for y, h in ov.checked_json(edge.OUT / "comparison.json")[
                "year_hashes"
            ].items()
        },
    }
    for p, h in hashes.items():
        if g.sha256_file(p) != h:
            raise ValueError(f"Input checksum mismatch: {p}")


def merge(parts):
    runs = []
    for off, size in sorted(set(parts)):
        end = off + size
        if runs and off < runs[-1][1]:
            raise ValueError("Overlapping TIFF ranges")
        if runs and off - runs[-1][1] <= 16 and end - runs[-1][0] <= 4 * 1024**2:
            runs[-1] = (runs[-1][0], end)
        else:
            runs.append((off, end))
    return [(a, b - a) for a, b in runs]


def cached(obj, span):
    start, n = span
    root = CACHE / Path(obj["name"]).stem / obj["generation"]
    root.mkdir(parents=True, exist_ok=True)
    prefix = f"{start}_{n}_"
    found = list(root.glob(prefix + "*.bin"))
    if found:
        if (
            len(found) != 1
            or found[0].stat().st_size != n
            or g.sha256_file(found[0]) != found[0].stem.split("_")[-1]
        ):
            raise ValueError("Corrupt or ambiguous range cache")
        return found[0]
    if not hasattr(_local, "http"):
        _local.http = requests.Session()
    end = start + n - 1
    for attempt in range(4):
        try:
            with _local.http.get(
                g.media(obj),
                headers={
                    "Range": f"bytes={start}-{end}",
                    "Accept-Encoding": "identity",
                },
                stream=True,
                timeout=(15, 60),
            ) as resp:
                resp.raise_for_status()
                if (
                    resp.status_code != 206
                    or resp.headers.get("Content-Range")
                    != f"bytes {start}-{end}/{obj['size']}"
                ):
                    raise ValueError("Range request not honored")
                data = resp.raw.read(n + 1)
                if len(data) != n:
                    raise IOError("Short response")
            break
        except (OSError, requests.RequestException):
            if attempt == 3:
                raise
            time.sleep(1 + attempt)
    path = root / (prefix + hashlib.sha256(data).hexdigest() + ".bin")
    with tempfile.NamedTemporaryFile(dir=root, delete=False) as tmp:
        tmp.write(data)
    try:
        os.link(tmp.name, path)
    finally:
        Path(tmp.name).unlink()
    return path


class DiskRanges(io.RawIOBase):
    def __init__(self, paths, size):
        self.paths, self.starts, self.size, self.pos = paths, sorted(paths), size, 0

    def tell(self):
        return self.pos

    def seek(self, o, whence=0):
        self.pos = (0, self.pos, self.size)[whence] + o
        if self.pos < 0:
            raise ValueError("Negative seek")
        return self.pos

    def read(self, size=-1):
        n = min(self.size - self.pos, size if size >= 0 else self.size)
        if n <= 0:
            return b""
        idx = bisect.bisect_right(self.starts, self.pos) - 1
        if idx < 0:
            raise IOError("Uncached data")
        start = self.starts[idx]
        with self.paths[start].open("rb") as f:
            f.seek(self.pos - start)
            data = f.read(n)
        if len(data) != n:
            raise IOError(f"Uncached TIFF range {self.pos}:{self.pos + n}")
        self.pos += n
        return data


def grid(ref):
    aff = ref.transform
    if ref.crs.to_epsg() != 4326 or aff.b or aff.d:
        raise ValueError("Unexpected reference geometry")
    lon = aff.c + (np.arange(ref.width) + 0.5) * aff.a
    lat = aff.f + (np.arange(ref.height) + 0.5) * aff.e
    w, s, e, n = RULE["roi"]
    inside = (lat[:, None] >= s) & (lat[:, None] <= n) & (lon >= w) & (lon <= e)
    yy, xx = np.nonzero(inside)
    x, y = Transformer.from_crs(ref.crs, 32748, always_xy=True).transform(
        lon[xx], lat[yy]
    )
    return inside, yy, xx, x, y


def semantic_mask(q):
    nodata = q == -128
    if np.any(nodata.any(axis=-1) != nodata.all(axis=-1)):
        raise ValueError("Partial mask")
    return (~nodata[..., 0]) & q.any(axis=-1)


def populate(tile, limit, x, y, out_rc, output):
    obj = tile["object"]
    prefix = cached(obj, (0, 262144))
    with (
        MemoryFile(prefix.read_bytes()) as mem,
        mem.open() as native,
        mem.open(OVERVIEW_LEVEL="0") as src,
    ):
        if (
            native.descriptions != g.BANDS
            or native.overviews(1)[0] != 2
            or src.res != (20, 20)
            or src.crs.to_epsg() != 32748
            or src.count != 64
            or src.nodata != -128
            or set(src.dtypes) != {"int8"}
            or native.bounds != src.bounds
            or src.shape != (4096, 4096)
            or len(set(src.block_shapes)) != 1
        ):
            raise ValueError("Source overview metadata mismatch")
        inv = ~src.transform
        j, i = inv * (x, y)
        i, j = np.floor(i).astype("int32"), np.floor(j).astype("int32")
        if min(i.min(), j.min()) < 0 or i.max() >= src.height or j.max() >= src.width:
            raise ValueError("Source index out of bounds")
        bh, bw = src.block_shapes[0]
        ncols = (src.width + bw - 1) // bw
        ids = (i // bh) * ncols + j // bw
        blocks = np.unique(ids)
        ranges = []
        for k in blocks:
            by, bx = divmod(int(k), ncols)
            for band in range(1, 65):
                off = int(
                    src.get_tag_item(f"BLOCK_OFFSET_{bx}_{by}", "TIFF", bidx=band) or 0
                )
                size = int(
                    src.get_tag_item(f"BLOCK_SIZE_{bx}_{by}", "TIFF", bidx=band) or 0
                )
                if (off, size) == (0, 0):
                    continue
                if off < 262144 or size <= 0 or off + size > int(obj["size"]):
                    raise ValueError("Invalid block offsets")
                ranges.append((off, size))
    if (
        sum(n for _, n in ranges) > limit["payload_bytes"]
        or len(blocks) > limit["spatial_blocks"]
    ):
        raise ValueError("Preflight volume exceeded")
    runs = merge(ranges)
    print(
        f"{tile['year']}: {len(blocks)} blocks, {len(runs)} requests, {sum(n for _, n in runs) / 1e6:.1f} MB",
        flush=True,
    )
    with ThreadPoolExecutor(16) as pool:
        files = list(pool.map(lambda s: cached(obj, s), runs))
    paths = {a: f for (a, _), f in zip(runs, files)}
    paths[0] = prefix
    name = Path(obj["name"]).name

    def opener(path, mode="rb"):
        if Path(path).name != name:
            raise FileNotFoundError(path)
        return DiskRanges(paths, int(obj["size"]))

    with (
        rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_CACHEMAX=128 * 1024**2
        ),
        rasterio.open(name, opener=opener, OVERVIEW_LEVEL="0") as src,
    ):
        for k in blocks:
            by, bx = divmod(int(k), ncols)
            mask = ids == k
            block = src.read(
                window=((by * bh, (by + 1) * bh), (bx * bw, (bx + 1) * bw))
            )
            q = block[:, i[mask] % bh, j[mask] % bw].T
            q[~semantic_mask(q)] = -128
            output[out_rc[0][mask], out_rc[1][mask]] = q
    return dict(
        name=obj["name"],
        generation=obj["generation"],
        assigned=len(x),
        blocks=len(blocks),
        payload=sum(n for _, n in ranges),
    )


def band_path(year):
    return OUT / f"Jakarta_GCS20m_on30m_{year}_qint8.tif"


def write_year(year, geom, ref, tiles, limits, token):
    dst = band_path(year)
    qa = OUT / f"{year}_qa.json"
    if qa.exists():
        old = ov.checked_json(qa)
        if (
            old["decision"] != "pass"
            or old["contract_sha256"] != token
            or g.sha256_file(dst) != old["sha256"]
        ):
            raise ValueError("Output fingerprint mismatch")
        return
    if dst.exists():
        raise FileExistsError(dst)
    inside, yy, xx, x, y = geom
    assignment = np.zeros(inside.shape, np.uint8)
    output = np.full((*inside.shape, 64), -128, dtype="int8")
    sources = []
    for num, t in enumerate(tiles, 1):
        w, s, e, n = t["native_bounds"]
        hit = (x >= w) & (x < e) & (y >= s) & (y < n)
        rc = (yy[hit], xx[hit])
        if not hit.any() or assignment[rc].any():
            raise ValueError("Ambiguous tile ownership")
        assignment[rc] = num
        sources.append(
            populate(t, limits[t["object"]["name"]], x[hit], y[hit], rc, output)
        )
    if not np.array_equal(assignment != 0, inside):
        raise ValueError("Unassigned interior centres")
    valid = output[:, :, 0] != -128
    seam = (assignment[:, 1:] != assignment[:, :-1]) & inside[:, 1:] & inside[:, :-1]
    if not seam.any():
        raise ValueError("Missing tile join")
    ys, xs = np.nonzero(inside)
    edges = [
        valid[ys.min(), xs.min() : xs.max() + 1],
        valid[ys.max(), xs.min() : xs.max() + 1],
        valid[ys.min() : ys.max() + 1, xs.min()],
        valid[ys.min() : ys.max() + 1, xs.max()],
    ]
    seam_counts = [int((seam & v).sum()) for v in (valid[:, :-1], valid[:, 1:])]
    if not all(seam_counts) or not all(a.any() for a in edges):
        raise ValueError("Empty join side or ROI edge")
    with tempfile.TemporaryDirectory(dir=OUT) as temp:
        tmp = Path(temp) / dst.name
        with rasterio.open(
            tmp,
            "w",
            driver="GTiff",
            width=ref.width,
            height=ref.height,
            transform=ref.transform,
            crs=ref.crs,
            count=64,
            dtype="int8",
            nodata=-128,
            tiled=True,
            blockxsize=128,
            blockysize=128,
            compress="zstd",
            interleave="pixel",
        ) as f:
            f.descriptions = g.BANDS
            f.update_tags(
                encoding=RULE["encoding"],
                contract_sha256=token,
                attribution=ATTR,
                year=str(year),
            )
            for _, win in f.block_windows(1):
                rr, cc = win.toslices()
                f.write(output[rr, cc].transpose(2, 0, 1), window=win)
        with rasterio.open(tmp) as f:
            if (
                f.crs != ref.crs
                or f.transform != ref.transform
                or f.shape != ref.shape
                or f.descriptions != g.BANDS
                or set(f.dtypes) != {"int8"}
                or f.nodata != -128
            ):
                raise ValueError("Output grid or encoding mismatch")
            for _, win in f.block_windows(1):
                rr, cc = win.toslices()
                if not np.array_equal(
                    f.read(window=win).transpose(1, 2, 0), output[rr, cc]
                ):
                    raise ValueError("Raster roundtrip mismatch")
            transect = ov.checked_json(edge.OUT / f"{year}.json")["samples"]
            legacy_checks = 0
            for p in transect:
                r, c = p["reference_rc"]
                expected = (
                    np.array(p["q"], dtype="int8")
                    if p["inside"] and p["valid"]
                    else np.full(64, -128)
                )
                if not np.array_equal(output[r, c], expected):
                    raise ValueError("Frozen transect mismatch")
            if year == 2023:
                for stage in ["holdout", "confirmation"]:
                    for p in ov.checked_json(OVDIR / (stage + ".json"))["samples"]:
                        legacy_checks += 1
                        r, c = p["reference_rc"]
                        orig = ref.read(window=((r, r + 1), (c, c + 1)))[:, 0, 0]
                        if not np.allclose(
                            g.dequantize(output[r, c]), orig, rtol=0, atol=1e-7
                        ):
                            raise ValueError("2023 legacy sample mismatch")
        digest = g.sha256_file(tmp)
        os.link(tmp, dst)
    g.write_new(
        qa,
        dict(
            year=year,
            contract_sha256=token,
            sha256=digest,
            decision="pass",
            sources=sources,
            inside=int(inside.sum()),
            valid=int(valid.sum()),
            outside=int((~inside).sum()),
            missing_inside=int((inside & ~valid).sum()),
            seam_rows=int(seam.sum()),
            seam_valid_left_right=seam_counts,
            edge_valid_top_bottom_left_right=[int(a.sum()) for a in edges],
            transect_checks=len(transect),
            legacy_value_checks=legacy_checks,
        ),
    )
    print(f"{year}: PASS, {valid.sum():,} valid, sha256 {digest}", flush=True)


def main():
    verify_inputs()
    protocol = OUT / "contract.json"
    if not protocol.exists():
        g.write_new(protocol, RULE)
    if ov.checked_json(protocol) != RULE:
        raise ValueError("Contract drift")
    token = g.sha256_file(protocol)
    tiles = ov.checked_json(ov.INV)["tiles"]
    limits = {v["name"]: v for v in ov.checked_json(VOLUME)["tiles"]}
    with rasterio.open(g.REFERENCE) as ref:
        geom = grid(ref)
        for year in [2023, 2020, 2021, 2022, 2024, 2025]:
            write_year(
                year, geom, ref, [v for v in tiles if v["year"] == year], limits, token
            )


if __name__ == "__main__":
    main()
