"""Pure June--September quality/temporal support; no spectral classification."""

from datetime import date

import numpy as np
from pyproj import Geod, Transformer
from scipy import ndimage

from scripts.coastal_transport import GateError

BUFFERS = (60, 120)


def clear_mask(observation, buffer_m):
    """Finite green/SWIR plus SCL; deliberately no spectral eligibility test."""
    g, s, q = (np.asarray(observation[k]) for k in ('B03', 'B11', 'SCL'))
    if (buffer_m not in BUFFERS or g.shape != (66, 66) or s.shape != g.shape
            or q.shape != g.shape or not np.isin(q, range(12)).all()):
        raise GateError('Invalid aligned coverage arrays/buffer')
    radius = buffer_m // 20
    yy, xx = np.ogrid[-radius:radius + 1, -radius:radius + 1]
    danger = ndimage.binary_dilation(np.isin(q, [2, 3, 8, 9, 10]),
                                    structure=xx * xx + yy * yy <= radius * radius)
    clear = np.isin(q, [4, 5, 6]) & ~danger & np.isfinite(g) & np.isfinite(s)
    return clear[8:-8, 8:-8]


def temporal_support(dates, clear):
    """Return only support/counts. No state arrays, votes or classification calls."""
    ds = [date.fromisoformat(d) for d in dates]
    c = np.asarray(clear)
    if (not ds or ds != sorted(set(ds)) or len({d.year for d in ds}) != 1
            or not all(6 <= d.month <= 9 for d in ds)
            or c.dtype != bool or c.ndim < 2 or c.shape[0] != len(ds)):
        raise GateError('Invalid June-September clear observations/dates')
    days = np.array([d.toordinal() for d in ds])
    expanded = days.reshape((-1,) + (1,) * (c.ndim - 1))
    counts = c.sum(axis=0)
    months = sum(c[[i for i, d in enumerate(ds) if d.month == m]].any(axis=0)
                 for m in sorted({d.month for d in ds}))
    first = np.where(c, expanded, 10**9).min(axis=0)
    last = np.where(c, expanded, -10**9).max(axis=0)
    span = np.where(counts > 0, last - first, 0)
    previous = np.full(c.shape[1:], -10**9)
    spaced = np.zeros(c.shape[1:], dtype=int)
    for day, mask in zip(days, c):
        take = mask & (day - previous >= 10)
        spaced += take
        previous[take] = day
    support = (counts >= 3) & (months >= 3) & (span >= 60) & (spaced >= 3)
    return dict(support=support, clear_count=counts, month_count=months,
                span_days=span, spaced_count=spaced)


def cell_areas(bounds):
    left, bottom, right, top = bounds
    if right - left != 1000 or top - bottom != 1000:
        raise GateError('Nonregistered core area')
    tr = Transformer.from_crs(32748, 4326, always_xy=True)
    geod = Geod(ellps='WGS84')
    area = np.zeros((50, 50))
    for row, col in np.ndindex(area.shape):
        x, y = left + 20 * col, top - 20 * row
        lon, lat = tr.transform([x, x + 20, x + 20, x], [y, y, y - 20, y - 20])
        area[row, col] = abs(geod.polygon_area_perimeter(lon, lat)[0])
    if not np.isfinite(area).all() or (area <= 0).any():
        raise GateError('Invalid geodesic area')
    return area


def coverage_row(window, year, dates, clear, buffer_m, area):
    if len(dates) != 8 or clear.shape != (8, 50, 50):
        raise GateError('Incomplete coverage batch')
    metrics = temporal_support(dates, clear)
    support, counts = metrics['support'], metrics['clear_count']
    n = int(support.sum())
    row = dict(window=window, year=year, season='Jun-Sep', buffer_m=buffer_m,
               status='measured', selected_dates=8, acquired_dates=8, core_cells=2500,
               supported_cells=n, support_fraction=n / 2500, support_gate_pass=n >= 2000,
               clear_cell_observations=int(clear.sum()), total_cell_observations=int(clear.size),
               masked_fraction=float(1 - clear.mean()), minimum_clear_count=int(counts.min()),
               median_clear_count=float(np.median(counts)), maximum_clear_count=int(counts.max()),
               three_clear_dates_cells=int((counts >= 3).sum()),
               three_months_cells=int((metrics['month_count'] >= 3).sum()),
               sixty_day_span_cells=int((metrics['span_days'] >= 60).sum()),
               three_spaced_dates_cells=int((metrics['spaced_count'] >= 3).sum()),
               supported_area_m2=float(area[support].sum()),
               unsupported_area_m2=float(area[~support].sum()), dates=dates)
    return row, metrics
