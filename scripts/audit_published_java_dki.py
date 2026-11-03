"""Count screened source points in official mainland Jakarta municipal polygons."""

import json
from pathlib import Path
import geopandas as gp
import numpy as np
import pandas as pd
import shapely
from scripts.audit_published_java import RAW, AUDIT, ROI, screen_locations
from scripts.prepare_alphaearth_annual_change import sha256_file
from scripts.alphaearth_gcs_pilot import write_new

BOUND = Path("data/output/v9_qc/dki_kelurahan_official.geojson")


def main():
    out = AUDIT.with_name("mainland_counts.json")
    if out.exists():
        raise FileExistsError(out)
    audit = json.loads(AUDIT.read_text(encoding="utf8"))
    if (
        sha256_file(RAW) != audit["sha256"]
        or sha256_file(BOUND)
        != "7bb4dd0589cec8bd64e8930c94b1835116701b6148f7b7de183e61196593c540"
    ):
        raise ValueError("Source/boundary checksum mismatch")
    rows = []
    for chunk in pd.read_csv(RAW, chunksize=200000, float_precision="round_trip"):
        rows.append(
            chunk.loc[
                chunk.Longitude.between(ROI[0], ROI[2])
                & chunk.Latitude.between(ROI[1], ROI[3])
            ]
        )
    pts, _ = screen_locations(pd.concat(rows))
    if len(pts) != audit["eligible_unique_vertical_locations"]:
        raise ValueError("Source count mismatch")
    boundary = gp.read_file(BOUND).to_crs(4326)
    x, y = pts.Longitude.to_numpy(), pts.Latitude.to_numpy()
    memberships = np.zeros(len(pts), dtype=int)
    stats = {}
    for city, group in boundary.groupby("wadmkk"):
        if not city.startswith("JAKARTA "):
            continue
        geom = shapely.union_all(shapely.make_valid(group.geometry.to_numpy()))
        inside = shapely.intersects_xy(geom, x, y)
        memberships += inside
        stats[city] = int(inside.sum())
    if len(stats) != 5:
        raise ValueError("Expected five mainland municipalities")
    result = dict(
        audit_sha256=sha256_file(AUDIT),
        boundary_sha256=sha256_file(BOUND),
        by_city=stats,
        mainland_union_locations=int((memberships > 0).sum()),
        multiple_city_memberships=int((memberships > 1).sum()),
        note="Point support, not a measured land-area fraction. No inferred values in gaps.",
    )
    write_new(out, result)
    print(result)


if __name__ == "__main__":
    main()
