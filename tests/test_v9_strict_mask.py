import numpy as np

from scripts.build_v9_strict_mask import build_strict_mask


def test_strict_mask_requires_finite_velocity_and_zero_gap_and_loop_error():
    arrays = {
        "vel": np.array([[1.0, 2.0, np.nan], [3.0, 4.0, 5.0]], dtype="float32"),
        "vstd": np.array([[1.0, 1.0, 1.0], [np.nan, 1.0, 1.0]], dtype="float32"),
        "n_gap": np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 0.0]], dtype="float32"),
        "n_loop_err": np.array([[0.0, 0.0, 0.0], [0.0, 2.0, np.nan]], dtype="float32"),
    }

    joint_finite, strict = build_strict_mask(arrays)

    np.testing.assert_array_equal(
        joint_finite,
        np.array([[True, True, False], [False, True, True]]),
    )
    np.testing.assert_array_equal(
        strict,
        np.array([[True, False, False], [False, False, False]]),
    )
