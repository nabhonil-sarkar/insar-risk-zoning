"""Inventory without distance statistics; register; run only with exact approval."""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import Affine

from scripts import alphaearth_surface_type as stats
from scripts.run_alphaearth_tile_seam import checked_json, snapshot, sample_cover

ROOT = Path(__file__).resolve().parents[1]
DATA = Path("data/output/alphaearth_annual_change")
FULL = DATA / "gcs_full_v1"
MAPS = FULL / "cosine_change"
DEST = Path("data/output/alphaearth_surface_type_v1")
GRID = DATA / "alphaearth_annual_change_contract.json"
WC_SHA = "e57aa50ed914ca8ce646797e0b430c1a4c723e51028b77c6312a1fc7810bcc4e"
MANIFEST_SHA = "6f5a56846626ec2c058472ce4ee8707172c245da6642027f645591668fea3fbb"
PINS = {
    GRID.as_posix(): "a43b2fff3dd8dbfdfe55f3c79be1add90e17360a2918893e43f4e8a25ec74c63",
    (DATA / "gcs_v1_inventory.json").as_posix(): "be02701d9a3c539653f5d395fc1a5a659340217b56986e4df8ccd500f2c0e63e",
    (FULL / "contract.json").as_posix(): "0fac38294b4b2e8ebd1ef2189df0898b4b79ef07ae7b8dcac21aa3e673829862",
}
PROTOCOL_SHA256 = "34f69075b89b76897ab5405d9d98f9cad14a81c68eef0fc53a5535028a06aaa0"
EXPECTED_PAIRS = {*stats.YEARS, (2020, 2023), (2020, 2025)}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_new(path, obj):
    raw = (json.dumps(obj, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with Path(path).open("xb") as stream:
        stream.write(raw)
    return hashlib.sha256(raw).hexdigest()


def header(ds):
    return dict(shape=list(ds.shape), crs=str(ds.crs), transform=list(ds.transform)[:6],
                count=ds.count, dtypes=list(ds.dtypes), nodata=ds.nodata,
                descriptions=list(ds.descriptions), bounds=list(ds.bounds))


def preflight(root, worldcover, stage):
    """Hash ALL required inputs before any GDAL open; checked map snapshots."""
    metadata = {p: checked_json(root / p, sha) for p, sha in PINS.items()}
    manifest = checked_json(root / MAPS / "manifest.json", MANIFEST_SHA)
    contract_sha = PINS[(FULL / "contract.json").as_posix()]
    pairs = [tuple(r["years"]) for r in manifest["comparisons"]]
    if (len(pairs) != 7 or set(pairs) != EXPECTED_PAIRS
            or manifest["annual_contract_sha256"] != contract_sha
            or set(manifest["annual_sha256"]) != {str(y) for y in range(2020, 2026)}
            or set(manifest["annual_qa_sha256"]) != {str(y) for y in range(2020, 2026)}):
        raise ValueError("Wrong change manifest contract or comparisons")
    hashes = dict(PINS)
    hashes[(MAPS / "manifest.json").as_posix()] = MANIFEST_SHA
    annual_paths = []
    for year in range(2020, 2026):
        rel = FULL / f"Jakarta_GCS20m_on30m_{year}_qint8.tif"
        expected = manifest["annual_sha256"][str(year)]
        if digest(root / rel) != expected:
            raise ValueError(f"SHA-256 mismatch: annual {year}")
        qa_rel = FULL / f"{year}_qa.json"
        qa = checked_json(root / qa_rel, manifest["annual_qa_sha256"][str(year)])
        if (qa["decision"] != "pass" or qa["year"] != year or qa["sha256"] != expected
                or qa["contract_sha256"] != contract_sha
                or qa["inside"] != manifest["inside_roi_centres"]
                or qa["valid"] != qa["inside"] or qa["missing_inside"] != 0):
            raise ValueError("Annual QA contract mismatch")
        hashes[rel.as_posix()] = expected
        hashes[qa_rel.as_posix()] = manifest["annual_qa_sha256"][str(year)]
        annual_paths.append(root / rel)
    snapshot(worldcover, stage / "worldcover.tif", WC_SHA)
    for entry in manifest["comparisons"]:
        a, b = entry["years"]
        name = f"cosine_{a}_{b}.tif"
        snapshot(root / MAPS / name, stage / name, entry["sha256"])
        hashes[(MAPS / name).as_posix()] = entry["sha256"]
    grid = metadata[GRID.as_posix()]["frozen_reference_grid"]
    roi = metadata[(FULL / "contract.json").as_posix()]["roi"]
    return grid, roi, manifest, hashes, annual_paths


def geometry(grid, roi):
    t = Affine(*grid["transform"])
    h, w = grid["height"], grid["width"]
    if (grid["crs"] != "EPSG:4326" or t.b or t.d or not (t.a > 0 > t.e)
            or len(roi) != 4 or not np.isfinite(roi).all()):
        raise ValueError("Invalid analysis geometry")
    lon = t.c + (np.arange(w) + 0.5) * t.a
    lat = t.f + (np.arange(h) + 0.5) * t.e
    west, south, east, north = roi
    if not (west < east and south < north):
        raise ValueError("Invalid ROI bounds")
    inside = ((lon >= west) & (lon <= east))[None, :] & ((lat >= south) & (lat <= north))[:, None]
    x, y = Transformer.from_crs(4326, 32748, always_xy=True).transform(*np.meshgrid(lon, lat))
    size = stats.RULE["sparse"]["block_size_m"]
    pairs = np.column_stack((np.floor(x.ravel()/size), np.floor(y.ravel()/size)))
    _, block_ids = np.unique(pairs, axis=0, return_inverse=True)
    return t, lon, lat, inside, block_ids.reshape(h, w)


def check_grid(ds, grid, count, dtype, nodata):
    if (ds.shape != (grid["height"], grid["width"])
            or ds.transform != Affine(*grid["transform"]) or ds.crs != grid["crs"]
            or ds.count != count or ds.dtypes != (dtype,) * count or ds.nodata != nodata):
        raise ValueError("Raster header/grid mismatch")


def inspect(stage, grid, roi, manifest, annual_paths):
    """Headers, class values and masks only: never read distance bands here."""
    t, lon, lat, inside, blocks = geometry(grid, roi)
    n = int(inside.sum())
    if n != manifest["inside_roi_centres"]:
        raise ValueError("ROI count mismatch")
    headers = {}
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        for path in annual_paths:
            with rasterio.open(path) as ds:
                check_grid(ds, grid, 64, "int8", -128)
                if (ds.descriptions != tuple(f"A{i:02}" for i in range(64))
                        or ds.tags().get("contract_sha256") != manifest["annual_contract_sha256"]):
                    raise ValueError("Annual band/contract mismatch")
                headers[path.name] = header(ds)
        masks = {}
        for entry in manifest["comparisons"]:
            a, b = entry["years"]
            name = f"cosine_{a}_{b}"
            with rasterio.open(stage / (name + ".tif")) as ds:
                check_grid(ds, grid, 1, "float32", -9999)
                if (ds.descriptions != (name,)
                        or ds.tags().get("contract_sha256") != manifest["annual_contract_sha256"]
                        or entry["total_cells"] != inside.size):
                    raise ValueError("Map metadata mismatch")
                mask = ds.read_masks(1) != 0
                if int(mask.sum()) != entry["joint_valid"] or not np.array_equal(mask, inside):
                    raise ValueError("Registered map mask/support mismatch")
                headers[name + ".tif"] = header(ds)
                if (a, b) in stats.YEARS:
                    masks[a, b] = mask
        with rasterio.open(stage / "worldcover.tif") as wc:
            if wc.dtypes != ("uint8",) or wc.nodata != 0:
                raise ValueError("Unexpected WorldCover encoding")
            cover = sample_cover(wc, lon, lat)
            wc_header = header(wc)
    valid = np.stack([masks[p] for p in stats.YEARS])
    support = stats.support_rows(cover, inside, valid, blocks)
    edges = {"rows": [int(v[0]) for v in np.array_split(np.arange(inside.shape[0]), 3)] + [inside.shape[0]],
             "columns": [int(v[0]) for v in np.array_split(np.arange(inside.shape[1]), 3)] + [inside.shape[1]]}
    census = dict(grid=grid, roi=roi, inside_roi_centres=n, exterior_centres=int(inside.size-n),
                  sector_edges_exclusive=edges, headers=headers, worldcover_header=wc_header,
                  support=support, joint_valid_count=int(valid.all(axis=0).sum()),
                  support_loss_count=int((inside & ~valid.all(axis=0)).sum()))
    return census, cover, inside, blocks


def inventory(worldcover):
    out = ROOT / DEST
    out.mkdir(parents=True, exist_ok=True)
    target = out / "inventory.json"
    if target.exists():
        raise FileExistsError(target)
    with tempfile.TemporaryDirectory(dir=out) as folder:
        stage = Path(folder)
        grid, roi, manifest, hashes, annual = preflight(ROOT, worldcover, stage)
        census, _, _, _ = inspect(stage, grid, roi, manifest, annual)
        census.update(schema="jakarta_surface_type_inventory_v1", date="2026-11-05 Asia/Singapore",
                      scope="Input hashes, headers, masks and baseline class/sector support only; no distance distributions or contrasts computed.",
                      input_sha256=hashes, worldcover_sha256=WC_SHA,
                      worldcover_path=str(worldcover.resolve()),
                      worldcover_source="https://esa-worldcover.s3.eu-central-1.amazonaws.com/v100/2020/map/ESA_WorldCover_10m_2020_v100_S09E105_Map.tif",
                      source_trace="Exact tile path recovered from completed seam-run invocation and report land-check input; SHA-256 matches completed seam results.",
                      code_commit_at_inventory=subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
                      inventory_code_state="Working-tree preparation; not an approved real analysis execution.")
        tmp = stage / "inventory.json"
        write_new(tmp, census)
        os.link(tmp, target)
    return target


def register():
    path = ROOT / DEST / "inventory.json"
    census = json.loads(path.read_bytes())
    if census["input_sha256"].get((MAPS / "manifest.json").as_posix()) != MANIFEST_SHA or census["worldcover_sha256"] != WC_SHA:
        raise ValueError("Unexpected inventory provenance")
    protocol = dict(schema="jakarta_surface_type_v1", proposed="2026-11-05 Asia/Singapore",
                    authorization="Pending owner approval of these exact bytes. Approval is recorded separately; never edit this file. Changes require a new version/hash.",
                    rules=stats.RULE, inventory_sha256=digest(path),
                    input_sha256=census["input_sha256"], worldcover_sha256=WC_SHA,
                    worldcover_reference="https://esa-worldcover.org/en/data-access",
                    worldcover_legend_reference="https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v100",
                    geometry={k: census[k] for k in ("grid", "roi", "sector_edges_exclusive")})
    return write_new(ROOT / DEST / "protocol.json", protocol)


def revision(root):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
    if git("status", "--porcelain"):
        raise ValueError("Real analysis requires a clean committed working tree")
    git("ls-files", "--error-unmatch", "scripts/alphaearth_surface_type.py", "scripts/run_alphaearth_surface_type.py",
        "scripts/run_alphaearth_tile_seam.py", "tests/test_alphaearth_surface_type.py", "tests/test_run_alphaearth_surface_type.py")
    return git("rev-parse", "HEAD")


def csv_write(path, rows):
    flat = [{k: json.dumps(v, allow_nan=False) if isinstance(v, (dict, list)) else v
             for k, v in row.items()} for row in rows]
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flat[0]))
        writer.writeheader()
        writer.writerows(flat)


