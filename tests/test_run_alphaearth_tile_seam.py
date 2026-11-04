"""End-to-end gate tests. All TIFFs and manifests live under pytest's tmp_path."""

import hashlib
import json
import subprocess
from unittest.mock import Mock

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from scripts import run_alphaearth_tile_seam as runner


def test_revision_requires_clean_committed_sources(tmp_path):
    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(tmp_path), *args], text=True
        ).strip()

    git("init", "-q")
    sources = tmp_path / "scripts"
    sources.mkdir()
    for name in ("alphaearth_tile_seam.py", "run_alphaearth_tile_seam.py"):
        (sources / name).write_text("# synthetic repository\n", encoding="utf8")
    git("add", "scripts")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "fixture",
    )
    assert runner.revision(tmp_path) == git("rev-parse", "HEAD")
    (sources / "alphaearth_tile_seam.py").write_text("# changed\n", encoding="utf8")
    with pytest.raises(ValueError, match="dirty"):
        runner.revision(tmp_path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf8")
    return digest(path)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "revision", lambda _: "abcd" * 10)
    t = from_origin(106.47, -6.1, 0.001, 0.001)
    grid = dict(width=6, height=6, transform=list(t)[:6], crs="EPSG:4326")
    tiles = [
        dict(year=y, native_bounds=b, crs="EPSG:32748")
        for y in range(2020, 2026)
        for b in reversed(runner.BOUNDS)
    ]
    pins = {
        p.as_posix(): write_json(root / p, obj)
        for p, obj in [
            (runner.INV, {"tiles": tiles}),
            (runner.GRID, {"frozen_reference_grid": grid}),
            (runner.FULL, {"roi": [106, -7, 107, -6]}),
        ]
    }
    protocol_hash = write_json(
        root / runner.PROTOCOL, {"geometry_sources_repo_relative_sha256": pins}
    )
    monkeypatch.setattr(runner.stats, "PROTOCOL_SHA256", protocol_hash)

    def tif(path, data, nodata):
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=6,
            height=6,
            count=1,
            crs="EPSG:4326",
            transform=t,
            dtype=data.dtype,
            nodata=nodata,
        ) as dst:
            dst.write(data, 1)
            dst.set_band_description(1, path.stem)
            dst.update_tags(contract_sha256=pins[runner.FULL.as_posix()])
        return digest(path)

    wc = root / "classes.tif"
    monkeypatch.setattr(
        runner, "WC_SHA", tif(wc, np.full((6, 6), 10, dtype="uint8"), 0)
    )
    (root / runner.MAPS).mkdir()
    maps = []
    for a, b in (*runner.stats.COMPARISONS, (2020, 2023)):
        sha = tif(
            root / runner.MAPS / f"cosine_{a}_{b}.tif",
            np.ones((6, 6), dtype="float32"),
            -9999,
        )
        maps.append(dict(years=[a, b], sha256=sha, joint_valid=36, total_cells=36))
    monkeypatch.setattr(
        runner,
        "MANIFEST_SHA",
        write_json(
            root / runner.MAPS / "manifest.json",
            dict(
                annual_contract_sha256=pins[runner.FULL.as_posix()],
                inside_roi_centres=36,
                comparisons=maps,
            ),
        ),
    )
    return root, wc


@pytest.mark.parametrize(
    "bad",
    ["last_map", "worldcover", "manifest", "protocol", "inventory", "bounds_2025"],
)
def test_gates_abort_before_any_raster_open(bundle, monkeypatch, bad):
    root, wc = bundle
    if bad == "bounds_2025":
        # Even an internally hash-consistent inventory must match frozen bounds.
        ip, pp = root / runner.INV, root / runner.PROTOCOL
        inv, protocol = json.loads(ip.read_bytes()), json.loads(pp.read_bytes())
        inv["tiles"][-1]["native_bounds"][2] += 10
        protocol["geometry_sources_repo_relative_sha256"][runner.INV.as_posix()] = (
            write_json(ip, inv)
        )
        monkeypatch.setattr(runner.stats, "PROTOCOL_SHA256", write_json(pp, protocol))
    else:
        path = {
            "last_map": root / runner.MAPS / "cosine_2020_2023.tif",
            "worldcover": wc,
            "manifest": root / runner.MAPS / "manifest.json",
            "protocol": root / runner.PROTOCOL,
            "inventory": root / runner.INV,
        }[bad]
        with path.open("ab") as f:
            f.write(b"unexpected")
    opener = Mock(side_effect=AssertionError("unexpected raster open"))
    monkeypatch.setattr(runner.rasterio, "open", opener)
    with pytest.raises(ValueError, match="2025|SHA-256 mismatch"):
        runner.run(wc, runner.stats.PROTOCOL_SHA256)
    opener.assert_not_called()
    assert not (root / runner.PROTOCOL.parent / "results.json").exists()


def test_synthetic_run_writes_commit_and_refuses_overwrite(bundle, monkeypatch):
    root, wc = bundle
    # Change only the expected endpoint census for this 36-cell synthetic map.
    headline = runner.stats.headline
    monkeypatch.setattr(
        runner.stats,
        "headline",
        lambda a, x: headline(a, x, expected_counts=(36, 36, 4, 4)),
    )
    with pytest.raises(ValueError, match="approval"):
        runner.run(wc, "wrong")
    path = runner.run(wc, runner.stats.PROTOCOL_SHA256)
    raw = path.read_bytes()
    result = json.loads(raw)
    assert result["provenance"]["code_commit"] == "abcd" * 10
    assert result["provenance"]["worldcover_sha256"] == digest(wc)
    assert len(result["provenance"]["maps"]) == 7
    assert len(result["strip_tests"]) == 18
    assert result["endpoint_sensitivity"]["original"]["valid_share"]["n"] == 4
    with pytest.raises(FileExistsError):
        runner.run(wc, runner.stats.PROTOCOL_SHA256)
    assert path.read_bytes() == raw
