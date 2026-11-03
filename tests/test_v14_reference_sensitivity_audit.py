import hashlib
import json

import numpy as np
import pytest

from scripts.audit_v14_reference_sensitivity import (
    comparison_statistics,
    fingerprint_preregistration,
    strict_mask,
)


def test_preregistration_fingerprint_omits_only_runtime_fields() -> None:
    preregistration = {"experiment": "x", "created_utc": "later", "value": 3}
    expected = hashlib.sha256(
        json.dumps(
            {"experiment": "x", "value": 3}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    preregistration["configuration_fingerprint"] = expected
    assert fingerprint_preregistration(preregistration) == expected


def test_strict_mask_and_centered_comparison_are_recomputed() -> None:
    eligible = np.array([[True, True], [True, False]])
    velocity = np.array([[1.0, 2.0], [3.0, 4.0]], dtype="float32")
    vstd = np.ones((2, 2), dtype="float32")
    n_gap = np.array([[0.0, 1.0], [0.0, 0.0]], dtype="float32")
    n_loop_err = np.zeros((2, 2), dtype="float32")
    np.testing.assert_array_equal(
        strict_mask(eligible, velocity, vstd, n_gap, n_loop_err),
        [[True, False], [True, False]],
    )

    control = np.array([1.0, 2.0, 4.0, 7.0])
    candidate = control + np.array([2.0, 2.0, 2.0, 2.0])
    statistics = comparison_statistics(control, candidate)
    assert statistics["median_offset_from_control_mm_per_year"] == 2.0
    assert statistics["centered_rmse_mm_per_year"] == 0.0
    assert statistics["centered_p95_abs_mm_per_year"] == 0.0
    assert statistics["centered_max_abs_mm_per_year"] == 0.0
    assert statistics["pearson_pattern_correlation"] == pytest.approx(1.0)
    assert statistics["spearman_pattern_correlation"] == pytest.approx(1.0)
