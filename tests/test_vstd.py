"""
Tests for the vstd (velocity-uncertainty) masking path.

Covers the contract of apply_vstd_mask and vstd_survival_sweep in M1, and the
vstd carry-through signature of M3's align_datasets. These guard the quality-
masking behaviour introduced after the noise diagnosis (per-cluster sigma of
32-53 mm/yr exceeded the +/-25 mm/yr severity thresholds; masking by LiCSBAS
vstd is the remedy).
"""

import sys
import os
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.m1_insar_ingestion import apply_vstd_mask, vstd_survival_sweep


def make_pair(vel_values, vstd_values):
    """Build (1, H, W) float32 rasters from equal-shape 2-D lists."""
    vel = np.array([vel_values], dtype=np.float32)
    vstd = np.array([vstd_values], dtype=np.float32)
    assert vel.shape == vstd.shape
    return vel, vstd


class TestApplyVstdMask:

    def test_over_threshold_pixels_are_masked(self):
        vel, vstd = make_pair(
            [[-30.0, -30.0, -30.0]],
            [[5.0, 15.0, 40.0]],       # under, at, over (threshold 15)
        )
        out, counts = apply_vstd_mask(vel, vstd, threshold=15.0)
        assert not np.isnan(out[0, 0, 0])        # 5.0  <= 15 -> kept
        assert not np.isnan(out[0, 0, 1])        # 15.0 <= 15 -> kept (inclusive)
        assert np.isnan(out[0, 0, 2])            # 40.0 > 15  -> masked
        assert counts == {"n_over_threshold": 1, "n_missing_vstd": 0, "n_kept": 2}

    def test_missing_vstd_masks_velocity_and_is_counted_separately(self):
        # A finite velocity whose uncertainty is unknown cannot support
        # classification; it must be masked AND reported as missing, not
        # lumped in with over-threshold (footprint mismatches must be visible).
        vel, vstd = make_pair(
            [[-30.0, -30.0]],
            [[np.nan, 5.0]],
        )
        out, counts = apply_vstd_mask(vel, vstd, threshold=15.0)
        assert np.isnan(out[0, 0, 0])
        assert not np.isnan(out[0, 0, 1])
        assert counts["n_missing_vstd"] == 1
        assert counts["n_over_threshold"] == 0
        assert counts["n_kept"] == 1

    def test_velocity_nodata_stays_nodata_and_is_not_counted(self):
        # NaN velocity pixels are outside all three counters: they were never
        # candidates for keeping or masking.
        vel, vstd = make_pair(
            [[np.nan, np.nan]],
            [[5.0, np.nan]],
        )
        out, counts = apply_vstd_mask(vel, vstd, threshold=15.0)
        assert np.isnan(out).all()
        assert counts == {"n_over_threshold": 0, "n_missing_vstd": 0, "n_kept": 0}

    def test_counts_partition_velocity_valid_pixels(self):
        # kept + over + missing must exactly equal the number of finite
        # velocity pixels — no pixel silently uncounted or double-counted.
        rng = np.random.RandomState(42)
        vel = rng.uniform(-60, 20, size=(1, 40, 40)).astype(np.float32)
        vstd = rng.uniform(0, 40, size=(1, 40, 40)).astype(np.float32)
        vel[0, rng.rand(40, 40) < 0.2] = np.nan     # 20% velocity nodata
        vstd[0, rng.rand(40, 40) < 0.1] = np.nan    # 10% vstd gaps
        n_vel_valid = int((~np.isnan(vel[0])).sum())

        _, counts = apply_vstd_mask(vel, vstd, threshold=15.0)
        assert (counts["n_kept"] + counts["n_over_threshold"]
                + counts["n_missing_vstd"]) == n_vel_valid

    def test_masking_is_idempotent(self):
        vel, vstd = make_pair([[-30.0, -30.0]], [[5.0, 40.0]])
        out1, c1 = apply_vstd_mask(vel, vstd, threshold=15.0)
        out2, c2 = apply_vstd_mask(out1, vstd, threshold=15.0)
        assert c2["n_over_threshold"] == 0          # already masked
        assert c2["n_kept"] == c1["n_kept"]
        assert np.isnan(out2[0, 0, 1])


class TestVstdSurvivalSweep:

    def test_survival_is_monotonic_in_threshold(self):
        rng = np.random.RandomState(0)
        vel = rng.uniform(-60, 20, size=(1, 50, 50)).astype(np.float32)
        vstd = rng.uniform(0, 60, size=(1, 50, 50)).astype(np.float32)
        sweep = vstd_survival_sweep(vstd, vel)
        pcts = [p for _, p in sweep]
        assert pcts == sorted(pcts)                  # looser threshold >= survival

    def test_known_fractions(self):
        vel, vstd = make_pair(
            [[-1.0, -1.0, -1.0, -1.0]],
            [[2.0, 8.0, 12.0, 100.0]],
        )
        sweep = dict(vstd_survival_sweep(vstd, vel, thresholds=(5, 10, 15)))
        assert sweep[5] == 25.0
        assert sweep[10] == 50.0
        assert sweep[15] == 75.0

    def test_all_nodata_velocity_reports_zero(self):
        vel, vstd = make_pair([[np.nan, np.nan]], [[5.0, 5.0]])
        sweep = vstd_survival_sweep(vstd, vel, thresholds=(10,))
        assert sweep == [(10, 0.0)]


