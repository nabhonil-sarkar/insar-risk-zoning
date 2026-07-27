"""Tests for schema-versioned, atomic pipeline state."""

import json

import pandas as pd
import pytest


def example_risk_summary():
    return pd.DataFrame([{
        "cluster": 0,
        "cluster_risk": "high",
        "total_pixels": 10,
        "pct_velocity_coverage": 80.0,
        "vel_mean": -12.5,
        "pct_moderate_or_worse": 40.0,
        "pct_rapid": 10.0,
    }])


def test_pipeline_state_is_schema_versioned_and_atomic(tmp_path, monkeypatch):
    import scripts.run_full_pipeline as pipeline

    state_path = tmp_path / "pipeline_state.json"
    monkeypatch.setattr(pipeline, "PIPELINE_STATE_FILE", str(state_path))
    pipeline.save_pipeline_state(
        paths={"velocity_aligned": "velocity.tif"},
        config={"method": "kmeans", "n_clusters": 1},
        risk_summary_df=example_risk_summary(),
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["schema_version"] == pipeline.PIPELINE_STATE_SCHEMA_VERSION
    assert state["risk_summary"][0]["cluster"] == 0
    assert not (tmp_path / "pipeline_state.json.tmp").exists()


def test_subcluster_rejects_legacy_state_without_schema(tmp_path):
    from scripts.subcluster_analysis import load_pipeline_state

    state_path = tmp_path / "legacy.json"
    state_path.write_text(json.dumps({
        "timestamp": "2026-07-06T00:00:00",
        "config": {"method": "kmeans", "n_clusters": 4},
        "paths": {},
        "risk_summary": [],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported pipeline-state schema"):
        load_pipeline_state(str(state_path))
