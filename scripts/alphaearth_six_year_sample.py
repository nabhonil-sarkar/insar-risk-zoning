"""Versioned, GCS-only six-year edge transect; no full-area change inference."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import rasterio
from rasterio.warp import transform
from scripts import alphaearth_overview_check as ov
from scripts import alphaearth_gcs_pilot as g

OUT = g.OUT / "gcs_only_v1"
EDGES = [(r, c) for r in [1963, 1965, 1967] for c in [58, 60, 62, 1398, 1400, 1402]]
PAIRS = [(y, y + 1) for y in range(2020, 2025)] + [(2020, 2023), (2020, 2025)]
RULE = dict(
    schema="gcs_only_edge_v1",
    years=g.YEARS,
    reference_geometry_sha256=g.EXPECTED_REFERENCE_SHA256,
    inventory_sha256=ov.PINS[ov.INV],
    sample_rc=EDGES,
    comparisons=PAIRS,
    roi=[106.45, -6.54, 107.22, -6.01],
    clip="reference centre inside closed study rectangle; outside marked unavailable",
    method="same stored 20 m overview, nearest at frozen 30 m centres, decode all 64 axes; no EE values in annual data",
    budget_bytes_per_year=ov.PROTOCOL["tiff_byte_cap_per_stage"],
    gate="Require all 6 years, exactly one tile per location, no partial masks, common valid interior samples on both tiles for all pairs. Compare raw 2023 support to EE separately at boundary; not an EE-equivalence gate.",
    scope="small southern-edge transect only; not citywide coverage or validated urban development",
)


def support(q):
    v = g.dequantize(np.asarray(q, dtype="int8"))
    return v if np.isfinite(v).all() and np.linalg.norm(v) > 0 else None


def change(a, b):
    return float(
        np.clip(1 - np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)), 0, 2)
    )


def collect(year, protocol_hash):
    path = OUT / f"{year}.json"
    if path.exists():
        saved = ov.checked_json(path)
        if (
            saved["protocol_sha256"] != protocol_hash
            or saved["year"] != year
            or sorted(tuple(v["reference_rc"]) for v in saved["samples"])
            != sorted(EDGES)
        ):
            raise ValueError("Invalid checkpoint")
        return saved
    budget = [0]
    samples = []
    with rasterio.open(g.REFERENCE) as ref:
        xy = [ref.xy(*rc) for rc in EDGES]
        for tile in ov.checked_json(ov.INV)["tiles"]:
            if tile["year"] != year:
                continue
            xs, ys = transform(ref.crs, tile["crs"], *zip(*xy))
            w, s, e, n = tile["native_bounds"]
            hits = [
                (rc, x, y)
                for rc, x, y in zip(EDGES, xs, ys)
                if w <= x < e and s <= y < n
            ]
            if hits:
                samples.extend(ov.check_tile(tile, hits, ref, budget, source_only=True))
        if sorted(tuple(v["reference_rc"]) for v in samples) != sorted(EDGES):
            raise ValueError("Missing or duplicated cell")
        for v in samples:
            r, c = v["reference_rc"]
            lon, lat = ref.xy(r, c)
            w, s, e, n = RULE["roi"]
            v["inside"] = bool(w <= lon <= e and s <= lat <= n)
            v["valid"] = support(v["q"]) is not None
            if year == 2023:
                a = ref.read(window=((r, r + 1), (c, c + 1)), masked=True).filled(
                    np.nan
                )[:, 0, 0]
                v["legacy_unclipped_comparison"] = ov.compare(
                    a, g.dequantize(np.array(v["q"], dtype="int8"))
                )
    report = dict(
        year=year,
        protocol_sha256=protocol_hash,
        samples=samples,
        requested_tiff_bytes=budget[0],
    )
    g.write_new(path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["register", "run"])
    stage = parser.parse_args().stage
    ov.verify()
    path = OUT / "protocol.json"
    import json

    if stage == "register":
        g.write_new(path, RULE)
        return
    if (
        ov.checked_json(path) != json.loads(json.dumps(RULE))
        or (OUT / "comparison.json").exists()
    ):
        raise ValueError("Protocol drift or output exists")
    pin = g.sha256_file(path)
    with ThreadPoolExecutor(2) as pool:
        years = {
            v["year"]: {tuple(s["reference_rc"]): s for s in v["samples"]}
            for v in pool.map(lambda y: collect(y, pin), g.YEARS)
        }
    pairs = []
    for a, b in PAIRS:
        values = []
        for rc in EDGES:
            x, y = years[a][rc], years[b][rc]
            if x["inside"] and y["inside"] and x["valid"] and y["valid"]:
                values.append(
                    dict(rc=rc, cosine_change=change(support(x["q"]), support(y["q"])))
                )
        pairs.append(
            dict(
                years=[a, b],
                joint_valid=len(values),
                points=values,
                two_tiles=all(
                    len({years[t][tuple(v["rc"])]["source"] for v in values}) == 2
                    for t in (a, b)
                ),
            )
        )
    ok = all(p["two_tiles"] for p in pairs)
    g.write_new(
        OUT / "comparison.json",
        dict(
            protocol_sha256=pin,
            year_hashes={y: g.sha256_file(OUT / f"{y}.json") for y in years},
            decision="transect_only_pass" if ok else "hold",
            pairs=pairs,
        ),
    )
    if not ok:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
