"""Array-only, prospective baseline-surface diagnostic; no file I/O."""

import numpy as np


YEARS = tuple((y, y + 1) for y in range(2020, 2025))
SECTORS = ("NW", "N", "NE", "W", "C", "E", "SW", "S", "SE")
CLASSES = {
    10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland",
    50: "Built-up", 60: "Bare / sparse vegetation", 70: "Snow and ice",
    80: "Permanent water bodies", 90: "Herbaceous wetland", 95: "Mangroves",
    100: "Moss and lichen",
}
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
RULE = {
    "question": "How does 2022-2023 differ from each other adjacent transition within 2020 baseline class and sector?",
    "prior_knowledge": "Aggregate findings and existing maps are known. This is a prospectively specified follow-up, not an entirely blind experiment.",
    "years": [list(p) for p in YEARS],
    "primary": "Four target-minus-comparator contrasts (2022-2023 minus each other annual transition), within each baseline class; sector rows are mandatory geographic checks.",
    "classes": {str(k): v for k, v in CLASSES.items()},
    "grouping": "None. All 11 classes remain separate, including wetland and mangroves; absent classes retained.",
    "worldcover": "Exact 2020 v100 S09E105 tile. Native containing pixel at each frozen analysis centre (inverse affine floor), no overviews/interpolation/majority vote. Code 0 or masked = unclassified, excluded from distance summaries but retained in support accounting. Any other code fails closed.",
    "sectors": "np.array_split of original full raster rows and columns into three groups, north/west first; row-major NW,N,NE,W,C,E,SW,S,SE. Never redivide after exclusions; closed ROI centre clip.",
    "support": "Fixed intersection of finite, unmasked distances in [0,2] across all FIVE annual transitions, inside ROI, with valid baseline class. No capped values or resampling. Counts by map, joint support and excluded counts/fractions retained. Registered input masks/counts must match; unexpected support loss stops, not silently accepted.",
    "support_denominators": "Per class/sector: baseline_count is classified ROI centres before distance validity; missing_count=baseline_count-joint_count, missing_fraction=missing_count/baseline_count. Per-map available counts use the same baseline. Unclassified_fraction uses all ROI centres in that geography. Zero denominator gives JSON null, never zero.",
    "sparse": {"min_joint_cells": 100, "block_size_m": 1000,
               "min_cells_per_block": 10, "min_blocks": 5,
               "definition": "EPSG:32748 centre blocks anchored at easting/northing zero, floor(x/1000),floor(y/1000). Supported requires >=100 joint cells AND >=5 blocks with >=10 joint cells of this class in this geography. Empty if no joint cells; otherwise sparse if either floor fails. Floors are descriptive design choices for count and geographic spread, not independent observations, power or accuracy guarantees. All nonempty rows retain statistics with their status; sparse rows cannot support a class/geographic interpretation."},
    "statistics": "Float64 calculations from original float32 uncapped maps. Per class and class-by-sector: count and p10,q25,median,q75,p90 via numpy.quantile(method='linear'); empty gives null. Four contrasts report difference of transition medians AND quantiles of cell-paired target-minus-comparator differences on identical joint support. These are distinct estimands. Also paired positive/zero/negative counts and fractions (exact stored-value ties, no tolerance or rounding); no ratios to comparator distances.",
    "geography": "Inspect every supported within-sector contrast before interpreting a pooled class contrast; report supported-sector count and signs, disagreement and sparse/empty sectors. Do not average sector medians or infer a class effect from pooled class differences. No geographic reweighting or automatic attribution classifier.",
    "interpretation": [
        "Broad differences across supported classes/sectors are compatible with shared observation/product influence but do not prove it.",
        "Class/geography concentration identifies where dated observations could be inspected, not a physical cause.",
        "Mixed, contradictory, sparse or empty patterns remain unresolved. A mixture is allowed.",
        "WorldCover is ancillary baseline evidence, not independent truth or proof that locations stayed unchanged. No pixel-independence tests, p-values, causal claims, learned noise floor, development, subsidence, hazard or risk classification.",
    ],
    "outputs": ["results.json (support, transition and paired-contrast rows, provenance)",
                "support.csv", "transitions.csv", "contrasts.csv",
                "summary.txt (descriptive coverage and interpretation limits)",
                "class_transitions.png (all-class pooled medians and IQRs)",
                "sector_contrasts.png (paired median differences; all classes/sectors and four comparators, sparse/empty marked)"],
    "execution": "Explicit approval of exact protocol SHA-256, clean committed code, verified inventory and all pinned input hashes before distance raster opens. Isolated checked snapshots for map/WorldCover reads. Non-overwriting atomic publication of a run directory. No seam rerun, new acquisition, new annual maps, automatic rescue test, report revision or Phase B/C work.",
}


