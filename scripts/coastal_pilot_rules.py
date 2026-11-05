"""Synthetic-testable proposed rules; no file/network access or real-data runner."""

from datetime import date

import numpy as np
from scipy import ndimage


def reflectance(dn, offset):
    dn = np.asarray(dn)
    if offset not in (0, -1000) or dn.dtype.kind not in "ui" or np.any(dn > 32767):
        raise ValueError("Unregistered radiometry")
    return np.where(dn != 0, (dn.astype(float) + offset) / 10000, np.nan)


def mean_2x2(a):
    a = np.asarray(a, dtype=float)
    if a.ndim != 2 or any(n % 2 for n in a.shape):
        raise ValueError("Requires aligned even 10 m array")
    # A single missing native contributor leaves the 20 m cell missing.
    return a.reshape(a.shape[0]//2, 2, a.shape[1]//2, 2).mean(axis=(1, 3))


def date_states(green, swir, scl, centre=0., buffer_m=60):
    """Return clear support and {-1 ambiguous/masked, 0 land, 1 water}."""
    g, s, q = np.asarray(green), np.asarray(swir), np.asarray(scl)
    if g.ndim != 2 or g.shape != s.shape or g.shape != q.shape:
        raise ValueError("Misaligned observation")
    if centre not in (-.05, 0., .05) or buffer_m not in (60, 120):
        raise ValueError("Unregistered sensitivity")
    if not np.isin(q, np.arange(12)).all():
        raise ValueError("Unknown SCL code")
    danger = np.isin(q, [2, 3, 8, 9, 10])
    radius = buffer_m // 20
    yy, xx = np.ogrid[-radius:radius+1, -radius:radius+1]
    danger = ndimage.binary_dilation(danger, structure=xx*xx+yy*yy <= radius*radius)
    clear = np.isin(q, [4, 5, 6]) & ~danger & np.isfinite(g) & np.isfinite(s)
    eligible = clear & (g >= 0) & (s >= 0) & (g+s > .02)
    index = np.divide(g-s, g+s, out=np.full(g.shape, np.nan), where=eligible)
    state = np.full(g.shape, -1, dtype=np.int8)
    for value, mask in [(0, index < centre-.1), (1, index > centre+.1)]:
        interior = ndimage.binary_erosion(mask, structure=np.ones((3,3)), border_value=0)
        state[interior] = value
    return clear, state


def season_state(dates, clear, state):
    """At least 3 dates/months, 10-day spacing and 60-day span; 80% agreement."""
    ds = [date.fromisoformat(d) for d in dates]
    if len(set(ds)) != len(ds) or ds != sorted(ds) or not ds:
        raise ValueError("Dates must be unique and ordered")
    if len({d.year for d in ds}) != 1 or not (all(1 <= d.month <= 4 for d in ds) or all(6 <= d.month <= 9 for d in ds)):
        raise ValueError("Dates cross declared year/season")
    c, s = np.asarray(clear), np.asarray(state)
    if c.dtype != bool or c.shape != s.shape or c.shape[0] != len(ds) or not np.isin(s, [-1,0,1]).all():
        raise ValueError("Invalid observation arrays")
    if np.any((s != -1) & ~c):
        raise ValueError("Classified masked observation")
    shape = c.shape[1:]
    support = np.zeros(shape, dtype=bool)
    result = np.full(shape, -1, dtype=np.int8)
    flat_c, flat_s = c.reshape(len(ds), -1), s.reshape(len(ds), -1)
    for j in range(flat_c.shape[1]):
        ix = np.flatnonzero(flat_c[:, j])
        if len(ix) < 3:
            continue
        valid = [ds[i] for i in ix]
        spaced = [valid[0]]
        for d in valid[1:]:
            if (d-spaced[-1]).days >= 10:
                spaced.append(d)
        ok = len({d.month for d in valid}) >= 3 and len(spaced) >= 3 and (valid[-1]-valid[0]).days >= 60
        support.flat[j] = ok
        if ok:
            for value in (0,1):
                if np.count_nonzero(flat_s[ix,j] == value) / len(ix) >= .8:
                    result.flat[j] = value
    return support, result


def annual_state(first, second):
    a, b = np.asarray(first), np.asarray(second)
    if a.shape != b.shape or not np.isin(a, [-1,0,1]).all() or not np.isin(b, [-1,0,1]).all():
        raise ValueError("Invalid seasonal states")
    return np.where((a == b) & (a >= 0), a, -1).astype(np.int8)


def persistence(annual):
    """0 stable land, 1 stable water, 2 water->land, 3 land->water,
    -1 unknown, -2 reversal, -3 insufficient persistence at series edge.
    """
    a = np.asarray(annual)
    if a.shape[0] != 6 or not np.isin(a, [-1,0,1]).all():
        raise ValueError("Exactly 2020-2025 required")
    out = np.full(a.shape[1:], -1, dtype=np.int8)
    flat = a.reshape(6, -1)
    for j in range(flat.shape[1]):
        v = flat[:,j]
        if (v < 0).any():
            continue
        switches = np.flatnonzero(v[1:] != v[:-1])+1
        if len(switches) == 0:
            out.flat[j] = v[0]
        elif len(switches) > 1:
            out.flat[j] = -2
        elif 2 <= switches[0] <= 4:
            out.flat[j] = 2 if v[0] == 1 else 3
        else:
            out.flat[j] = -3
    return out
