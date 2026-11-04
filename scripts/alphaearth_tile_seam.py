"""Array-only calculations for the frozen v2 seam diagnostic. No raster I/O.

Inputs are co-registered, north-up arrays. The caller must supply projected
cell centres (EPSG:32748), with invalid/outside-ROI distances masked or NaN.
Input provenance and real-run authorization belong upstream of these functions.
"""

import math

import numpy as np


PROTOCOL_SHA256 = "fec005c9b413df6ddcb197746c188183fec9f671743e53fca65a394e927b735d"
SEAM = 663840
OFFSETS = tuple(range(-3000, 3001, 300))
BASELINE = (5619719, 56198, 624512, 18096)
COMPARISONS = tuple((y, y + 1) for y in range(2020, 2025)) + ((2020, 2025),)
LAND = (10, 20, 30, 40, 50, 60, 70, 90, 95, 100)


def _arrays(distance, *coords):
    a = np.ma.asarray(distance, dtype=np.float64).filled(np.nan)
    coords = tuple(np.asarray(c, dtype=np.float64) for c in coords)
    if a.ndim != 2 or any(c.shape != a.shape for c in coords):
        raise ValueError("Expected aligned 2-D arrays")
    valid = np.isfinite(a)
    if any(not np.isfinite(c[valid]).all() for c in coords):
        raise ValueError("Missing coordinate for valid cell")
    return a, valid, *coords


def _metrics(d):
    median = float(np.median(d))
    pos, neg = int((d > 0).sum()), int((d < 0).sum())
    return dict(
        signed_median=median,
        strength=abs(median),
        consistency=max(pos, neg) / len(d),
        zero=len(d) - pos - neg,
        direction="east" if pos > neg else "west" if neg > pos else "none",
    )


def _rank(value, controls):
    return dict(
        below=int((controls < value).sum()),
        tied=int((controls == value).sum()),
        above=int((controls > value).sum()),
    )


def strip_test(distance, x, y):
    """One comparison/stratum; preserve counts even for inconclusive results."""
    a, valid, x, y = _arrays(distance, x, y)
    use = (
        valid & (y >= 9278000) & (y < 9334000) & (x >= SEAM - 3120) & (x < SEAM + 3120)
    )
    x, a = x[use], a[use]
    seg = ((y[use] - 9278000) // 2000).astype(int)
    counts = np.zeros((21, 28, 2), dtype=int)
    contrasts = np.full((21, 28), np.nan)
    for i, off in enumerate(OFFSETS):
        dx = x - (SEAM + off)
        meds = np.full((28, 2), np.nan)
        for side, lo in enumerate((-120, 0)):
            take = (dx >= lo) & (dx < lo + 120)
            ids, vals = seg[take], a[take]
            counts[i, :, side] = np.bincount(ids, minlength=28)
            for j in np.flatnonzero(counts[i, :, side] >= 60):
                meds[j, side] = np.median(vals[ids == j])
        contrasts[i] = meds[:, 1] - meds[:, 0]
    seam_idx = OFFSETS.index(0)
    matched = np.isfinite(contrasts[seam_idx])
    lines = {}
    out = dict(
        status="inconclusive",
        matched_segments=np.flatnonzero(matched).tolist(),
        lines=lines,
        reasons=[],
    )
    for i, off in enumerate(OFFSETS):
        d = contrasts[i, matched]
        line = dict(
            counts_west_east=counts[i].tolist(),
            matched_contrasts=[float(v) if np.isfinite(v) else None for v in d],
        )
        if len(d) >= 6 and np.isfinite(d).all():
            line.update(_metrics(d))
        lines[off] = line
    controls = [o for o in OFFSETS if o and "strength" in lines[o]]
    out["eligible_controls"] = controls
    if matched.sum() < 6:
        out["reasons"].append("too_few_seam_segments")
        return out
    if (
        len(controls) < 19
        or min(sum(o < 0 for o in controls), sum(o > 0 for o in controls)) < 9
    ):
        out["reasons"].append("too_few_matched_controls")
        return out
    ref = lines[0]
    for key in ("strength", "consistency"):
        vals = np.array([lines[o][key] for o in controls])
        out[key + "_rank"] = _rank(ref[key], vals)
    q90 = sorted(lines[o]["consistency"] for o in controls)[
        math.ceil(0.9 * len(controls)) - 1
    ]
    out["control_consistency_q90"] = q90
    if out["strength_rank"]["below"] != len(controls):
        out["reasons"].append("strength_not_strictly_above_controls")
    if ref["consistency"] < 0.75 or ref["consistency"] < q90:
        out["reasons"].append("insufficient_consistency")
    out["status"] = "not_flagged" if out["reasons"] else "flagged"
    return out


def comparison_rows(years, distance, x, y, worldcover):
    """Independent rows; never pool primary and supporting flags."""
    if years not in COMPARISONS:
        raise ValueError("Unregistered comparison")
    wc = np.ma.asarray(worldcover).filled(0)
    if wc.shape != np.shape(distance):
        raise ValueError("WorldCover grid mismatch")
    rows = []
    for group, excluded in (
        ("all", False),
        ("land", ~np.isin(wc, LAND)),
        ("water", wc != 80),
    ):
        result = strip_test(np.ma.array(distance, mask=excluded, keep_mask=True), x, y)
        result.update(
            years=years,
            group=group,
            priority="primary"
            if group == "all" and years in ((2022, 2023), (2020, 2025))
            else "supporting",
        )
        rows.append(result)
    return rows


def _ratio(n, d):
    return dict(n=int(n), d=int(d), value=float(n / d) if d else None)


def headline(distance, x, *, expected_counts=BASELINE):
    """Full-height endpoint exclusion, independent of all strip-test flags."""
    a, valid, x = _arrays(distance, x)
    nw = np.zeros(a.shape, dtype=bool)
    nw[: (a.shape[0] + 2) // 3, : (a.shape[1] + 2) // 3] = True
    east = valid & (x >= SEAM)

    def population(mask, cutoff=None):
        if cutoff is None and mask.any():
            cutoff = float(np.percentile(a[mask], 99, method="linear"))
        hot = mask & (a >= cutoff) if cutoff is not None else np.zeros_like(mask)
        share = _ratio((hot & nw).sum(), hot.sum())
        base = _ratio((mask & nw).sum(), mask.sum())
        enrichment = (
            share["value"] / base["value"]
            if share["value"] is not None and base["value"]
            else None
        )
        return hot, dict(
            cutoff=cutoff, extreme_share=share, valid_share=base, enrichment=enrichment
        )

    hot, original = population(valid)
    if (valid.sum(), hot.sum(), (valid & nw).sum(), (hot & nw).sum()) != tuple(
        expected_counts
    ):
        raise ValueError("Endpoint baseline count mismatch")
    _, fixed = population(east, original["cutoff"])
    _, reranked = population(east)
    for pop in (fixed, reranked):
        new, old = pop["extreme_share"]["value"], original["extreme_share"]["value"]
        pop["change_pp"] = (
            100 * (new - old) if new is not None and old is not None else None
        )
    hits = hot & nw
    return dict(
        original=original,
        fixed=fixed,
        reranked=reranked,
        west=_ratio((hits & ~east).sum(), hits.sum()),
        east=_ratio((hits & east).sum(), hits.sum()),
    )
