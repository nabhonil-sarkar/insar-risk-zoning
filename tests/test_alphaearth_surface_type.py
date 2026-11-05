"""Synthetic scientific checks, including geographic confounding and exclusions."""

import numpy as np
import pytest

from scripts import alphaearth_surface_type as s


def inputs(shape=(30, 30)):
    a = np.full((5, *shape), .1)
    cover = np.full(shape, 10)
    inside = np.ones(shape, dtype=bool)
    blocks = np.arange(np.prod(shape)).reshape(shape) // 10
    return a, cover, inside, blocks


def rows(result, key, code=10, sector="ALL"):
    return [r for r in result[key] if r["class_code"] == code and r["sector"] == sector]


@pytest.mark.parametrize("uniform", [False, True])
def test_planted_class_specific_and_uniform_jump(uniform):
    a, cover, inside, blocks = inputs()
    cover[:, 15:] = 50
    a[2, :, :15] = .4
    if uniform:
        a[2, :, 15:] = .4
    result = s.analyse(a, cover, inside, blocks)
    for code, delta in ((10, .3), (50, .3 if uniform else 0)):
        for row in rows(result, "contrasts", code):
            assert row["paired_quantiles"]["median"] == pytest.approx(delta)
            assert row["difference_of_medians"] == pytest.approx(delta)
            assert row["positive"] == (450 if delta else 0)
            assert row["zero"] == (0 if delta else 450)
    assert len(result["transitions"]) == 550
    assert len(result["contrasts"]) == 440
    assert len(result["support"]) == 120


def test_geographic_confounding_is_visible_within_sectors():
    a, cover, inside, blocks = inputs((90, 90))
    # A geographic jump only; classes have different geographic composition.
    cover[:, :] = 50
    cover[:30, :25] = 10
    cover[:30, 30:55] = 10
    cover[:30, 60:85] = 10
    cover[30:, ::6] = 10
    a[2, :30] = .5
    result = s.analyse(a, cover, inside, blocks)
    assert rows(result, "contrasts", 10)[0]["paired_quantiles"]["median"] == pytest.approx(.4)
    assert rows(result, "contrasts", 50)[0]["paired_quantiles"]["median"] == 0
    for sector in s.SECTORS:
        first = rows(result, "contrasts", 10, sector)[0]
        second = rows(result, "contrasts", 50, sector)[0]
        assert first["paired_quantiles"] == second["paired_quantiles"]


def test_joint_mask_nodata_and_zero_denominators():
    a, cover, inside, blocks = inputs()
    a[0, 0, :5] = np.nan
    a[4, 0, 5:10] = np.nan
    cover[1, :10] = 0
    result = s.analyse(a, cover, inside, blocks)
    row = rows(result, "support")[0]
    assert row["baseline_count"] == 890 and row["joint_count"] == 880
    assert row["missing_fraction"] == pytest.approx(10/890)
    assert row["available_counts"] == [885, 890, 890, 890, 885]
    assert all(r["joint_count"] == 880 for r in rows(result, "transitions"))
    empty = rows(result, "support", 95)[0]
    assert empty["status"] == "empty" and empty["missing_fraction"] is None
    assert rows(result, "transitions", 95)[0]["median"] is None
    assert rows(result, "contrasts", 95)[0]["fractions"]["zero"] is None
    assert not rows(result, "transitions", 0)


def test_masked_cover_and_distances_exclude_without_reclassification():
    a, cover, inside, blocks = inputs()
    cover = np.ma.array(cover, mask=False)
    cover.mask[0, 0] = True
    a = np.ma.array(a, mask=False)
    a.mask[2, 0, 1] = True
    result = s.analyse(a, cover, inside, blocks)
    assert rows(result, "support", 0)[0]["baseline_count"] == 1
    assert rows(result, "support")[0]["joint_count"] == 898


def test_quantile_interpolation_ties_and_distinct_estimands():
    assert s.quantiles([0, 1])["p10"] == pytest.approx(.1)
    assert s.quantiles([0, 1])["median"] == .5
    a, cover, inside, blocks = inputs((3, 3))
    a[0] = np.array([0, 0, 1] * 3).reshape(3, 3)
    a[2] = np.array([0, 1, 1] * 3).reshape(3, 3)
    r = rows(s.analyse(a, cover, inside, blocks), "contrasts")[0]
    assert r["difference_of_medians"] == 1
    assert r["paired_quantiles"]["median"] == 0
    assert r["zero"] == 6 and r["positive"] == 3


def test_sparse_count_and_spread_floors_and_empty_retained():
    a, cover, inside, blocks = inputs()
    for n, spread, expected in ((99, 9, "sparse"), (100, 4, "sparse"), (100, 5, "supported"), (0, 0, "empty")):
        valid = np.zeros_like(a, dtype=bool)
        valid.reshape(5, -1)[:, :n] = True
        b = np.zeros(inside.size, dtype=int)
        if spread:
            b[:n] = np.arange(n) % spread
        row = rows({"support": s.support_rows(cover, inside, valid, b.reshape(inside.shape))}, "support")[0]
        assert row["status"] == expected


def test_original_sectors_are_not_redivided_after_clipping():
    sector = s.sector_grid((8, 7))
    assert np.all(sector[:3, :3] == 0)
    assert np.all(sector[3:6, 3:5] == 4)
    a, cover, inside, blocks = inputs((8, 7))
    inside[0, :] = False
    result = s.analyse(a, cover, inside, blocks)
    assert rows(result, "support", sector="NW")[0]["baseline_count"] == 6


@pytest.mark.parametrize("bad", ["shape", "code", "infinite", "range"])
def test_invalid_arrays_fail_closed(bad):
    a, cover, inside, blocks = inputs()
    if bad == "shape":
        a = a[:4]
    elif bad == "code":
        cover[0, 0] = 42
    elif bad == "infinite":
        a[0, 0, 0] = np.inf
    else:
        a[0, 0, 0] = 2.1
    with pytest.raises(ValueError):
        s.analyse(a, cover, inside, blocks)