def sector_grid(shape):
    if len(shape) != 2 or min(shape) < 3:
        raise ValueError("Expected 2-D grid with at least three rows and columns")
    out = np.empty(shape, dtype=np.uint8)
    for i, rr in enumerate(np.array_split(np.arange(shape[0]), 3)):
        for j, cc in enumerate(np.array_split(np.arange(shape[1]), 3)):
            out[np.ix_(rr, cc)] = 3 * i + j
    return out


def ratio(n, d):
    return float(n / d) if d else None


def quantiles(values):
    vals = np.asarray(values, dtype=np.float64)
    keys = ("p10", "q25", "median", "q75", "p90")
    return dict(zip(keys, np.quantile(vals, QUANTILES, method="linear").tolist()
                    if vals.size else [None] * 5))


def support_rows(cover, inside, valid, blocks):
    """Count-only inventory; valid is a (5,H,W) boolean mask, never distances."""
    cover = np.ma.asarray(cover).filled(0)
    inside, valid, blocks = map(np.asarray, (inside, valid, blocks))
    if (inside.ndim != 2 or cover.shape != inside.shape or blocks.shape != inside.shape
            or valid.shape != (5, *inside.shape) or valid.dtype != bool
            or inside.dtype != bool):
        raise ValueError("Expected aligned class, geometry and five boolean masks")
    if not np.isin(cover[inside], [0, *CLASSES]).all():
        raise ValueError("Unexpected WorldCover class code")
    sectors = sector_grid(inside.shape)
    joint = valid.all(axis=0) & inside
    rows = []
    for sector_id, sector in [(-1, "ALL"), *enumerate(SECTORS)]:
        geo = inside & ((sectors == sector_id) if sector_id >= 0 else True)
        total = int(geo.sum())
        unknown = int((geo & (cover == 0)).sum())
        for code in [0, *CLASSES]:
            baseline = geo & (cover == code)
            take = baseline & joint
            base, n = int(baseline.sum()), int(take.sum())
            _, counts = np.unique(blocks[take], return_counts=True)
            rule = RULE["sparse"]
            spread = int((counts >= rule["min_cells_per_block"]).sum())
            status = ("unclassified" if code == 0 else "empty" if not n
                      else "sparse" if n < rule["min_joint_cells"] or spread < rule["min_blocks"]
                      else "supported")
            rows.append(dict(sector=sector, class_code=code,
                             class_name=CLASSES.get(code, "Unclassified"),
                             roi_count=total, unclassified_count=unknown,
                             unclassified_fraction=ratio(unknown, total),
                             baseline_count=base, joint_count=n,
                             missing_count=base-n, missing_fraction=ratio(base-n, base),
                             available_counts=[int((baseline & m).sum()) for m in valid],
                             occupied_blocks=len(counts), supported_blocks=spread, status=status))
    return rows


def analyse(distances, cover, inside, blocks):
    a = np.ma.asarray(distances, dtype=np.float64).filled(np.nan)
    if a.shape != (5, *np.shape(inside)):
        raise ValueError("Expected exactly five aligned transitions")
    if np.isinf(a).any() or np.any(np.isfinite(a) & ((a < 0) | (a > 2))):
        raise ValueError("Invalid cosine distance")
    valid = np.isfinite(a)
    support = support_rows(cover, inside, valid, blocks)
    cover = np.ma.asarray(cover).filled(0)
    sectors = sector_grid(inside.shape)
    joint = valid.all(axis=0) & inside
    transitions, contrasts = [], []
    for row in support:
        if not row["class_code"]:
            continue
        take = joint & (cover == row["class_code"])
        if row["sector"] != "ALL":
            take &= sectors == SECTORS.index(row["sector"])
        vals = a[:, take]
        base = {k: row[k] for k in ("sector", "class_code", "class_name", "status", "joint_count")}
        summaries = [quantiles(v) for v in vals]
        for years, q in zip(YEARS, summaries):
            transitions.append(dict(base, years=list(years), **q))
        for i in (0, 1, 3, 4):
            delta = vals[2] - vals[i]
            n = delta.size
            counts = {"positive": int((delta > 0).sum()), "zero": int((delta == 0).sum()),
                      "negative": int((delta < 0).sum())}
            contrasts.append(dict(base, target=[2022, 2023], comparator=list(YEARS[i]),
                                  difference_of_medians=(summaries[2]["median"] - summaries[i]["median"] if n else None),
                                  paired_quantiles=quantiles(delta), **counts,
                                  fractions={k: ratio(v, n) for k, v in counts.items()}))
    return dict(support=support, transitions=transitions, contrasts=contrasts)
