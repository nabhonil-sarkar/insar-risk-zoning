import numpy as np

from scripts.analyze_v9_retained_loop_attribution import (
    loop_error_mask,
    make_triangle_loops,
    parse_reference_area,
    referenced_loop_phase,
)


def test_make_triangle_loops_matches_three_edge_cycles():
    pairs = [
        "20200101_20200113",
        "20200101_20200125",
        "20200113_20200125",
        "20200113_20200206",
    ]

    assert make_triangle_loops(pairs) == [
        (
            "20200101_20200113",
            "20200113_20200125",
            "20200101_20200125",
        )
    ]


def test_reference_correction_and_pi_error_gate_preserve_missing_pixels():
    unw12 = np.array([[1.0, 5.0, np.nan], [2.0, 2.0, 2.0]], dtype="float32")
    unw23 = np.array([[2.0, 2.0, 2.0], [2.0, 2.0, 2.0]], dtype="float32")
    unw13 = np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]], dtype="float32")

    phase = referenced_loop_phase(unw12, unw23, unw13, (0, 1, 0, 1))
    errors, valid = loop_error_mask(phase)

    np.testing.assert_allclose(phase[0, :2], [0.0, 4.0])
    assert np.isnan(phase[0, 2])
    np.testing.assert_array_equal(valid[0], [True, True, False])
    np.testing.assert_array_equal(errors[0], [False, True, False])


def test_parse_reference_area_uses_x_then_y_order():
    assert parse_reference_area("17:18/23:24\n") == (17, 18, 23, 24)
