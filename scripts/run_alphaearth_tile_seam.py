"""Fail-closed, write-once runner for the separately approved v2 protocol."""

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import Affine
from rasterio.windows import Window

from scripts import alphaearth_tile_seam as stats

ROOT = Path(__file__).resolve().parents[1]
DATA = Path("data/output/alphaearth_annual_change")
INV = DATA / "gcs_v1_inventory.json"
GRID = DATA / "alphaearth_annual_change_contract.json"
FULL = DATA / "gcs_full_v1/contract.json"
MAPS = FULL.parent / "cosine_change"
PROTOCOL = Path("data/output/alphaearth_seam_v2/protocol.json")
MANIFEST_SHA = "6f5a56846626ec2c058472ce4ee8707172c245da6642027f645591668fea3fbb"
WC_SHA = "e57aa50ed914ca8ce646797e0b430c1a4c723e51028b77c6312a1fc7810bcc4e"
BOUNDS = [
    (581920, 9262720, stats.SEAM, 9344640),
    (stats.SEAM, 9262720, 745760, 9344640),
]


def checked_json(path, expected):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"SHA-256 mismatch: {path.name}")
    return json.loads(raw)


def snapshot(src, dst, expected):
    # Decode only the very bytes that passed the gate, not a later reopen of
    # a mutable input or an unchecked GDAL sidecar next to the original file.
    with src.open("rb") as source, dst.open("xb") as copy:
        shutil.copyfileobj(source, copy, length=1 << 20)
    with dst.open("rb") as copy:
        if hashlib.file_digest(copy, "sha256").hexdigest() != expected:
            raise ValueError(f"SHA-256 mismatch: {src.name}")


def preflight(root, worldcover, stage):
    protocol = checked_json(root / PROTOCOL, stats.PROTOCOL_SHA256)
    pins = protocol["geometry_sources_repo_relative_sha256"]
    inv, grid, full = (
        checked_json(root / p, pins[p.as_posix()]) for p in (INV, GRID, FULL)
    )
    manifest = checked_json(root / MAPS / "manifest.json", MANIFEST_SHA)
    expected = set(stats.COMPARISONS) | {(2020, 2023)}
    maps = {tuple(row["years"]): row for row in manifest["comparisons"]}
    if (
        set(maps) != expected
        or len(manifest["comparisons"]) != len(expected)
        or manifest["annual_contract_sha256"] != pins[FULL.as_posix()]
    ):
        raise ValueError("Wrong change manifest comparisons or annual contract")
    for year in sorted({y for pair in expected for y in pair}):
        tiles = [t for t in inv["tiles"] if t["year"] == year]
        if sorted(tuple(t["native_bounds"]) for t in tiles) != BOUNDS or any(
            t["crs"] != "EPSG:32748" for t in tiles
        ):
            raise ValueError(f"Source tile seam/bounds or CRS changed in {year}")
    snapshot(worldcover, stage / "worldcover.tif", WC_SHA)
    for (a, b), row in maps.items():
        name = f"cosine_{a}_{b}.tif"
        snapshot(root / MAPS / name, stage / name, row["sha256"])
    return grid["frozen_reference_grid"], full["roi"], manifest


def sample_cover(ds, lon, lat):
    t = ds.transform
    if (
        ds.crs != rasterio.crs.CRS.from_epsg(4326)
        or ds.count != 1
        or t.b
        or t.d
        or not (t.a > 0 > t.e)
    ):
        raise ValueError("Unexpected WorldCover geometry")
    c = np.floor((lon - t.c) / t.a).astype(int)
    r = np.floor((lat - t.f) / t.e).astype(int)
    if c.min() < 0 or r.min() < 0 or c.max() >= ds.width or r.max() >= ds.height:
        raise ValueError("WorldCover does not cover the analysis grid")
    win = Window(c.min(), r.min(), np.ptp(c) + 1, np.ptp(r) + 1)
    return ds.read(1, window=win, masked=True)[np.ix_(r - r.min(), c - c.min())]


