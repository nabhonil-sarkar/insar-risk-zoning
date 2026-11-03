"""Catalogue scout only: no imagery access, commercial orders, labels or gate changes."""

import argparse
from datetime import datetime, timezone
from shapely.geometry import shape, box
from shapely import make_valid
from scripts import expand_urban_wayback as ext
from scripts import audit_urban_reference as wb
from scripts import urban_change_benchmark as b

OUT = b.OUT.parent / "pleiades_catalogue_scout"
SERVICE = "https://portal.intelligence-airbusds.com/arcgis/rest/services/OneAtlas/OADConstellationArchive/MapServer/9"
RULE = dict(
    schema="phr_footprints_v1",
    assignment_sha256=ext.ASSIGNMENT,
    service=SERVICE,
    years=[2020, 2025],
    roi=b.ROI,
    rule="Check all assigned patches identically. One dated Pléiades All Segments footprint must cover the entire patch. Keep all candidate IDs; no cloud screening by scene average. No image, licence, clarity, registration or source-resolution verification. Geometric upper bound ONLY, never insert into the Wayback support gate.",
)


def get_year(y):
    where = f"acquisitiondate >= DATE '{y}-01-01' AND acquisitiondate < DATE '{y + 1}-01-01'"
    common = dict(
        where=where,
        geometry=",".join(map(str, b.ROI)),
        geometryType="esriGeometryEnvelope",
        inSR=4326,
        spatialRel="esriSpatialRelIntersects",
    )
    url = SERVICE + "/query"
    ids = sorted(wb.get(url, dict(common, f="json", returnIdsOnly="true"))["objectIds"])
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate catalogue IDs")
    features = []
    for i in range(0, len(ids), 40):
        wanted = ids[i : i + 40]
        part = wb.get(
            url,
            dict(
                f="geojson",
                objectIds=",".join(map(str, wanted)),
                where=where,
                outSR=4326,
                returnGeometry="true",
                outFields="objectid,parentidentifier,acquisitiondate,cloudcover",
            ),
        )
        rows = part["features"]
        if (
            part.get("exceededTransferLimit")
            or sorted(r["properties"]["objectid"] for r in rows) != wanted
        ):
            raise ValueError("Incomplete footprint query")
        for row in rows:
            p = row["properties"]
            d = p["acquisitiondate"]
            day = (
                datetime.fromtimestamp(d / 1000, tz=timezone.utc)
                if isinstance(d, (int, float))
                else datetime.fromisoformat(d.replace("Z", "+00:00"))
            )
            if day.year != y:
                raise ValueError("Wrong acquisition year")
        features.extend(rows)
    return features


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=["register", "audit"])
    stage = p.parse_args().stage
    if b.sha256_file(b.OUT / "assignment.json") != ext.ASSIGNMENT:
        raise ValueError("Assignment drift")
    path = OUT / "rule.json"
    if stage == "register":
        b.write_new(path, RULE)
        return
    if ext.read(path) != RULE:
        raise ValueError("Scout rules changed")
    dest = OUT / "footprint_scout.json"
    if dest.exists():
        raise FileExistsError(dest)
    wb.CACHE = OUT / "catalogue_cache"
    sites = ext.read(b.OUT / "assignment.json")["sites"]
    inventory = {}
    bysite = {s["id"]: {} for s in sites}
    for year in RULE["years"]:
        features = get_year(year)
        geoms = [
            (r["properties"]["objectid"], make_valid(shape(r["geometry"])))
            for r in features
        ]
        inventory[str(year)] = [r["properties"] for r in features]
        for s in sites:
            patch = box(*s["bounds"])
            bysite[s["id"]][str(year)] = sorted(
                oid for oid, g in geoms if g.covers(patch)
            )
    split = {}
    for group in ["development", "evaluation"]:
        covered = [
            s for s in sites if s["split"] == group and all(bysite[s["id"]].values())
        ]
        split[group] = dict(
            patches=len(covered), blocks=len({s["block"] for s in covered})
        )
    b.write_new(
        dest,
        dict(
            rule_sha256=b.sha256_file(path),
            source=SERVICE,
            segments=inventory,
            whole_patch_catalogue_ids=bysite,
            geometric_pairs=split,
            access="Metadata only. No order, purchased imagery, verified view rights or confirmed labels.",
        ),
    )
    print({y: len(v) for y, v in inventory.items()}, split)


if __name__ == "__main__":
    main()
