"""Fail-closed and write-once runner tests use synthetic files only."""

import json
import subprocess
from unittest.mock import Mock

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from scripts import run_alphaearth_surface_type as r


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")
    return r.digest(path)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "ROOT", tmp_path)
    monkeypatch.setattr(r, "revision", lambda _: "abcd" * 10)
    t = from_origin(106.5, -6.1, .001, .001)
    grid = dict(width=6, height=6, transform=list(t)[:6], crs="EPSG:4326")
    roi = [106, -7, 107, -6]
    pins = {
        p.as_posix(): write(tmp_path / p, obj) for p, obj in [
            (r.GRID, {"frozen_reference_grid": grid}),
            (r.DATA / "gcs_v1_inventory.json", {"synthetic": True}),
            (r.FULL / "contract.json", {"roi": roi}),
        ]
    }
    monkeypatch.setattr(r, "PINS", pins)
    contract = pins[(r.FULL / "contract.json").as_posix()]

    def tif(path, data, nodata, descriptions=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        if data.ndim == 2:
            data = data[None]
        with rasterio.open(path, "w", driver="GTiff", height=6, width=6, count=len(data),
                           dtype=data.dtype, crs="EPSG:4326", transform=t, nodata=nodata) as ds:
            ds.write(data)
            ds.descriptions = descriptions or (path.stem,)
            ds.update_tags(contract_sha256=contract)
        return r.digest(path)

    annual, qa = {}, {}
    for y in range(2020, 2026):
        annual[str(y)] = tif(tmp_path / r.FULL / f"Jakarta_GCS20m_on30m_{y}_qint8.tif",
                             np.full((64, 6, 6), 10, dtype="int8"), -128,
                             tuple(f"A{i:02}" for i in range(64)))
        qa[str(y)] = write(tmp_path / r.FULL / f"{y}_qa.json", dict(year=y, decision="pass",
                           contract_sha256=contract, sha256=annual[str(y)], inside=36, valid=36, missing_inside=0))
    maps = []
    for a, b in sorted(r.EXPECTED_PAIRS):
        sha = tif(tmp_path / r.MAPS / f"cosine_{a}_{b}.tif", np.full((6, 6), .3 if a == 2022 else .1, dtype="float32"), -9999)
        maps.append(dict(years=[a, b], sha256=sha, joint_valid=36, total_cells=36))
    monkeypatch.setattr(r, "MANIFEST_SHA", write(tmp_path / r.MAPS / "manifest.json",
        dict(comparisons=maps, annual_sha256=annual, annual_qa_sha256=qa, annual_contract_sha256=contract, inside_roi_centres=36)))
    wc = tmp_path / "classes.tif"
    monkeypatch.setattr(r, "WC_SHA", tif(wc, np.full((6, 6), 10, dtype="uint8"), 0))
    stage = tmp_path / "stage"
    stage.mkdir()
    grid, roi, manifest, hashes, paths = r.preflight(tmp_path, wc, stage)
    census, *_ = r.inspect(stage, grid, roi, manifest, paths)
    census.update(input_sha256=hashes, worldcover_sha256=r.WC_SHA)
    write(tmp_path / r.DEST / "inventory.json", census)
    monkeypatch.setattr(r, "PROTOCOL_SHA256", r.register())
    return tmp_path, wc


@pytest.mark.parametrize("bad", ["annual", "qa", "last_map", "worldcover", "manifest", "grid", "protocol", "inventory"])
def test_bad_hash_stops_before_raster_open(bundle, monkeypatch, bad):
    root, wc = bundle
    paths = {
        "annual": root / r.FULL / "Jakarta_GCS20m_on30m_2025_qint8.tif",
        "qa": root / r.FULL / "2025_qa.json", "last_map": root / r.MAPS / "cosine_2024_2025.tif",
        "worldcover": wc, "manifest": root / r.MAPS / "manifest.json", "grid": root / r.GRID,
        "protocol": root / r.DEST / "protocol.json", "inventory": root / r.DEST / "inventory.json",
    }
    with paths[bad].open("ab") as stream:
        stream.write(b"drift")
    opener = Mock(side_effect=AssertionError("Raster open before hash gate"))
    monkeypatch.setattr(r.rasterio, "open", opener)
    with pytest.raises(ValueError, match="SHA-256"):
        r.run(wc, r.PROTOCOL_SHA256)
    opener.assert_not_called()
    assert not (root / r.DEST / "run").exists()


def test_wrong_approval_stops_before_any_input_read(bundle, monkeypatch):
    _, wc = bundle
    reader = Mock(side_effect=AssertionError("input read"))
    monkeypatch.setattr(r, "checked_json", reader)
    with pytest.raises(ValueError, match="approval"):
        r.run(wc, "wrong")
    reader.assert_not_called()


def test_synthetic_run_outputs_provenance_and_never_overwrites(bundle):
    root, wc = bundle
    path = r.run(wc, r.PROTOCOL_SHA256)
    result = json.loads((path / "results.json").read_bytes())
    assert len(result["contrasts"]) == 440
    assert result["provenance"]["code_commit"] == "abcd" * 10
    assert result["provenance"]["worldcover_sha256"] == r.digest(wc)
    for name, sha in result["output_sha256"].items():
        assert r.digest(path / name) == sha
    before = r.digest(path / "results.json")
    with pytest.raises(FileExistsError):
        r.run(wc, r.PROTOCOL_SHA256)
    assert r.digest(path / "results.json") == before
    with pytest.raises(FileExistsError):
        r.register()


def test_inventory_inspection_never_reads_distance_bands(bundle, monkeypatch):
    root, wc = bundle
    stage = root / "new_stage"
    stage.mkdir()
    grid, roi, manifest, _, paths = r.preflight(root, wc, stage)
    actual_open = rasterio.open

    class Guard:
        def __init__(self, path):
            self.ds = actual_open(path)
            self.is_wc = path.name == "worldcover.tif"
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.ds.close()
        def __getattr__(self, key):
            if key == "read" and not self.is_wc:
                raise AssertionError("Distance/annual band read during inventory")
            return getattr(self.ds, key)
    monkeypatch.setattr(r.rasterio, "open", Guard)
    census, *_ = r.inspect(stage, grid, roi, manifest, paths)
    assert census["joint_valid_count"] == 36


@pytest.mark.parametrize("bad", ["geometry", "mask", "class_code", "nan", "range"])
def test_metadata_masks_and_values_fail_closed(bundle, monkeypatch, bad):
    root, wc = bundle
    preflight = r.preflight

    def staged_corruption(root, wc, stage):
        evidence = preflight(root, wc, stage)
        # Exercise downstream guards independently of the checksum tests.
        path = stage / ("worldcover.tif" if bad == "class_code" else "cosine_2022_2023.tif")
        with rasterio.open(path, "r+") as ds:
            if bad == "geometry":
                ds.transform = from_origin(100, 0, .001, .001)
            else:
                a = ds.read(1)
                a[0, 0] = {"mask": -9999, "class_code": 42, "nan": np.nan, "range": 3}[bad]
                ds.write(a, 1)
        return evidence

    monkeypatch.setattr(r, "preflight", staged_corruption)
    with pytest.raises(ValueError):
        r.run(wc, r.PROTOCOL_SHA256)
    assert not (root / r.DEST / "run").exists()


@pytest.mark.parametrize("bad", ["duplicate_comparison", "contract", "failed_qa"])
def test_hash_consistent_invalid_metadata_fails_before_open(bundle, monkeypatch, bad):
    root, wc = bundle
    path = root / r.MAPS / "manifest.json"
    manifest = json.loads(path.read_bytes())
    if bad == "duplicate_comparison":
        manifest["comparisons"][-1] = manifest["comparisons"][0]
    elif bad == "contract":
        manifest["annual_contract_sha256"] = "wrong"
    else:
        qa_path = root / r.FULL / "2025_qa.json"
        qa = json.loads(qa_path.read_bytes())
        qa["decision"] = "fail"
        manifest["annual_qa_sha256"]["2025"] = write(qa_path, qa)
    monkeypatch.setattr(r, "MANIFEST_SHA", write(path, manifest))
    opener = Mock(side_effect=AssertionError("Unexpected raster open"))
    monkeypatch.setattr(r.rasterio, "open", opener)
    stage = root / "bad_metadata_stage"
    stage.mkdir()
    with pytest.raises(ValueError, match="manifest|QA"):
        r.preflight(root, wc, stage)
    opener.assert_not_called()


def test_revision_requires_clean_tracked_implementation(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()
    git("init", "-q")
    for name in ("scripts/alphaearth_surface_type.py", "scripts/run_alphaearth_surface_type.py",
                 "scripts/run_alphaearth_tile_seam.py", "tests/test_alphaearth_surface_type.py",
                 "tests/test_run_alphaearth_surface_type.py"):
        p = tmp_path / name
        p.parent.mkdir(exist_ok=True)
        p.write_text("# synthetic\n")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    assert r.revision(tmp_path) == git("rev-parse", "HEAD")
    (tmp_path / "new.txt").write_text("dirty")
    with pytest.raises(ValueError, match="clean"):
        r.revision(tmp_path)