def analyse(stage, grid, roi, manifest):
    t = Affine(*grid["transform"])
    h, w = grid["height"], grid["width"]
    if grid["crs"] != "EPSG:4326" or t.b or t.d or not (t.a > 0 > t.e):
        raise ValueError("Expected north-up geographic analysis grid")
    lon = t.c + (np.arange(w) + 0.5) * t.a
    lat = t.f + (np.arange(h) + 0.5) * t.e
    west, south, east, north = roi
    inside = ((lon >= west) & (lon <= east))[None, :] & (
        (lat >= south) & (lat <= north)
    )[:, None]
    n = int(inside.sum())
    if manifest["inside_roi_centres"] != n:
        raise ValueError("ROI count mismatch")
    x, y = Transformer.from_crs(4326, 32748, always_xy=True).transform(
        *np.meshgrid(lon, lat)
    )
    rows = []
    with ExitStack() as stack:
        sources = {}
        for entry in manifest["comparisons"]:
            a, b = entry["years"]
            name = f"cosine_{a}_{b}"
            ds = stack.enter_context(rasterio.open(stage / (name + ".tif")))
            if (
                ds.shape != (h, w)
                or ds.transform != t
                or ds.crs != grid["crs"]
                or ds.count != 1
                or ds.dtypes != ("float32",)
                or ds.nodata != -9999
                or ds.descriptions != (name,)
                or ds.tags().get("contract_sha256")
                != manifest["annual_contract_sha256"]
                or entry["joint_valid"] != n
                or entry["total_cells"] != h * w
            ):
                raise ValueError(f"Map metadata mismatch: {name}")
            sources[a, b] = ds
        with rasterio.open(stage / "worldcover.tif") as wc:
            cover = sample_cover(wc, lon, lat)
        for years in stats.COMPARISONS:
            d = sources[years].read(1, masked=True)
            if not np.array_equal(~np.ma.getmaskarray(d), inside):
                raise ValueError(f"Change mask mismatch: {years}")
            v = d.compressed()
            if not np.isfinite(v).all() or v.min() < 0 or v.max() > 2:
                raise ValueError(f"Invalid cosine distance: {years}")
            rows.extend(stats.comparison_rows(years, d, x, y, cover))
            if years == (2020, 2025):
                endpoint = stats.headline(d, x)
    return {"strip_tests": rows, "endpoint_sensitivity": endpoint}


def revision(root):
    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(root), *args], text=True
        ).strip()

    if git("status", "--porcelain"):
        raise ValueError("Refusing to attribute results to a dirty working tree")
    git(
        "ls-files",
        "--error-unmatch",
        "scripts/run_alphaearth_tile_seam.py",
        "scripts/alphaearth_tile_seam.py",
    )
    return git("rev-parse", "HEAD")


def run(worldcover, approved_protocol_sha256):
    if approved_protocol_sha256 != stats.PROTOCOL_SHA256:
        raise ValueError("Explicit approval of the pinned protocol is required")
    commit = revision(ROOT)
    dest = ROOT / PROTOCOL.parent / "results.json"
    if dest.exists():
        raise FileExistsError(dest)
    with tempfile.TemporaryDirectory(dir=dest.parent) as folder:
        stage = Path(folder)
        grid, roi, manifest = preflight(ROOT, worldcover, stage)
        result = analyse(stage, grid, roi, manifest)
        if revision(ROOT) != commit:
            raise ValueError("Code revision changed during run")
        result["provenance"] = dict(
            code_commit=commit,
            protocol_sha256=stats.PROTOCOL_SHA256,
            change_manifest_sha256=MANIFEST_SHA,
            worldcover_sha256=WC_SHA,
            maps={str(row["years"]): row["sha256"] for row in manifest["comparisons"]},
        )
        tmp = stage / "results.json"
        tmp.write_text(
            json.dumps(result, allow_nan=False, indent=2) + "\n", encoding="utf-8"
        )
        os.link(tmp, dest)  # atomic publication; never replace an existing result
    return dest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worldcover", required=True, type=Path)
    parser.add_argument("--approved-protocol-sha256", required=True)
    args = parser.parse_args()
    print(run(args.worldcover, args.approved_protocol_sha256))