def deliver(result, folder):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    for key in ("support", "transitions", "contrasts"):
        csv_write(folder / f"{key}.csv", result[key])
    fig, axes = plt.subplots(3, 4, figsize=(13, 9), layout="constrained")
    for ax, (code, label) in zip(axes.flat, stats.CLASSES.items()):
        rows = [r for r in result["transitions"] if r["class_code"] == code and r["sector"] == "ALL"]
        med = np.array([r["median"] if r["median"] is not None else np.nan for r in rows])
        low = np.array([r["q25"] if r["q25"] is not None else np.nan for r in rows])
        high = np.array([r["q75"] if r["q75"] is not None else np.nan for r in rows])
        ax.plot(range(5), med, "o-")
        ax.fill_between(range(5), low, high, alpha=.2)
        ax.set_xticks(range(5), ["20-21", "21-22", "22-23", "23-24", "24-25"], rotation=45)
        ax.set_title(f"{code} {label}\n{rows[0]['status']}; n={rows[0]['joint_count']:,}", fontsize=9)
        ax.set_ylabel("Cosine distance")
        if rows[0]["status"] == "empty":
            ax.text(.5, .5, "No joint support", ha="center", va="center", transform=ax.transAxes)
            ax.set_yticks([])
    axes.flat[-1].axis("off")
    fig.suptitle("2020 baseline classes: medians and IQRs on fixed joint support\nAncillary classes do not establish unchanged surfaces; panel scales differ")
    fig.savefig(folder / "class_transitions.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(14, 11), layout="constrained")
    matrices, annotations = [], []
    for pair in (stats.YEARS[i] for i in (0, 1, 3, 4)):
        matrix = np.full((11, 9), np.nan)
        labels = np.full((11, 9), "", dtype="U12")
        for i, code in enumerate(stats.CLASSES):
            for j, sector in enumerate(stats.SECTORS):
                row = next(r for r in result["contrasts"] if r["class_code"] == code and r["sector"] == sector and tuple(r["comparator"]) == pair)
                val = row["paired_quantiles"]["median"]
                if val is not None:
                    matrix[i, j] = val
                    labels[i, j] = "S" if row["status"] == "sparse" else ""
                else:
                    labels[i, j] = "empty"
        matrices.append(matrix)
        annotations.append((pair, labels))
    finite = np.concatenate([m[np.isfinite(m)] for m in matrices])
    limit = max(float(np.abs(finite).max()) if finite.size else 0, 1e-12)
    for ax, matrix, (pair, labels) in zip(axes.flat, matrices, annotations):
        im = ax.imshow(matrix, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")
        ax.set_xticks(range(9), stats.SECTORS)
        ax.set_yticks(range(11), [f"{k} {v}" for k, v in stats.CLASSES.items()], fontsize=8)
        ax.set_title(f"2022-2023 minus {pair[0]}-{pair[1]}")
        for (i, j), label in np.ndenumerate(labels):
            if label:
                ax.text(j, i, label, ha="center", va="center", fontsize=6,
                        bbox=dict(facecolor="white", edgecolor="none", alpha=.8, pad=.3))
    fig.colorbar(im, ax=list(axes.flat), label="Median cell-paired cosine-distance difference (shared uncapped scale)", shrink=.65)
    fig.suptitle("Within-sector contrasts by 2020 baseline class\nS = sparse descriptive row; empty = no joint support; no causal attribution")
    fig.savefig(folder / "sector_contrasts.png", dpi=150)
    plt.close(fig)
    summary = ["Baseline surface diagnostic; descriptive, not physical attribution.",
               "Aggregate findings were known before this prospective follow-up.",
               "Inspect within-sector contrasts before pooled class differences.",
               "Positive/negative below refers to paired median contrast, not significance."]
    for code, label in stats.CLASSES.items():
        for pair in (stats.YEARS[i] for i in (0, 1, 3, 4)):
            rows = [r for r in result["contrasts"] if r["class_code"] == code and r["sector"] != "ALL" and tuple(r["comparator"]) == pair]
            supported = [r for r in rows if r["status"] == "supported"]
            signs = {s: [r["sector"] for r in supported if np.sign(r["paired_quantiles"]["median"]) == v]
                     for s, v in (("positive", 1), ("zero", 0), ("negative", -1))}
            summary.append(f"{code} {label}, target minus {pair}: supported={len(supported)}/9; signs={signs}; sparse={[r['sector'] for r in rows if r['status']=='sparse']}; empty={[r['sector'] for r in rows if r['status']=='empty']}")
    summary.extend(stats.RULE["interpretation"])
    (folder / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")


def run(worldcover, approved_protocol_sha256):
    if approved_protocol_sha256 != PROTOCOL_SHA256 or PROTOCOL_SHA256 == "PENDING_REGISTRATION":
        raise ValueError("Explicit approval of pinned protocol is required")
    protocol = checked_json(ROOT / DEST / "protocol.json", PROTOCOL_SHA256)
    if protocol["rules"] != stats.RULE:
        raise ValueError("Protocol and implementation rules differ")
    census = checked_json(ROOT / DEST / "inventory.json", protocol["inventory_sha256"])
    commit = revision(ROOT)
    target = ROOT / DEST / "run"
    if target.exists():
        raise FileExistsError(target)
    with tempfile.TemporaryDirectory(dir=target.parent) as folder:
        stage = Path(folder)
        grid, roi, manifest, hashes, annual = preflight(ROOT, worldcover, stage)
        if hashes != protocol["input_sha256"] or WC_SHA != protocol["worldcover_sha256"]:
            raise ValueError("Protocol input pins differ")
        current, cover, inside, blocks = inspect(stage, grid, roi, manifest, annual)
        if any(current[k] != census[k] for k in current):
            raise ValueError("Inventory geometry or support changed")
        distances = []
        for a, b in stats.YEARS:
            with rasterio.open(stage / f"cosine_{a}_{b}.tif") as ds:
                d = ds.read(1, masked=True)
            if not np.isfinite(d.compressed()).all():
                raise ValueError("Nonfinite unmasked distance")
            distances.append(d)
        result = stats.analyse(np.ma.stack(distances), cover, inside, blocks)
        if result["support"] != census["support"]:
            raise ValueError("Distance validity differs from registered mask support")
        result["provenance"] = dict(code_commit=commit, protocol_sha256=PROTOCOL_SHA256,
                                     inventory_sha256=protocol["inventory_sha256"],
                                     input_sha256=hashes, worldcover_sha256=WC_SHA,
                                     python=platform.python_version(), numpy=np.__version__, rasterio=rasterio.__version__)
        product = stage / "run"
        product.mkdir()
        deliver(result, product)
        result["output_sha256"] = {p.name: digest(p) for p in sorted(product.iterdir())}
        write_new(product / "results.json", result)
        if revision(ROOT) != commit:
            raise ValueError("Code revision changed during run")
        # Windows rename refuses an existing destination. On POSIX an existing
        # nonempty run directory also cannot be replaced; reserve under lock.
        lock = target.parent / "run.lock"
        with lock.open("x"):
            if target.exists():
                raise FileExistsError(target)
            os.rename(product, target)
        lock.unlink()
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inventory", "register", "run"))
    parser.add_argument("--worldcover", type=Path)
    parser.add_argument("--approved-protocol-sha256")
    args = parser.parse_args()
    if args.action in ("inventory", "run") and args.worldcover is None:
        parser.error("--worldcover required")
    print(inventory(args.worldcover) if args.action == "inventory" else register()
          if args.action == "register" else run(args.worldcover, args.approved_protocol_sha256))
