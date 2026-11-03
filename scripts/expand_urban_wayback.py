"""Metadata-only extension of the frozen Jakarta benchmark; preserve v1 evidence."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
from scripts import audit_urban_reference as wb
from scripts import urban_change_benchmark as b
from scripts.check_urban_benchmark_support import ASSIGNMENT, ceiling

OUT = b.OUT.parent / "urban_wayback_extension_v2"
PINS = {
    "protocol.json": wb.PIN,
    "assignment.json": ASSIGNMENT,
    "reference_availability.json": "380b30a82390a7f5dc78fe65c6524b0e9bbb6def00d1b6e875ec4a15e4a65ff8",
    "support_gate.json": "0d56e1833b6133d8e2433549e74dec01c50002933403b46fd03d6379fa9f2140",
}
CUTOFF = "2026-11-03"


def read(path):
    return json.loads(path.read_text(encoding="utf8"))


def schedule(config, old):
    prior = {r["release"] for r in old["snapshots"]}
    seen = set()
    jobs = []
    for key, item in config.items():
        day = date.fromisoformat(item["itemTitle"][-11:-1])
        if day.isoformat() > CUTOFF or day.year < 2020:
            continue
        if key in prior:
            seen.add(key)
        years = [
            y
            for y in (2020, 2025)
            if day.year >= y and not (key in prior and day >= date(y, 7, 1))
        ]
        if years:
            jobs.append(
                dict(
                    key=key,
                    day=day.isoformat(),
                    url=item["metadataLayerUrl"],
                    years=years,
                )
            )
    if prior != seen:
        raise ValueError("Catalogue missing v1 releases")
    return sorted(jobs, key=lambda j: (j["day"], j["key"]))


def register(old):
    cfg = wb.get(wb.CONFIG)
    return dict(
        schema="urban_wayback_extension_v2",
        cutoff=CUTOFF,
        pins=PINS,
        rules="Keep all 300 sites, splits, capture years, v1 candidate function and gates. Retain every v1 hit. For every initially missing site/year search every remaining applicable release; include early endpoint-year releases omitted in v1. Select earliest new qualifying release by date then ID. Archive errors/truncations never count as missing imagery. No visual labels or predictors.",
        releases=schedule(cfg, old),
    )


def inspect(job, sites, base, token):
    path = OUT / "releases" / (job["key"] + ".json")
    if path.exists():
        result = read(path)
        if result["protocol_sha256"] != token or result["job"] != job:
            raise ValueError("Checkpoint drift")
        return result
    need = sorted(
        [s for s in sites if any(str(y) not in base[s["id"]] for y in job["years"])],
        key=lambda s: (round(s["lon"], 1), s["lat"]),
    )
    url = job["url"] + "/" + str(wb.find_layer(job["url"])) + "/query"
    # A complete distinct-date query on the entire bounding box can rule a year
    # OUT, never qualify a site. Inconclusive/truncated prefilter -> full checks.
    params = dict(
        f="geojson",
        geometry=",".join(map(str, b.ROI)),
        inSR=4326,
        geometryType="esriGeometryEnvelope",
        spatialRel="esriSpatialRelIntersects",
        where="1=1",
        outFields="SRC_DATE",
        returnGeometry="false",
        returnDistinctValues="true",
    )
    try:
        dates = wb.get(url, params)
        available = (
            None
            if dates.get("exceededTransferLimit")
            else {str(f["properties"]["SRC_DATE"])[:4] for f in dates["features"]}
        )
    except (ValueError, KeyError, wb.requests.RequestException):
        available = None
    years = [str(y) for y in job["years"] if available is None or str(y) in available]
    need = [s for s in need if any(y not in base[s["id"]] for y in years)]
    hits = {}
    for i in range(0, len(need), 10):
        for s, fs in wb.query_batch(url, need[i : i + 10]):
            for y in years:
                if y in base[s["id"]]:
                    continue
                m = wb.candidate(s, fs, int(y))
                if m:
                    hits.setdefault(s["id"], {})[y] = dict(
                        **m,
                        release=job["key"],
                        release_date=job["day"],
                        metadata_layer=url,
                        viewer=f"https://livingatlas.arcgis.com/wayback/#active={job['key']}&mapCenter={s['lon']:.7f}%2C{s['lat']:.7f}%2C19",
                    )
    result = dict(
        protocol_sha256=token,
        job=job,
        inspected_sites=len(need),
        bbox_ruled_out=[y for y in job["years"] if str(y) not in years],
        hits=hits,
    )
    b.write_new(path, result)
    print(job["day"], len(need), len(hits), flush=True)
    return result


def combine(sites, base, results):
    found = {k: dict(v) for k, v in base.items()}
    for r in sorted(results, key=lambda r: (r["job"]["day"], r["job"]["key"])):
        for sid, vals in r["hits"].items():
            for y, v in vals.items():
                found[sid].setdefault(y, v)
    return found, ceiling(sites, found)


def verify_result(rule, token, old, sites, output):
    """Reconcile saved evidence; absence of a completed release is never a negative."""
    keys = {j["key"] for j in rule["releases"]}
    if output["protocol_sha256"] != token or set(output["checkpoints"]) != keys:
        raise ValueError("Incomplete release evidence")
    results = []
    for j in rule["releases"]:
        p = OUT / "releases" / (j["key"] + ".json")
        if b.sha256_file(p) != output["checkpoints"][j["key"]]:
            raise ValueError("Release checksum mismatch")
        r = read(p)
        if r["job"] != j or r["protocol_sha256"] != token:
            raise ValueError("Wrong release job")
        results.append(r)
    found, c = combine(sites, old["sites"], results)
    if found != output["sites"] or c != output["counts"]:
        raise ValueError("Summary mismatch")
    return dict(
        completed_jobs=len(results),
        unique_releases=len(keys | {r["release"] for r in old["snapshots"]}),
        additional_endpoints=sum(
            len(v) - len(old["sites"][s]) for s, v in found.items()
        ),
        additional_pairs=sum(
            len(v) == 2 and len(old["sites"][s]) != 2 for s, v in found.items()
        ),
        counts=c,
        confirmed_labels=0,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=["register", "audit", "verify"])
    stage = p.parse_args().stage
    for name, h in PINS.items():
        if b.sha256_file(b.OUT / name) != h:
            raise ValueError("Frozen evidence mismatch: " + name)
    old = read(b.OUT / "reference_availability.json")
    path = OUT / "protocol.json"
    wb.CACHE = OUT / "metadata_cache"
    if stage == "register":
        rule = register(old)
        b.write_new(path, rule)
        print("Frozen release jobs:", len(rule["releases"]))
        return
    rule = read(path)
    token = b.sha256_file(path)
    if token != "191600a505893cf5dd15c15a27ac50c9aa925081c3ad4501f1e6dfc130dc7edd":
        raise ValueError("Frozen extension changed")
    dest = OUT / "reference_availability.json"
    sites = read(b.OUT / "assignment.json")["sites"]
    if stage == "verify":
        print(json.dumps(verify_result(rule, token, old, sites, read(dest)), indent=2))
        return
    if dest.exists():
        raise FileExistsError(dest)
    base = old["sites"]
    with ThreadPoolExecutor(9) as pool:
        results = list(
            pool.map(lambda j: inspect(j, sites, base, token), rule["releases"])
        )
    found, counts = combine(sites, base, results)
    b.write_new(
        dest,
        dict(
            protocol_sha256=token,
            sites=found,
            counts=counts,
            checkpoints={
                j["key"]: b.sha256_file(OUT / "releases" / (j["key"] + ".json"))
                for j in rule["releases"]
            },
            decision="blinded_review_possible_not_scorable"
            if all(v["upper_bound_can_meet_minimum"] for v in counts.values())
            else "insufficient_reference_support_do_not_score",
            confirmed_labels=0,
        ),
    )
    print(counts)


if __name__ == "__main__":
    main()
