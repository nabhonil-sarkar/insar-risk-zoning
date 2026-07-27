"""Small end-to-end smoke test for the two-stage pipeline core."""

import os

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin


def write_raster(path, data, transform, resolution_crs="EPSG:32748"):
    profile = {
        "driver": "GTiff",
        "height": data.shape[1],
        "width": data.shape[2],
        "count": data.shape[0],
        "dtype": str(data.dtype),
        "crs": resolution_crs,
        "transform": transform,
        "nodata": np.nan,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data)
    return str(path)


def test_tiny_pipeline_from_raw_quality_stack_to_overlay(tmp_path, monkeypatch):
    import src.m1_insar_ingestion as m1
    from src.m3_feature_fusion import align_datasets, prepare_embedding_features
    from src.m4_clustering import cluster_embeddings
    from src.m4b_insar_overlay import run_insar_overlay

    monkeypatch.setattr(m1, "COMMON_CRS", "EPSG:32748")
    monkeypatch.setattr(m1, "COMMON_RESOLUTION", 30)
    monkeypatch.setattr(m1, "INSAR_RESAMPLING", "nearest")
    monkeypatch.setattr(m1, "INSAR_VELOCITY_IS_LOS", False)
    monkeypatch.setattr(m1, "INSAR_VSTD_THRESHOLD", 15.0)
    monkeypatch.setattr(m1, "INSAR_NODATA_VALUES", [])
    monkeypatch.setattr(m1, "INSAR_VSTD_NODATA_VALUES", [])

    # Six-by-six embedding grid with two deliberately separable land-cover
    # populations. This is already "normalized" for the smoke test.
    embeddings = np.empty((4, 6, 6), dtype=np.float32)
    embeddings[:, :, :3] = -2.0
    embeddings[:, :, 3:] = 2.0
    embeddings[1] += np.linspace(-0.1, 0.1, 6, dtype=np.float32)[:, None]
    embedding_path = write_raster(
        tmp_path / "embeddings_norm.tif",
        embeddings,
        from_origin(0, 180, 30, 30),
    )

    # Coarser, matched raw LiCSBAS-like stack covering the same extent.
    velocity = np.array(
        [[[-1, -12, -30], [-1, -12, -30], [-1, -12, -30]]],
        dtype=np.float32,
    )
    vstd = np.full((1, 3, 3), 5.0, dtype=np.float32)
    velocity_path = write_raster(
        tmp_path / "jakarta_vel.tif",
        velocity,
        from_origin(0, 180, 60, 60),
    )
    vstd_path = write_raster(
        tmp_path / "jakarta_vstd.tif",
        vstd,
        from_origin(0, 180, 60, 60),
    )

    processed_dir = tmp_path / "processed_insar"
    processed_velocity = m1.preprocess_insar(
        velocity_path,
        output_dir=str(processed_dir),
        vstd_path=vstd_path,
    )
    assert os.path.exists(processed_velocity)
    assert (processed_dir / "vstd_vertical.tif").exists()

    aligned_dir = tmp_path / "aligned"
    emb_aligned, vel_aligned, vstd_aligned = align_datasets(
        embedding_path,
        processed_velocity,
        output_dir=str(aligned_dir),
        insar_vstd_path=str(processed_dir / "vstd_vertical.tif"),
    )
    assert os.path.exists(vstd_aligned)

    features, valid_mask, full_features, profile = \
        prepare_embedding_features(emb_aligned, sample=False)
    labels, label_raster, metrics = cluster_embeddings(
        features,
        valid_mask,
        full_features,
        profile,
        method="kmeans",
        n_clusters=2,
        output_dir=str(tmp_path / "clusters"),
    )
    assert metrics["n_clusters"] == 2
    assert label_raster.shape == (1, 6, 6)

    overlay = run_insar_overlay(
        labels,
        valid_mask,
        vel_aligned,
        profile,
        output_dir=str(tmp_path / "overlay"),
    )
    assert len(overlay["cluster_stats"]) == 2
    assert set(np.unique(overlay["severity"])) >= {0, 2, 3}
    assert (tmp_path / "overlay" / "subsidence_severity.tif").exists()


def test_cli_help_smoke(capsys):
    from scripts.run_full_pipeline import cli

    with pytest.raises(SystemExit) as exc:
        cli(["--help"])
    assert exc.value.code == 0
    assert "--force-from" in capsys.readouterr().out


def test_production_mode_requires_complete_explicit_exposure(
        tmp_path, monkeypatch):
    import scripts.run_full_pipeline as pipeline

    labels = np.array([0, 0, 1, 1])
    monkeypatch.setattr(pipeline, "CLUSTER_EXPOSURE", {})
    with pytest.raises(SystemExit):
        pipeline.validate_cluster_exposure(
            labels, label_file_path=None, production=True
        )

    monkeypatch.setattr(pipeline, "CLUSTER_EXPOSURE", {0: "high"})
    with pytest.raises(SystemExit):
        pipeline.validate_cluster_exposure(
            labels, label_file_path=None, production=True
        )

    monkeypatch.setattr(
        pipeline, "CLUSTER_EXPOSURE", {0: "high", 1: "low"}
    )
    pipeline.validate_cluster_exposure(
        labels, label_file_path=None, production=True
    )


def test_deprecated_calibration_script_refuses_to_run():
    from scripts.calibrate_velocity import main as deprecated_calibration

    with pytest.raises(SystemExit) as exc:
        deprecated_calibration()
    assert exc.value.code == 1
