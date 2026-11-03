"""Preregister and test the provider's first stored overview against the frozen EE grid."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.warp import transform

from scripts import alphaearth_gcs_pilot as g

INV = g.OUT / "gcs_v1_inventory.json"
OLD = g.OUT / "gcs_v1_pilot.json"
PINS = {
    INV: "be02701d9a3c539653f5d395fc1a5a659340217b56986e4df8ccd500f2c0e63e",
    OLD: "49f491d873e9362bc2c5a61502d97842adeca4cd1d4d2c18e62300354ed211bb",
    g.REFERENCE: g.EXPECTED_REFERENCE_SHA256,
    g.DEFAULT_OUTPUT: g.CONTRACT_SHA,
}
PROTOCOL = {
    "schema": "jakarta_provider_overview_v1",
    "year": 2023,
    "overview_factor": 2,
    "grid": "reference cell centre; nearest stored 20 m overview cell",
    "holdout_centres_lonlat": [[106.47, -6.45], [106.88, -6.28]],
    "confirmation_centres_lonlat": [
        [106.455, -6.52],
        [106.48, -6.24],
        [106.495, -6.24],
        [106.85, -6.025],
        [106.80, -6.14],
        [107.21, -6.52],
    ],
    "offsets_rows_cols": [-2, 0, 2],
    "atol": 1e-7,
    "rtol": 0,
    "holdout_rule": "all 18 jointly valid and all axes within atol, both tiles represented",
    "confirmation_rule": "all 54 mask states equal and every valid axis within atol; both tiles have valid samples and at least one jointly masked cell",
    "failure_rule": "hold; do not mix; evaluate separate all-GCS series including 2023",
    "tiff_byte_cap_per_stage": 480 * 1024**2,
    "pins": {str(k.as_posix()): v for k, v in PINS.items()},
}


def checked_json(path):
    return json.loads(path.read_text(encoding="utf8"))


def verify():
    for path, digest in PINS.items():
        if g.sha256_file(path) != digest:
            raise ValueError(f"Frozen input mismatch: {path}")


class CachedTIFF(io.RawIOBase):
    """Serve only the exact pre-fetched GDAL metadata and compressed TIFF blocks."""

    def __init__(self, segments, size):
        self.segments, self.size, self.pos = segments, size, 0

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = (0, self.pos, self.size)[whence] + offset
        if self.pos < 0:
            raise ValueError("Negative seek")
        return self.pos

    def read(self, size=-1):
        end = min(self.size, self.pos + size) if size >= 0 else self.size
        if end <= self.pos:
            return b""
        for start, data in self.segments.items():
            if start <= self.pos and end <= start + len(data):
                result = data[self.pos - start : end - start]
                self.pos = end
                return result
        raise IOError(f"GDAL requested a non-prefetched range [{self.pos}, {end})")


def fetch(obj, section):
    offset, length = section
    # Independent handles; aggregate bound is reserved before submitting requests.
    with g.RangeFile(obj, [0]) as f:
        f.seek(offset)
        return f.read(length)


def compare(a, b):
    def state(v):
        if np.isnan(v).all() or np.all(v == 0):
            return "masked"
        if not np.isfinite(v).all():
            return "invalid"
        return "valid"

    left, right = state(a), state(b)
    err = float(np.max(np.abs(a - b))) if left == right == "valid" else None
    return dict(
        reference_state=left,
        source_state=right,
        max_abs_error=err,
        passed=(left == right == "masked")
        or (err is not None and err <= PROTOCOL["atol"]),
    )


def check_tile(tile, hits, ref, budget, *, source_only=False):
    obj = tile["object"]
    prefix = 256 * 1024
    budget[0] += prefix
    if budget[0] > PROTOCOL["tiff_byte_cap_per_stage"]:
        raise ValueError("Header budget exceeded")
    header = fetch(obj, (0, prefix))
    with MemoryFile(header) as mem, mem.open(OVERVIEW_LEVEL="0") as overview:
        if (
            overview.res != (20, 20)
            or overview.shape != (4096, 4096)
            or overview.crs.to_string() != tile["crs"]
            or set(overview.dtypes) != {"int8"}
            or overview.nodata != -128
            or len(set(overview.block_shapes)) != 1
        ):
            raise ValueError("Unexpected stored overview metadata")
        with mem.open() as native:
            if (
                native.descriptions != g.BANDS
                or native.overviews(1)[0] != 2
                or native.res != (10, 10)
                or native.bounds != overview.bounds
            ):
                raise ValueError("Unexpected native band order / overview extent")
        rowscols = [overview.index(x, y) for _, x, y in hits]
        bh, bw = overview.block_shapes[0]
        sections = set()
        for by, bx in {(r // bh, c // bw) for r, c in rowscols}:
            for band in range(1, 65):
                start = int(
                    overview.get_tag_item(f"BLOCK_OFFSET_{bx}_{by}", "TIFF", bidx=band)
                    or 0
                )
                length = int(
                    overview.get_tag_item(f"BLOCK_SIZE_{bx}_{by}", "TIFF", bidx=band)
                    or 0
                )
                if (start, length) == (0, 0):
                    continue  # TIFF sparse block; GDAL handles its fill.
                if start < prefix or length <= 0 or start + length > int(obj["size"]):
                    raise ValueError("Bad TIFF block")
                sections.add((start, length))
    budget[0] += sum(n for _, n in sections)
    if budget[0] > PROTOCOL["tiff_byte_cap_per_stage"]:
        raise ValueError("TIFF byte budget exceeded")
    print(
        f"{obj['name']}: {len(hits)} cells, {len(sections)} compressed blocks",
        flush=True,
    )
    sections = sorted(sections)
    with ThreadPoolExecutor(10) as pool:
        segments = {
            0: header,
            **{
                offset: data
                for (offset, _), data in zip(
                    sections, pool.map(lambda s: fetch(obj, s), sections)
                )
            },
        }
    name = Path(obj["name"]).name

    def opener(path, mode="rb"):
        if Path(path).name != name:
            raise FileNotFoundError(path)
        return CachedTIFF(segments, int(obj["size"]))

    records = []
    with (
        rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"),
        rasterio.open(name, opener=opener, OVERVIEW_LEVEL="0") as src,
    ):
        for ((r, c), x, y), (i, j) in zip(hits, rowscols):
            q = src.read(window=((i, i + 1), (j, j + 1)))[:, 0, 0]
            if source_only:
                records.append(
                    dict(
                        reference_rc=[r, c],
                        source_rc=[i, j],
                        source=obj["name"],
                        q=q.tolist(),
                    )
                )
                continue
            original = ref.read(window=((r, r + 1), (c, c + 1)), masked=True).filled(
                np.nan
            )[:, 0, 0]
            records.append(
                dict(
                    reference_rc=[r, c],
                    source_rc=[i, j],
                    source=obj["name"],
                    **compare(original, g.dequantize(q)),
                )
            )
    return records


def run(stage):
    inv = checked_json(INV)
    records, budget = [], [0]
    with rasterio.open(g.REFERENCE) as ref:
        centres = PROTOCOL[stage + "_centres_lonlat"]
        d = PROTOCOL["offsets_rows_cols"]
        points = [
            (r + dr, c + dc)
            for r, c in (ref.index(*xy) for xy in centres)
            for dr in d
            for dc in d
        ]
        previous = {tuple(s["reference_rc"]) for s in checked_json(OLD)["samples"]}
        if stage == "confirmation":
            previous.update(
                (r + dr, c + dc)
                for r, c in (
                    ref.index(*xy) for xy in PROTOCOL["holdout_centres_lonlat"]
                )
                for dr in d
                for dc in d
            )
        if previous.intersection(points) or len(points) != len(set(points)):
            raise ValueError("Non-independent locations")
        xy = [ref.xy(r, c) for r, c in points]
        for tile in (t for t in inv["tiles"] if t["year"] == 2023):
            xs, ys = transform(ref.crs, tile["crs"], *zip(*xy))
            w, s, e, n = tile["native_bounds"]
            hits = [
                (rc, x, y)
                for rc, x, y in zip(points, xs, ys)
                if w <= x < e and s <= y < n
            ]
            if hits:
                records.extend(check_tile(tile, hits, ref, budget))
    if sorted(tuple(v["reference_rc"]) for v in records) != sorted(points):
        raise ValueError("Incomplete coverage")
    valid = [r for r in records if r["max_abs_error"] is not None]
    masked = sum(r["reference_state"] == r["source_state"] == "masked" for r in records)
    passed = (
        all(r["passed"] for r in records)
        and len({r["source"] for r in valid}) == 2
        and (len(valid) == len(records) if stage == "holdout" else masked > 0)
    )
    return dict(
        stage=stage,
        samples=records,
        requested_tiff_bytes=budget[0],
        joint_valid=len(valid),
        joint_masked=masked,
        decision=(
            "advance_to_confirmation" if stage == "holdout" else "sample_confirmed_only"
        )
        if passed
        else "hold_do_not_mix",
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=["register", "holdout", "confirmation"])
    p.add_argument("--out", type=Path, default=g.OUT / "overview_v1")
    args = p.parse_args()
    verify()
    path = args.out / "protocol.json"
    if args.stage == "register":
        g.write_new(path, PROTOCOL)
        print(g.sha256_file(path))
        return
    if checked_json(path) != PROTOCOL:
        raise ValueError("Protocol drift")
    dest = args.out / (args.stage + ".json")
    if dest.exists():
        raise FileExistsError(dest)
    if args.stage == "confirmation":
        hold = checked_json(args.out / "holdout.json")
        if hold["decision"] != "advance_to_confirmation" or hold[
            "protocol_sha256"
        ] != g.sha256_file(path):
            raise ValueError("Confirmation not unlocked")
    result = run(args.stage)
    result["protocol_sha256"] = g.sha256_file(path)
    g.write_new(dest, result)
    print(result["decision"], result["joint_valid"], result["requested_tiff_bytes"])
    if result["decision"] == "hold_do_not_mix":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
