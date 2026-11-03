"""Freeze the endpoint interpretation experiment and select sites from geometry alone."""

import argparse
import hashlib
import json
import numpy as np
from pyproj import Transformer
import rasterio
from shapely.geometry import box, mapping

from scripts.alphaearth_gcs_pilot import (
    OUT as ANNUAL,
    REFERENCE,
    EXPECTED_REFERENCE_SHA256,
    sha256_file,
    write_new,
)

OUT = ANNUAL.parent / "urban_benchmark_v1"
ROI = [106.45, -6.54, 107.22, -6.01]
SEED = "jakarta-endpoint-v1-20261103"
RULE = {
    "schema": "jakarta_urban_gain_benchmark_v1",
    "seed": SEED,
    "roi": ROI,
    "grid_sha256": EXPECTED_REFERENCE_SHA256,
    "endpoint_years": [2020, 2025],
    "estimand": "Visible gain in built surface between independently dated endpoint images. Sampled inland patches in complete blocks only; not citywide area estimation, deformation, or risk.",
    "sampling": "EPSG:32748 5 km blocks anchored at multiples of 5000 m; four corners inside geographic ROI. Select 100 by SHA256 rank. Assign first 50 by independent split hash to evaluation, rest development. Three hash-proposed centres/block, 550 m inset before snapping, >=1000 m spacing after snapping. No scores, labels or imagery consulted; no replacements.",
    "support": "Fixed 3x3 frozen-grid cells (nominal 90x90 m); context outside only for orientation. Reject site if >50% permanent/open water at either endpoint, unclear land/water, cloud, shadow, poor registration, mixed dates, or unreadable detail. Water-to-land reclamation is outside the primary estimand.",
    "source": "Esri World Imagery Wayback zoom 19 metadata; actual commercial high-resolution optical capture in each target calendar year, native resolution >0 and <=2 m, identified WV/GeoEye/QuickBird/Pleiades sensor. Same-year release/thumbnail alone not evidence. Inspect whole patch at both endpoints. Sentinel/Landsat/AlphaEarth or derived indices cannot supply reference labels.",
    "search": "Last release in each calendar half-year from endpoint December through 2026-11-03 (include incomplete final half). Earliest eligible checked release per endpoint, no site substitutions. Require consistent source/date/resolution polygons across whole patch; manual verification required. Save metadata and viewer links, not imagery.",
    "labels": "Two reviewers independently examine both dated views blinded to split, embeddings, indices and each other's decisions. Positive: >=25% of patch newly occupied by buildings or paved infrastructure. Negative: <10% newly occupied (including unchanged or lost built area). 10%-<25%, bare ground without confirmed built use, unclear alignment or disagreement: exclude as uncertain. Record dates, source, reviewer ID, reason and evidence IDs; lock before model fitting. No pseudo-labels.",
    "baseline": "Earth Search sentinel-2-c1-l2a; June 1–September 30 each endpoint. At each reference-cell centre use nearest B04 red/B08 nir/B11 swir16/SCL. Apply asset scale/offset and nodata; keep SCL 4,5,6 only, finite nonnegative reflectance, positive denominators. For overlapping scenes choose first usable per UTC date by cloud% then ID. Per-cell median NDVI=(B08-B04)/(B08+B04) and NDBI=(B11-B08)/(B11+B08) over >=3 clear dates; same >=5/9 cells at both endpoints. Use patch medians for each endpoint on this support.",
    "models": "Same eligible complete-case rows, development-only StandardScaler then logistic regression C=1, L2, no class weights or tuning. Baseline = NDVI2020,NDBI2020,deltaNDVI,deltaNDBI. Augmented = baseline + median 2020-25 embedding cosine distance on same joint patch cells. No coordinates, split ID or post-label features.",
    "analysis": "Locked evaluation once. Report eligibility/missingness and class prevalence by split/block; AP (average precision) primary, ROC AUC and Brier secondary. Paired difference in AP, resample held-out blocks with replacement 2000 times seed 20261103, discard one-class draws and require >=1900 usable. Evidence of added value only if delta AP>0 and two-sided percentile 95% lower bound>0; otherwise inconclusive, not evidence of equivalence.",
    "gates": "At least 20 labelled complete blocks in each split, >=15 positives and >=15 negatives per split, each class in >=5 blocks per split. Two distinct agreeing reviewers. No fit/score when gate fails. Conditional results apply only to eligible observed sites; report attrition relative to all 300 assigned sites.",
    "sensitivity": "Repeat same fitted predictions on held-out pairs with seasonal capture difference <=90 days (circular day of year) and separately on patches with all 9 clear baseline cells. Require same test-side class/block gates for each sensitivity; report rather than select. Primary is 2020–25 only; no adjacent-year labels implied.",
}


