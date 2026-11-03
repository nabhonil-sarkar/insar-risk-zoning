import numpy as np

from scripts.audit_v13_results import finite_statistics, parse_dem_parameters, strict_candidate


def test_parse_dem_parameters_and_finite_statistics() -> None:
    parsed = parse_dem_parameters(b"width: 3\nnlines: 2\npost_lon: 0.005 decimal degrees\n")
    assert parsed == {"width": 3, "nlines": 2, "post_lon": 0.005}
    values = np.array([[1.0, np.nan, 3.0], [2.0, 4.0, np.nan]], dtype="float32")
    assert finite_statistics(values) == {
        "total_pixels": 6, "finite_pixels": 4, "min": 1.0, "median": 2.5, "max": 4.0,
    }


def test_strict_candidate_requires_all_frozen_pixel_conditions() -> None:
    ledger = [
        {"row": 0, "col": 0, "qualifies": True},
        {"row": 0, "col": 1, "qualifies": True},
        {"row": 1, "col": 0, "qualifies": False},
        {"row": 1, "col": 1, "qualifies": True},
    ]
    velocity = np.array([[1.0, np.nan], [1.0, 1.0]], dtype="float32")
    vstd = np.ones((2, 2), dtype="float32")
    n_gap = np.array([[0.0, 0.0], [0.0, 1.0]], dtype="float32")
    n_loop = np.zeros((2, 2), dtype="float32")
    eligible, strict = strict_candidate(ledger, velocity, vstd, n_gap, n_loop)
    np.testing.assert_array_equal(eligible, [[True, True], [False, True]])
    np.testing.assert_array_equal(strict, [[True, False], [False, False]])
