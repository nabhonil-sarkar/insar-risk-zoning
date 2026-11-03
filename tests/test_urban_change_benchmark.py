from itertools import combinations
import numpy as np
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import box, mapping
from scripts import urban_change_benchmark as b
from scripts.audit_urban_reference import candidate, schedule
from scripts.check_urban_benchmark_support import ceiling


def test_design_is_blind_deterministic_and_buffered():
    with (
        MemoryFile() as f,
        f.open(
            driver="GTiff",
            crs=4326,
            width=2858,
            height=1968,
            count=1,
            dtype="uint8",
            transform=from_origin(106.44982, -6.01, 0.00026949, 0.00026949),
        ) as ref,
    ):
        s = b.design(ref)
        assert s == b.design(ref)
    assert len({v["id"] for v in s}) == 300
    groups = {}
    t = Transformer.from_crs(4326, 32748, always_xy=True)
    for v in s:
        groups.setdefault(v["block"], []).append(v)
        assert box(*b.ROI).covers(box(*v["bounds"]))
    assert len(groups) == 100
    for block, g in groups.items():
        assert len(g) == 3 and len({x["split"] for x in g}) == 1
        coords = np.array([t.transform(v["lon"], v["lat"]) for v in g])
        for a, z in combinations(coords, 2):
            assert np.linalg.norm(a - z) >= 1000
        i, j = map(int, block.split(":"))
        assert (np.abs(coords - [i * 5000 + 2500, j * 5000 + 2500]) <= 2000).all()
    assert sum(v["split"] == "evaluation" for v in s) == 150


def test_capture_not_release_and_entire_patch():
    s = {"bounds": [0, 0, 1, 1]}

    def src(geom=box(-1, -1, 2, 2), day=20200602, sensor="WV03"):
        return dict(
            geometry=mapping(geom),
            properties=dict(
                MinMapLevel=12,
                MaxMapLevel=19,
                SRC_DATE=day,
                SRC_DESC=sensor,
                NICE_DESC="Maxar",
                SRC_RES=0.5,
                OBJECTID=42,
            ),
        )

    assert candidate(s, [src()], 2020)["capture_date"] == "2020-06-02"
    assert not candidate(s, [src()], 2025)
    assert not candidate(s, [src(box(0, 0, 0.9, 1))], 2020)
    assert not candidate(s, [src(), src(day=20200709)], 2020)
    assert not candidate(s, [src(sensor="Sentinel-2")], 2020)


def test_not_enough_sites_or_blocks_to_score():
    sites = [
        dict(
            id=str(i),
            block=str(i // 3),
            split="development" if i < 36 else "evaluation",
        )
        for i in range(72)
    ]
    meta = {v["id"]: {"2020": {}, "2025": {}} for v in sites}
    assert not ceiling(sites, meta)["evaluation"]["upper_bound_can_meet_minimum"]
    for v in sites:
        v["block"] = v["id"]
    del meta["1"]["2025"]
    assert ceiling(sites, meta)["development"]["paired"] == 35
    assert ceiling(sites, meta)["evaluation"]["upper_bound_can_meet_minimum"]


def test_fixed_snapshot_date():
    cfg = {
        str(i): dict(itemTitle=f"World Imagery (Wayback {day})")
        for i, day in enumerate(
            ["2020-06-01", "2020-07-01", "2020-12-21", "2026-10-29", "2026-11-30"]
        )
    }
    assert [x[1] for x in schedule(cfg)] == ["2", "3"]