def rank(s):
    return hashlib.sha256((SEED + "|" + s).encode()).hexdigest()


def design(ref):
    fwd = Transformer.from_crs(4326, 32748, always_xy=True)
    rev = Transformer.from_crs(32748, 4326, always_xy=True)
    w, s, e, n = ROI
    xmin, ymin, xmax, ymax = fwd.transform_bounds(w, s, e, n)
    blocks = []
    for i in range(int(xmin // 5000), int(xmax // 5000) + 1):
        for j in range(int(ymin // 5000), int(ymax // 5000) + 1):
            extent = rev.transform_bounds(
                i * 5000, j * 5000, (i + 1) * 5000, (j + 1) * 5000, densify_pts=21
            )
            if box(*ROI).covers(box(*extent)):
                blocks.append((i, j))
    chosen = sorted(blocks, key=lambda ij: rank("select" + str(ij)))[:100]
    if len(chosen) != 100:
        raise ValueError("Insufficient blocks")
    held = set(sorted(chosen, key=lambda ij: rank("split" + str(ij)))[:50])
    sites = []
    for i, j in chosen:
        accepted = []
        for k in range(500):
            h = rank(f"point/{i}/{j}/{k}")
            x = i * 5000 + 550 + 3900 * int(h[:12], 16) / 2**48
            y = j * 5000 + 550 + 3900 * int(h[12:24], 16) / 2**48
            row, col = ref.index(*rev.transform(x, y))
            lon, lat = ref.xy(row, col)
            xy = np.array(fwd.transform(lon, lat))
            if any(np.linalg.norm(p - xy) < 1000 for p in accepted):
                continue
            accepted.append(xy)
            corners = [
                ref.transform * (col - 1, row - 1),
                ref.transform * (col + 2, row + 2),
            ]
            a, b = corners
            sites.append(
                dict(
                    id="J" + h[:10],
                    row=row,
                    col=col,
                    lon=float(lon),
                    lat=float(lat),
                    block=f"{i}:{j}",
                    split="evaluation" if (i, j) in held else "development",
                    bounds=[a[0], b[1], b[0], a[1]],
                )
            )
            if len(accepted) == 3:
                break
        if len(accepted) != 3:
            raise ValueError("Sampling exhausted")
    return sorted(sites, key=lambda v: v["id"])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=["register", "select"])
    stage = p.parse_args().stage
    protocol = OUT / "protocol.json"
    if stage == "register":
        write_new(protocol, RULE)
        print(sha256_file(protocol))
        return
    if (
        json.loads(protocol.read_text(encoding="utf8")) != RULE
        or sha256_file(REFERENCE) != EXPECTED_REFERENCE_SHA256
    ):
        raise ValueError("Protocol or geometry drift")
    with rasterio.open(REFERENCE) as ref:
        sites = design(ref)  # metadata only; never read a pixel
    write_new(
        OUT / "assignment.json",
        dict(protocol_sha256=sha256_file(protocol), sites=sites),
    )
    write_new(
        OUT / "blinded_patches.geojson",
        dict(
            type="FeatureCollection",
            features=[
                dict(
                    type="Feature",
                    geometry=mapping(box(*s["bounds"])),
                    properties={"site_id": s["id"]},
                )
                for s in sites
            ],
        ),
    )
    print(len(sites), "sites;", len(set(s["block"] for s in sites)), "blocks")


if __name__ == "__main__":
    main()