class TestAlignDatasetsVstdSignature:

    def test_returns_none_vstd_when_not_provided(self, tmp_path, monkeypatch):
        # align_datasets must return a 3-tuple with aligned_vstd None when no
        # vstd is passed — the pipeline call site depends on this shape.
        rasterio = pytest.importorskip("rasterio")
        from rasterio.transform import from_origin
        from src.m3_feature_fusion import align_datasets

        transform = from_origin(0, 300, 30, 30)
        profile = dict(driver="GTiff", dtype="float32", width=10, height=10,
                       count=1, crs="EPSG:32748", transform=transform,
                       nodata=np.nan)

        emb_path = str(tmp_path / "emb.tif")
        vel_path = str(tmp_path / "vel.tif")
        with rasterio.open(emb_path, "w", **profile) as d:
            d.write(np.ones((1, 10, 10), dtype=np.float32))
        with rasterio.open(vel_path, "w", **profile) as d:
            d.write(np.full((1, 10, 10), -30.0, dtype=np.float32))

        emb_out, vel_out, vstd_out = align_datasets(
            emb_path, vel_path, output_dir=str(tmp_path))
        assert emb_out == emb_path
        assert os.path.exists(vel_out)
        assert vstd_out is None

    def test_aligns_vstd_when_provided(self, tmp_path):
        rasterio = pytest.importorskip("rasterio")
        from rasterio.transform import from_origin
        from src.m3_feature_fusion import align_datasets

        transform = from_origin(0, 300, 30, 30)
        profile = dict(driver="GTiff", dtype="float32", width=10, height=10,
                       count=1, crs="EPSG:32748", transform=transform,
                       nodata=np.nan)

        paths = {}
        for name, fill in (("emb", 1.0), ("vel", -30.0), ("vstd", 8.0)):
            p = str(tmp_path / f"{name}.tif")
            with rasterio.open(p, "w", **profile) as d:
                d.write(np.full((1, 10, 10), fill, dtype=np.float32))
            paths[name] = p

        _, vel_out, vstd_out = align_datasets(
            paths["emb"], paths["vel"], output_dir=str(tmp_path),
            insar_vstd_path=paths["vstd"])
        assert vstd_out is not None and os.path.exists(vstd_out)

        with rasterio.open(vstd_out) as s:
            v = s.read(1)
        assert np.allclose(v[~np.isnan(v)], 8.0)     # values preserved (nearest)


class TestPreprocessInsarVstdIntegration:

    def test_los_scales_vstd_and_combines_quality_masks(
            self, tmp_path, monkeypatch):
        rasterio = pytest.importorskip("rasterio")
        from rasterio.transform import from_origin
        import src.m1_insar_ingestion as m1

        monkeypatch.setattr(m1, "COMMON_CRS", "EPSG:32748")
        monkeypatch.setattr(m1, "COMMON_RESOLUTION", 30)
        monkeypatch.setattr(m1, "INSAR_RESAMPLING", "nearest")
        monkeypatch.setattr(m1, "INSAR_VELOCITY_IS_LOS", True)
        monkeypatch.setattr(m1, "INSAR_INCIDENCE_ANGLE_DEG", 60.0)
        monkeypatch.setattr(m1, "INSAR_VSTD_THRESHOLD", 15.0)
        monkeypatch.setattr(m1, "COHERENCE_THRESHOLD", 0.3)
        monkeypatch.setattr(m1, "INSAR_NODATA_VALUES", [])
        monkeypatch.setattr(m1, "INSAR_VSTD_NODATA_VALUES", [])

        profile = dict(
            driver="GTiff", dtype="float32", width=4, height=1, count=1,
            crs="EPSG:32748", transform=from_origin(0, 30, 30, 30),
            nodata=np.nan,
        )
        inputs = {
            "velocity": np.array([[-10, -10, -10, -10]], dtype=np.float32),
            # Pixel 1 fails vstd after LOS scaling; pixels 2 and 3 fail
            # coherence (low and missing, respectively).
            "vstd": np.array([[5, 10, 5, 5]], dtype=np.float32),
            "coherence": np.array([[0.9, 0.9, 0.2, np.nan]],
                                  dtype=np.float32),
        }
        paths = {}
        for name, values in inputs.items():
            path = tmp_path / f"{name}.tif"
            with rasterio.open(path, "w", **profile) as dst:
                dst.write(values, 1)
            paths[name] = str(path)

        output_dir = tmp_path / "processed"
        final_path = m1.preprocess_insar(
            paths["velocity"], paths["coherence"],
            output_dir=str(output_dir), vstd_path=paths["vstd"],
        )

        assert os.path.basename(final_path) == "velocity_masked.tif"
        with rasterio.open(final_path) as src:
            velocity = src.read(1)
            velocity_tags = src.tags()
        assert velocity[0, 0] == pytest.approx(-20.0)
        assert np.isnan(velocity[0, 1:]).all()
        assert velocity_tags["velocity_reference"] == "vertical"

        vstd_path = output_dir / "vstd_vertical.tif"
        with rasterio.open(vstd_path) as src:
            vstd = src.read(1)
            vstd_tags = src.tags()
        np.testing.assert_allclose(vstd[0], [10, 20, 10, 10], rtol=1e-5)
        assert vstd_tags["uncertainty_reference"] == "vertical"
        assert float(vstd_tags["los_to_vertical_factor"]) == \
            pytest.approx(2.0, rel=1e-5)
