import pytest
from scripts import expand_urban_wayback as ext


def item(day):
    return {
        "itemTitle": f"World Imagery (Wayback {day})",
        "metadataLayerUrl": "service",
    }


def test_all_relevant_endpoint_releases_including_previously_unsearched_half():
    cfg = {
        str(i): item(d)
        for i, d in enumerate(
            [
                "2019-12-31",
                "2020-01-05",
                "2020-12-21",
                "2025-02-01",
                "2025-06-26",
                "2025-12-18",
                "2026-11-04",
            ]
        )
    }
    old = {"snapshots": [{"release": k} for k in ["2", "4", "5"]]}
    assert [(j["key"], j["years"]) for j in ext.schedule(cfg, old)] == [
        ("1", [2020]),
        ("3", [2020, 2025]),
        ("4", [2025]),
    ]
    with pytest.raises(ValueError):
        ext.schedule(cfg, {"snapshots": [{"release": "absent"}]})


def test_combine_is_chronological_never_replaces_v1_or_mutates_it():
    s = [dict(id="a", split="development", block="x")]
    base = {"a": {"2020": {"release": "v1"}}}
    rows = [
        dict(
            job=dict(day=d, key=k),
            hits={"a": {"2020": {"release": k}, "2025": {"release": k}}},
        )
        for d, k in [("2026-05-01", "later"), ("2025-12-01", "first")]
    ]
    merged, counts = ext.combine(s, base, rows)
    assert merged == {"a": {"2020": {"release": "v1"}, "2025": {"release": "first"}}}
    assert "2025" not in base["a"] and counts["development"]["paired_blocks"] == 1


@pytest.mark.parametrize("truncated", [True, False])
def test_bbox_can_only_rule_out_not_qualify(tmp_path, monkeypatch, truncated):
    monkeypatch.setattr(ext, "OUT", tmp_path)
    monkeypatch.setattr(ext.wb, "find_layer", lambda url: 4)
    monkeypatch.setattr(
        ext.wb,
        "get",
        lambda *args: {
            "exceededTransferLimit": truncated,
            "features": [{"properties": {"SRC_DATE": 20190202}}],
        },
    )
    queried = []

    def patches(url, sites):
        queried.extend(sites)
        return [(s, []) for s in sites]

    monkeypatch.setattr(ext.wb, "query_batch", patches)
    site = dict(id="s", lon=106.8, lat=-6.2, bounds=[0, 0, 1, 1])
    job = dict(key="1", day="2020-12-10", url="test", years=[2020])
    r = ext.inspect(job, [site], {"s": {}}, "token")
    assert bool(queried) == truncated
    assert not r["hits"] and r["bbox_ruled_out"] == ([] if truncated else [2020])


def test_verify_requires_every_checkpoint_and_its_registered_bytes(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(ext, "OUT", tmp_path)
    job = dict(key="42", day="2025-12-01")
    s = [dict(id="a", split="evaluation", block="b")]
    base = {"a": {}}
    p = tmp_path / "releases/42.json"
    r = dict(job=job, protocol_sha256="pin", hits={})
    ext.b.write_new(p, r)
    vals, counts = ext.combine(s, base, [r])
    old = dict(sites=base, snapshots=[dict(release="v1")])
    output = dict(
        protocol_sha256="pin",
        sites=vals,
        counts=counts,
        checkpoints={"42": ext.b.sha256_file(p)},
    )
    assert (
        ext.verify_result({"releases": [job]}, "pin", old, s, output)["unique_releases"]
        == 2
    )
    with pytest.raises(ValueError, match="checksum"):
        ext.verify_result(
            {"releases": [job]},
            "pin",
            old,
            s,
            dict(output, checkpoints={"42": "wrong"}),
        )
    with pytest.raises(ValueError, match="Incomplete"):
        ext.verify_result(
            {"releases": [job]}, "pin", old, s, dict(output, checkpoints={})
        )
