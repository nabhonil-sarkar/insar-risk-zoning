"""Configuration invariant tests."""

import pytest

import config.settings as settings


def test_real_settings_are_valid():
    settings.validate_settings()


def test_rejects_gappy_severity_bins(monkeypatch):
    monkeypatch.setattr(settings, "SUBSIDENCE_THRESHOLDS", {
        "rapid": (float("-inf"), -25.0),
        "stable": (-2.0, float("inf")),
    })
    with pytest.raises(ValueError, match="gap/overlap"):
        settings.validate_settings()


def test_rejects_invalid_coverage_gate(monkeypatch):
    monkeypatch.setattr(settings, "MIN_CLUSTER_VELOCITY_COVERAGE_PCT", 120.0)
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        settings.validate_settings()


def test_rejects_invalid_risk_matrix_shape(monkeypatch):
    monkeypatch.setattr(settings, "EXPOSURE_RISK_MATRIX", [[1, 2]])
    with pytest.raises(ValueError, match="one row per severity"):
        settings.validate_settings()
