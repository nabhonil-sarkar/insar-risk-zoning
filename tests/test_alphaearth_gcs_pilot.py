import io

import numpy as np
import pytest
import rasterio
from affine import Affine

from scripts import alphaearth_gcs_pilot as gcs


def test_decode_masks_before_squaring_and_preserves_sign():
    q = np.full((2, 64), -128, dtype=np.int8)
    q[0] = np.resize(np.array([-127, -1, 0, 1, 127], dtype=np.int8), 64)
    decoded = gcs.dequantize(q)
    assert np.isnan(decoded[1]).all()
    np.testing.assert_allclose(
        decoded[0, :5], np.array([-(127**2), -1, 0, 1, 127**2]) / 127.5**2
    )
    q[1, 0] = 0
    with pytest.raises(ValueError, match="Partial"):
        gcs.dequantize(q)


def test_transport_pins_generation_and_caps_before_io(monkeypatch):
    obj = dict(size="10", name="test.tiff", generation="123")
    requests = []

    def fetch(req, timeout):
        requests.append((req.full_url, req.get_header("Range")))
        resp = io.BytesIO(b"0123456789")
        resp.status, resp.headers = 206, {"Content-Range": "bytes 0-9/10"}
        return resp

    monkeypatch.setattr(gcs, "urlopen", fetch)
    budget = [0]
    with gcs.RangeFile(obj, budget) as f:
        assert f.read(2) == b"01"
        f.seek(-3, 2)
        assert f.read(6) == b"789"
    assert budget == [10] and len(requests) == 1
    assert requests[0][0].endswith("?generation=123")
    assert requests[0][1] == "bytes=0-9"
    with pytest.raises(ValueError, match="limit"):
        gcs.RangeFile(obj, [gcs.BYTE_CAP]).read(1)
    assert len(requests) == 1


def test_rejects_whole_object_response(monkeypatch):
    resp = io.BytesIO(b"not partial")
    resp.status = 200
    monkeypatch.setattr(gcs, "urlopen", lambda *a, **kw: resp)
    with pytest.raises(IOError, match="exact byte range"):
        gcs.RangeFile(dict(size="11", name="test.tiff", generation="1"), [0]).read(10)


def test_artifacts_cannot_replace_existing_results(tmp_path):
    p = tmp_path / "result.json"
    gcs.write_new(p, {"id": 1})
    with pytest.raises(FileExistsError):
        gcs.write_new(p, {"id": 2})
    assert '"id": 1' in p.read_text()


@pytest.mark.parametrize("wrong_axis", [False, True])
def test_end_to_end_south_up_native_vs_north_up_reference(
    tmp_path, monkeypatch, wrong_axis
):
    # A deliberately south-up GeoTIFF, like the real distribution. Rows must
    # be selected from its affine, not as if all sources had north-up rows.
    native = tmp_path / "fixture.tiff"
    ref = tmp_path / "reference.tif"
    q = np.broadcast_to(
        np.arange(1, 33, dtype="int8")[None, :, None], (64, 32, 32)
    ).copy()
    q += np.arange(32, dtype="int8")[None, None, :]
    base = dict(driver="GTiff", width=32, height=32, count=64, crs="EPSG:32748")
    with rasterio.open(
        native,
        "w",
        **base,
        transform=Affine(10, 0, 500000, 0, 10, 9000000),
        dtype="int8",
        nodata=-128,
    ) as d:
        d.write(q)
        d.descriptions = gcs.BANDS
    expected = (q[:, ::-1, :].astype(float) / 127.5) ** 2
    if wrong_axis:
        expected[-1] += 0.001
    with rasterio.open(
        ref,
        "w",
        **base,
        transform=Affine(10, 0, 500000, 0, -10, 9000320),
        dtype="float64",
    ) as d:
        d.write(expected)
        d.descriptions = gcs.BANDS
    payload = native.read_bytes()

    def fetch(req, timeout):
        start, end = map(int, req.get_header("Range")[6:].split("-"))
        resp = io.BytesIO(payload[start : end + 1])
        resp.status = 206
        resp.headers = {"Content-Range": f"bytes {start}-{end}/{len(payload)}"}
        return resp

    monkeypatch.setattr(gcs, "REFERENCE", ref)
    monkeypatch.setattr(gcs, "CENTRES", [(500155, 9000155)])
    monkeypatch.setattr(gcs, "urlopen", fetch)
    tile = dict(
        year=2023,
        object=dict(
            name="fiction/fixture.tiff", generation="1", size=str(len(payload))
        ),
        crs="EPSG:32748",
        native_bounds=[500000, 9000000, 500320, 9000320],
    )
    result = gcs.pilot({"tiles": [tile]})
    assert result["decision"] == (
        "hold_do_not_mix" if wrong_axis else "sample_match_only"
    )
    assert len(result["samples"]) == 9
    assert all(
        item["reference_rc"][0] + item["source_rc"][0] == 31
        for item in result["samples"]
    )
