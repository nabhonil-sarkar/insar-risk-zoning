"""Tests for stage_cache. Drop into tests/test_stage_cache.py.

Each test reproduces, in miniature, a real failure mode from the code review:
  test_k_change_invalidates            -> bug 2.1
  test_upstream_recompute_invalidates  -> bug 2.2
  test_settings_change_invalidates     -> bug 2.3
  test_exposure_change_invalidates     -> exposure-binding fault
  test_legacy_output_without_sidecar   -> migration behavior
"""

import os
import json
import time
import types

import pytest

from src.utils.stage_cache import (  # adjust import to your layout
    cache_valid, write_sidecar, stage_params,
)


def fake_settings(**overrides):
    """Minimal stand-in for config.settings covering the m4/cal/m4b tables."""
    base = dict(
        ACTIVE_ROI=[106.45, -6.54, 107.22, -6.01],
        COMMON_RESOLUTION=30, COMMON_CRS="EPSG:32748",
        INSAR_VELOCITY_IS_LOS=True, INSAR_INCIDENCE_ANGLE_DEG=39.0,
        COHERENCE_THRESHOLD=0.3, INSAR_VSTD_THRESHOLD=15.0,
        INSAR_VSTD_SWEEP_THRESHOLDS=(5, 10, 15, 20, 30, 50),
        INSAR_NODATA_VALUES=[0.0], INSAR_VSTD_NODATA_VALUES=[0.0],
        INSAR_RESAMPLING="nearest",
        NORMALIZATION_METHOD="zscore", ANALYSIS_YEAR=2023,
        RANDOM_STATE=42, SAMPLE_FRACTION=0.1,
        MAX_CLUSTERING_SAMPLES=500_000, SILHOUETTE_MAX_SAMPLES=50_000,
        KMEANS_BATCH_SIZE=10_000, K_RANGE=range(2, 16),
        HDBSCAN_MIN_CLUSTER_SIZE=500, HDBSCAN_MIN_SAMPLES=50,
        HDBSCAN_MAX_FIT_SAMPLES=50_000, HDBSCAN_PCA_COMPONENTS=20,
        HDBSCAN_MAX_NOISE_FRACTION=0.5, HDBSCAN_MIN_USABLE_CLUSTERS=2,
        HDBSCAN_FALLBACK_K=4,
        CALIBRATION_MIN_CLUSTER_PIXELS=100, CALIBRATION_MAX_SHIFT=15.0,
        CALIBRATION_CANDIDATE_TOLERANCE=3.0,
        SUBSIDENCE_THRESHOLDS={"stable": (-2.0, float("inf"))},
        UPLIFT_REPORT_THRESHOLD=2.0,
        MIN_CLUSTER_VELOCITY_COVERAGE_PCT=20.0,
        CLUSTER_EXPOSURE={}, DEFAULT_EXPOSURE="medium",
        EXPOSURE_RISK_MATRIX=[[1, 1, 1], [1, 2, 2], [2, 3, 4], [3, 4, 4]],
        RISK_COLORMAP={
            "low": "#2ecc71", "moderate": "#f39c12",
            "high": "#e74c3c", "very_high": "#8e44ad",
        },
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def touch(path, content=b"x"):
    with open(path, "wb") as fh:
        fh.write(content)
    return str(path)


def bump_mtime(path):
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


# ---------------------------------------------------------------- bug 2.1
def test_k_change_invalidates(tmp_path):
    s = fake_settings()
    out = touch(tmp_path / "landcover_clusters_kmeans.tif")
    emb = touch(tmp_path / "embeddings_norm.tif")

    p6 = stage_params("m4", settings_module=s, method="kmeans", k=6)
    write_sidecar(out, p6, inputs=[emb])
    assert cache_valid(out, p6, inputs=[emb])[0]

    p4 = stage_params("m4", settings_module=s, method="kmeans", k=4)
    hit, reason = cache_valid(out, p4, inputs=[emb])
    assert not hit and "k" in reason


def test_method_change_invalidates(tmp_path):
    s = fake_settings()
    out = touch(tmp_path / "landcover_clusters.tif")
    emb = touch(tmp_path / "embeddings_norm.tif")
    write_sidecar(out, stage_params("m4", settings_module=s,
                                    method="kmeans", k=4), inputs=[emb])
    hit, _ = cache_valid(out, stage_params("m4", settings_module=s,
                                           method="gmm", k=4), inputs=[emb])
    assert not hit


# ---------------------------------------------------------------- bug 2.2
def test_upstream_recompute_invalidates(tmp_path):
    """Calibration cache must miss when the labels raster it was built
    against is rewritten (the kmeans -> gmm scenario)."""
    s = fake_settings()
    labels = touch(tmp_path / "landcover_clusters.tif", b"kmeans labels")
    vel = touch(tmp_path / "velocity_masked.tif")
    cal_out = touch(tmp_path / "velocity_calibrated.tif")

    p = stage_params("cal", settings_module=s)
    write_sidecar(cal_out, p, inputs=[labels, vel])
    assert cache_valid(cal_out, p, inputs=[labels, vel])[0]

    touch(labels, b"gmm labels -- different content")  # M4 recomputed
    bump_mtime(labels)
    hit, reason = cache_valid(cal_out, p, inputs=[labels, vel])
    assert not hit and "input changed" in reason


# ---------------------------------------------------------------- bug 2.3
def test_settings_change_invalidates(tmp_path):
    out = touch(tmp_path / "velocity_masked.tif")
    p_old = stage_params("m1", settings_module=fake_settings())
    write_sidecar(out, p_old)
    p_new = stage_params(
        "m1", settings_module=fake_settings(INSAR_INCIDENCE_ANGLE_DEG=41.5))
    hit, reason = cache_valid(out, p_new)
    assert not hit and "INSAR_INCIDENCE_ANGLE_DEG" in reason


@pytest.mark.parametrize(
    ("setting", "new_value"),
    [
        ("INSAR_NODATA_VALUES", [0.0, -9999.0]),
        ("INSAR_VSTD_NODATA_VALUES", [0.0, -9999.0]),
        ("INSAR_RESAMPLING", "bilinear"),
        ("INSAR_VSTD_THRESHOLD", 10.0),
        ("INSAR_VSTD_SWEEP_THRESHOLDS", (5, 10, 20)),
    ],
)
def test_m1_result_affecting_settings_invalidate(tmp_path, setting, new_value):
    out = touch(tmp_path / "velocity_masked.tif")
    old = stage_params("m1", settings_module=fake_settings())
    write_sidecar(out, old)
    new = stage_params(
        "m1", settings_module=fake_settings(**{setting: new_value})
    )
    hit, reason = cache_valid(out, new)
    assert not hit and setting in reason


def test_m3_resampling_change_invalidates(tmp_path):
    out = touch(tmp_path / "velocity_aligned.tif")
    old = stage_params("m3", settings_module=fake_settings())
    write_sidecar(out, old)
    new = stage_params(
        "m3", settings_module=fake_settings(INSAR_RESAMPLING="bilinear")
    )
    hit, reason = cache_valid(out, new)
    assert not hit and "INSAR_RESAMPLING" in reason


@pytest.mark.parametrize(
    ("setting", "new_value"),
    [
        ("RANDOM_STATE", 7),
        ("SAMPLE_FRACTION", 0.2),
        ("HDBSCAN_MIN_CLUSTER_SIZE", 1000),
        ("HDBSCAN_MIN_SAMPLES", 100),
    ],
)
def test_m4_sampling_settings_invalidate(tmp_path, setting, new_value):
    out = touch(tmp_path / "clusters.tif")
    old = stage_params(
        "m4", settings_module=fake_settings(), method="kmeans", k=4
    )
    write_sidecar(out, old)
    new = stage_params(
        "m4",
        settings_module=fake_settings(**{setting: new_value}),
        method="kmeans",
        k=4,
    )
    hit, reason = cache_valid(out, new)
    assert not hit and setting in reason


# ------------------------------------------------- exposure-binding fault
def test_exposure_change_invalidates(tmp_path):
    out = touch(tmp_path / "risk_zones.tif")
    labels = touch(tmp_path / "landcover_clusters.tif")
    p_empty = stage_params("m4b", settings_module=fake_settings())
    write_sidecar(out, p_empty, inputs=[labels])

    p_filled = stage_params("m4b", settings_module=fake_settings(
        CLUSTER_EXPOSURE={0: "high", 1: "low"}))
    hit, reason = cache_valid(out, p_filled, inputs=[labels])
    assert not hit and "CLUSTER_EXPOSURE" in reason


def test_exposure_stale_against_new_labels(tmp_path):
    """Same exposure dict, but labels raster changed -> must miss."""
    s = fake_settings(CLUSTER_EXPOSURE={0: "high"})
    out = touch(tmp_path / "risk_zones.tif")
    labels = touch(tmp_path / "landcover_clusters.tif", b"run A")
    p = stage_params("m4b", settings_module=s)
    write_sidecar(out, p, inputs=[labels])

    touch(labels, b"run B - labels permuted")
    bump_mtime(labels)
    assert not cache_valid(out, p, inputs=[labels])[0]


# ---------------------------------------------------------------- misc
def test_legacy_output_without_sidecar(tmp_path):
    out = touch(tmp_path / "old_output.tif")
    hit, reason = cache_valid(out, {"a": 1})
    assert not hit and "sidecar" in reason


def test_legacy_sidecar_schema_invalidates(tmp_path):
    out = touch(tmp_path / "output.tif")
    sidecar = str(out) + ".cachemeta.json"
    with open(sidecar, "w", encoding="utf-8") as stream:
        json.dump({
            "fingerprint": "old",
            "params": {},
            "inputs": [],
        }, stream)
    hit, reason = cache_valid(out, {})
    assert not hit and "sidecar schema changed" in reason


def test_sidecar_write_is_atomic(tmp_path):
    out = touch(tmp_path / "output.tif")
    sidecar = write_sidecar(out, {"a": 1})
    assert os.path.exists(sidecar)
    assert not os.path.exists(sidecar + ".tmp")


def test_missing_output(tmp_path):
    hit, reason = cache_valid(str(tmp_path / "nope.tif"), {"a": 1})
    assert not hit and "output missing" in reason


def test_added_input_invalidates_exact_input_set(tmp_path):
    out = touch(tmp_path / "velocity_aligned.tif")
    emb = touch(tmp_path / "emb.tif")
    vel = touch(tmp_path / "vel.tif")
    vstd = touch(tmp_path / "vstd.tif")
    params = {"__stage__": "m3"}
    write_sidecar(out, params, inputs=[emb, vel])

    hit, reason = cache_valid(out, params, inputs=[emb, vel, vstd])
    assert not hit and "input set changed" in reason and "added" in reason


def test_removed_input_invalidates_exact_input_set(tmp_path):
    out = touch(tmp_path / "velocity_aligned.tif")
    emb = touch(tmp_path / "emb.tif")
    vel = touch(tmp_path / "vel.tif")
    vstd = touch(tmp_path / "vstd.tif")
    params = {"__stage__": "m3"}
    write_sidecar(out, params, inputs=[emb, vel, vstd])

    hit, reason = cache_valid(out, params, inputs=[emb, vel])
    assert not hit and "input set changed" in reason and "removed" in reason


def test_stage_table_matches_real_settings():
    """Drift guard: every setting the fingerprint table declares must exist
    in the real config/settings.py — catches renames that would otherwise
    silently break cache invalidation."""
    from src.utils.stage_cache import _STAGE_SETTINGS
    import config.settings as real
    for stage in _STAGE_SETTINGS:
        stage_params(stage, settings_module=real)  # raises on any mismatch


def test_declared_setting_missing_fails_loud():
    s = fake_settings()
    del s.__dict__["COHERENCE_THRESHOLD"]
    with pytest.raises(AttributeError):
        stage_params("m1", settings_module=s)
