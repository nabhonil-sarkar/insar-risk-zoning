"""Continuous embedding dissimilarity on common observed support, not classified urban change."""

from contextlib import ExitStack
from pathlib import Path
import tempfile
import os
import numpy as np
import rasterio
from scripts import build_alphaearth_full_grid as b
from scripts import alphaearth_gcs_pilot as g
from scripts import alphaearth_overview_check as ov
from scripts import alphaearth_six_year_sample as edge

DEST = b.OUT / "cosine_change"
NODATA = -9999.0
CODEBOOK = np.sign(np.arange(-128, 128)) * np.square(np.arange(-128, 128) / 127.5)
CODEBOOK[0] = np.nan


def vectors(q):
    if q.dtype != np.int8 or q.shape[0] != 64:
        raise ValueError("Expected encoded 64-axis raster")
    valid = b.semantic_mask(q.transpose(1, 2, 0))
    # Mask code -128 before any vector operations. Values outside support
    # contribute to neither dot products nor coverage.
    vals = CODEBOOK[q.astype(np.int16) + 128]
    vals[:, ~valid] = 0
    norm = np.sqrt(np.einsum("ijk,ijk->jk", vals, vals))
    np.divide(vals, norm[None], out=vals, where=valid[None])
    return vals, valid


def distance(a, b):
    va, ma = a
    vb, mb = b
    common = ma & mb
    out = np.full(common.shape, NODATA, dtype="float32")
    out[common] = np.clip(1 - np.einsum("ijk,ijk->jk", va, vb)[common], 0, 2)
    return out


def main():
    b.verify_inputs()
    if ov.checked_json(b.OUT / "contract.json") != b.RULE:
        raise ValueError("Annual contract drift")
    pin = g.sha256_file(b.OUT / "contract.json")
    frozen = ov.checked_json(edge.OUT / "comparison.json")["pairs"]
    if DEST.exists():
        raise FileExistsError("Change outputs already exist; refusing overwrite")
    with tempfile.TemporaryDirectory(dir=b.OUT) as workspace:
        tmp = Path(workspace) / "products"
        tmp.mkdir()
        with ExitStack() as stack:
            sources = {}
            fingerprints = {}
            qa_sha256 = {}
            inside_counts = set()
            for year in g.YEARS:
                qa_path = b.OUT / f"{year}_qa.json"
                qa = ov.checked_json(qa_path)
                path = b.band_path(year)
                if (
                    qa["decision"] != "pass"
                    or qa["contract_sha256"] != pin
                    or qa["sha256"] != g.sha256_file(path)
                ):
                    raise ValueError("Annual input not verified")
                src = stack.enter_context(rasterio.open(path))
                if (
                    src.tags().get("contract_sha256") != pin
                    or src.descriptions != g.BANDS
                    or src.nodata != -128
                ):
                    raise ValueError("Invalid annual tags")
                if sources:
                    first = next(iter(sources.values()))
                    if (src.transform, src.shape, src.crs) != (
                        first.transform,
                        first.shape,
                        first.crs,
                    ):
                        raise ValueError("Grid mismatch")
                sources[year] = src
                fingerprints[year] = qa["sha256"]
                qa_sha256[year] = g.sha256_file(qa_path)
                inside_counts.add(qa["inside"])
            if len(inside_counts) != 1:
                raise ValueError("Inconsistent study boundary")
            profile = dict(
                src.profile, count=1, dtype="float32", nodata=NODATA, interleave="band"
            )
            outputs = {}
            for pair in edge.PAIRS:
                name = f"cosine_{pair[0]}_{pair[1]}"
                ds = stack.enter_context(
                    rasterio.open(tmp / (name + ".tif"), "w", **profile)
                )
                ds.set_band_description(1, name)
                ds.update_tags(
                    metric="1 - cosine similarity of decoded A00..A63",
                    meaning="embedding dissimilarity; no cause or class inferred",
                    attribution=b.ATTR,
                    contract_sha256=pin,
                )
                outputs[pair] = ds
            counts = {p: 0 for p in outputs}
            for _, win in src.block_windows(1):
                annual = {y: vectors(ds.read(window=win)) for y, ds in sources.items()}
                for (a, z), dest in outputs.items():
                    d = distance(annual[a], annual[z])
                    counts[a, z] += int((d != NODATA).sum())
                    dest.write(d, 1, window=win)
        evidence = []
        for sample in frozen:
            a, z = sample["years"]
            path = tmp / f"cosine_{a}_{z}.tif"
            with rasterio.open(path) as ds:
                for pt in sample["points"]:
                    r, c = pt["rc"]
                    val = ds.read(1, window=((r, r + 1), (c, c + 1))).item()
                    if abs(val - pt["cosine_change"]) > 1e-7:
                        raise ValueError("Frozen cosine mismatch")
                data = ds.read(1, masked=True).compressed()
                if (
                    len(data) != counts[a, z]
                    or not len(data)
                    or not np.isfinite(data).all()
                    or data.min() < 0
                    or data.max() > 2
                ):
                    raise ValueError("Support or range mismatch")
                evidence.append(
                    dict(
                        years=[a, z],
                        joint_valid=len(data),
                        total_cells=ds.width * ds.height,
                        frozen_checks=len(sample["points"]),
                        min=float(data.min()),
                        max=float(data.max()),
                        median=float(np.median(data)),
                        sha256=g.sha256_file(path),
                    )
                )
        g.write_new(
            tmp / "manifest.json",
            dict(
                annual_contract_sha256=pin,
                annual_sha256=fingerprints,
                annual_qa_sha256=qa_sha256,
                inside_roi_centres=inside_counts.pop(),
                interpretation="Observed embedding dissimilarity only; not urban development, displacement or risk.",
                comparisons=evidence,
            ),
        )
        os.rename(tmp, DEST)
    print("Verified seven continuous comparison rasters", flush=True)


if __name__ == "__main__":
    main()
