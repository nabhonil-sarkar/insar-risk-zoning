import numpy as np

from scripts.analyze_v9_north_failure import (
    CATEGORY_GAP_AND_LOOP,
    CATEGORY_GAP_ONLY,
    CATEGORY_INVALID_QUALITY_COUNTS,
    CATEGORY_LOOP_ONLY,
    CATEGORY_MISSING_OUTPUT,
    CATEGORY_OUTSIDE,
    CATEGORY_STRICT_PASS,
    classify_failure,
)


def test_failure_categories_are_mutually_exclusive_and_keep_outside_zero():
    inside = np.array([[False, True, True, True], [True, True, True, True]])
    velocity = np.ones((2, 4), dtype="float32")
    vstd = np.ones((2, 4), dtype="float32")
    n_gap = np.array([[0, 0, 1, 0], [1, 0, np.nan, 0]], dtype="float32")
    n_loop = np.array([[0, 0, 0, 1], [1, 0, 0, 0]], dtype="float32")
    velocity[1, 1] = np.nan

    categories = classify_failure(inside, velocity, vstd, n_gap, n_loop)

    np.testing.assert_array_equal(
        categories,
        np.array(
            [
                [CATEGORY_OUTSIDE, CATEGORY_STRICT_PASS, CATEGORY_GAP_ONLY, CATEGORY_LOOP_ONLY],
                [CATEGORY_GAP_AND_LOOP, CATEGORY_MISSING_OUTPUT, CATEGORY_INVALID_QUALITY_COUNTS, CATEGORY_STRICT_PASS],
            ],
            dtype="uint8",
        ),
    )
