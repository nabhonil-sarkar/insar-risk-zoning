"""Synthetic coordinates and distances only: no project data files or fixtures."""

import numpy as np
import pytest

from scripts.alphaearth_tile_seam import comparison_rows, headline, strip_test


def grid():
    # Four 30 m columns per strip side x 15 synthetic rows = exactly 60.
    # Include both segment/strip lower boundaries and the seam itself.
    return np.meshgrid(
        663840 + np.arange(-3120, 3120, 30),
        9278000 + np.repeat(np.arange(8) * 2000, 15) + np.tile(np.arange(15) * 30, 8),
    )


@pytest.mark.parametrize("sign,direction", [(1, "east"), (-1, "west")])
def test_planted_step(sign, direction):
    x, y = grid()
    result = strip_test(0.5 + sign * 0.25 * (x >= 663840), x, y)
    assert result["status"] == "flagged"
    assert result["matched_segments"] == list(range(8))
    assert len(result["eligible_controls"]) == 20
    seam = result["lines"][0]
    assert seam["counts_west_east"][:8] == [[60, 60]] * 8
    assert seam["matched_contrasts"] == [sign * 0.25] * 8
    assert (seam["direction"], seam["consistency"]) == (direction, 1)


def test_no_seam_and_control_ties():
    x, y = grid()
    r = strip_test(np.ones_like(x), x, y)
    assert r["status"] == "not_flagged"
    assert r["strength_rank"]["tied"] == 20
    assert r["lines"][0]["zero"] == 8
    assert r["lines"][0]["direction"] == "none"
    # Nonzero smooth slope: sign consistency alone cannot flag a boundary.
    r = strip_test((x - 660000) / 8192, x, y)
    assert r["lines"][0]["consistency"] == 1
    assert r["reasons"] == ["strength_not_strictly_above_controls"]


def test_mask_can_make_a_strong_step_inconclusive():
    x, y = grid()
    a = np.ma.array((x >= 663840).astype(float), mask=np.zeros_like(x, bool))
    # Remove just ONE east cell from each of three segments: 59 is not 60.
    a.mask[[0, 15, 30], np.where(x[0] == 663840)[0][0]] = True
    r = strip_test(a, x, y)
    assert r["status"] == "inconclusive"
    assert r["matched_segments"] == list(range(3, 8))
    assert r["reasons"] == ["too_few_seam_segments"]
    assert r["lines"][0]["counts_west_east"][0] == [60, 59]


def test_controls_must_support_every_seam_segment():
    x, y = grid()
    a = (x >= 663840).astype(float)
    for i, off in enumerate((-3000, 3000)):
        a[i * 15, np.where(x[0] == 663840 + off)[0][0]] = np.nan
        r = strip_test(a, x, y)
        assert len(r["eligible_controls"]) == 19 - i
        assert r["status"] == ("flagged" if i == 0 else "inconclusive")
    assert r["reasons"] == ["too_few_matched_controls"]
    assert len(r["matched_segments"]) == 8


def test_consistency_cutoff_and_control_percentile():
    x, y = grid()
    seg = (y - 9278000) // 2000
    # Six positive, two zero: equality at the 75% floor passes.
    a = ((x >= 663840) & (seg < 6)).astype(float)
    assert strip_test(a, x, y)["status"] == "flagged"
    # Three persistent, smaller control steps lift the 18th order statistic to 1.
    for off in (300, 600, 900):
        a += 0.125 * (x >= 663840 + off)
    r = strip_test(a, x, y)
    assert r["strength_rank"]["below"] == 20
    assert r["control_consistency_q90"] == 1
    assert r["reasons"] == ["insufficient_consistency"]


def test_comparison_priorities_and_strata():
    x, y = grid()
    wc = np.where(y < 9280000, 80, 10)
    for years in [
        (2020, 2021),
        (2021, 2022),
        (2022, 2023),
        (2023, 2024),
        (2024, 2025),
        (2020, 2025),
    ]:
        rows = comparison_rows(years, (x >= 663840).astype(float), x, y, wc)
        assert [r["priority"] for r in rows] == [
            "primary" if years in ((2022, 2023), (2020, 2025)) else "supporting",
            "supporting",
            "supporting",
        ]
        assert [r["status"] for r in rows] == ["flagged", "flagged", "inconclusive"]


def test_headline_excludes_whole_west_with_fixed_nw_and_recomputed_percentile():
    a = np.zeros((10, 20))
    # One NW extreme in each tile; next contender outside NW.
    a[0, 0], a[3, 6], a[9, 19] = 2, 1.75, 1.5
    x = np.broadcast_to(663840 + (np.arange(20) - 2) * 30, a.shape)
    r = headline(a, x, expected_counts=(200, 2, 28, 2))
    assert r["west"] == r["east"] == {"n": 1, "d": 2, "value": 0.5}
    assert r["fixed"]["extreme_share"]["value"] == 1
    assert r["reranked"]["extreme_share"]["value"] == 0.5
    assert r["reranked"]["change_pp"] == -50
    assert r["reranked"]["valid_share"] == {"n": 20, "d": 180, "value": 20 / 180}
    assert r["reranked"]["enrichment"] == 4.5
    assert r["fixed"]["cutoff"] == pytest.approx(1.5025)
    assert r["reranked"]["cutoff"] == pytest.approx(0.315)
    with pytest.raises(ValueError, match="baseline"):
        headline(a, x)


def test_headline_ties_and_empty_retained_population():
    a = np.ones((6, 6))
    r = headline(a, np.zeros_like(a), expected_counts=(36, 36, 4, 4))
    assert r["west"]["value"] == 1
    assert r["fixed"]["extreme_share"]["value"] is None
    assert r["reranked"]["cutoff"] is None
