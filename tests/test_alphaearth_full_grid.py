import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from scripts import build_alphaearth_full_grid as b
from scripts import alphaearth_full_grid_change as ch
from scripts.alphaearth_full_grid_change import vectors, distance, NODATA


def test_joint_support_and_all_axis_distance():
    q = np.zeros((64, 1, 5), dtype="int8")
    q[0, 0, :3] = 81
    q[:, 0, 4] = -128
    r = q.copy()
    r[0, 0, 1] = -81
    r[:, 0, 2] = -128
    actual = distance(vectors(q), vectors(r))
    np.testing.assert_allclose(actual, [[0, 2, NODATA, NODATA, NODATA]])
    r[32, 0, 0] = -128
    with pytest.raises(ValueError, match="Partial"):
        vectors(r)


def test_nonlinear_decode_before_cosine():
    a = np.zeros((64, 1, 1), dtype="int8")
    z = a.copy()
    a[:2, 0, 0] = [20, 40]
    z[1, 0, 0] = 40
    assert float(distance(vectors(a), vectors(z)).item()) == pytest.approx(
        1 - 4 / np.sqrt(17)
    )


def test_bounded_merge_and_immutable_range_reader(tmp_path):
    assert b.merge([(8, 3), (13, 9), (72, 10)]) == [(8, 14), (72, 10)]
    with pytest.raises(ValueError):
        b.merge([(20, 10), (28, 10)])
    f = tmp_path / "range.bin"
    f.write_bytes(b"abcde")
    d = b.DiskRanges({10: f}, 20)
    d.seek(11)
    assert d.read(3) == b"bcd"
    with pytest.raises(IOError):
        d.read(3)


@pytest.mark.parametrize("bad", ["none", "overlap", "gap", "sample"])
def test_year_assembly_is_fail_closed(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(b, "OUT", tmp_path)
    monkeypatch.setattr(b.edge, "OUT", tmp_path)
    inside = np.ones((3, 5), dtype=bool)
    inside[-1] = False
    rr, cc = np.nonzero(inside)
    geom = (inside, rr, cc, cc.astype(float), rr.astype(float))
    a = dict(native_bounds=[0, 0, 2, 3], object=dict(name="west"))
    z = dict(
        native_bounds=[{"overlap": 1, "gap": 3}.get(bad, 2), 0, 5, 3],
        object=dict(name="east"),
    )

    def fill(tile, limit, x, y, rc, out):
        out[rc] = 5 if tile is a else 30
        return dict(assigned=len(y))

    monkeypatch.setattr(b, "populate", fill)
    b.g.write_new(
        tmp_path / "2020.json",
        dict(
            samples=[
                dict(
                    reference_rc=[0, 2],
                    q=[30 if bad != "sample" else 29] * 64,
                    inside=True,
                    valid=True,
                )
            ]
        ),
    )
    with rasterio.open(
        tmp_path / "ref.tif",
        "w",
        driver="GTiff",
        width=5,
        height=3,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(106, -6, 0.01, 0.01),
    ) as ref:
        args = (2020, geom, ref, [a, z], {"west": {}, "east": {}}, "frozen")
        if bad != "none":
            with pytest.raises(ValueError):
                b.write_year(*args)
            assert not b.band_path(2020).exists()
            assert not (tmp_path / "2020_qa.json").exists()
            return
        b.write_year(*args)
        with rasterio.open(b.band_path(2020)) as src:
            q = src.read()
            assert (q[:, :2, :2] == 5).all() and (q[:, :2, 2:] == 30).all()
            assert (q[:, -1, :] == -128).all()
        evidence = b.ov.checked_json(tmp_path / "2020_qa.json")
        assert (
            evidence["valid"],
            evidence["outside"],
            evidence["seam_valid_left_right"],
        ) == (10, 5, [2, 2])
        b.write_year(*args)
        with pytest.raises(ValueError, match="fingerprint"):
            b.write_year(*args[:-1], "different contract")


def test_seven_saved_comparisons_use_pairwise_masks(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "OUT", tmp_path)
    monkeypatch.setattr(b.edge, "OUT", tmp_path)
    monkeypatch.setattr(ch, "DEST", tmp_path / "products")
    monkeypatch.setattr(b, "verify_inputs", lambda: None)
    b.g.write_new(tmp_path / "contract.json", b.RULE)
    pin = b.g.sha256_file(tmp_path / "contract.json")
    for y in b.g.YEARS:
        q = np.ones((64, 3, 4), dtype="int8")
        q[:, 0, 0] = -128
        if y == 2021:
            q[:, 0, 1] = -128
        with rasterio.open(
            b.band_path(y),
            "w",
            driver="GTiff",
            count=64,
            width=4,
            height=3,
            crs="EPSG:4326",
            transform=from_origin(106, -6, 0.01, 0.01),
            dtype="int8",
            nodata=-128,
        ) as ds:
            ds.write(q)
            ds.descriptions = b.g.BANDS
            ds.update_tags(contract_sha256=pin)
        b.g.write_new(
            tmp_path / f"{y}_qa.json",
            dict(
                decision="pass",
                inside=11,
                contract_sha256=pin,
                sha256=b.g.sha256_file(b.band_path(y)),
            ),
        )
    b.g.write_new(
        tmp_path / "comparison.json",
        dict(
            pairs=[
                dict(years=p, points=[dict(rc=[2, 3], cosine_change=0.0)])
                for p in b.edge.PAIRS
            ]
        ),
    )
    ch.main()
    manifest = b.ov.checked_json(ch.DEST / "manifest.json")
    for item in manifest["comparisons"]:
        a, z = item["years"]
        assert item["joint_valid"] == (10 if 2021 in (a, z) else 11)
        with rasterio.open(ch.DEST / f"cosine_{a}_{z}.tif") as src:
            assert src.read(1, masked=True).max() == pytest.approx(0.0, abs=1e-7)
    with pytest.raises(FileExistsError):
        ch.main()
