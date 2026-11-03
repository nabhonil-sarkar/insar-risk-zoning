"""Quantify, not assume, agreement with the legacy export; never change GCS masks."""

import numpy as np
import rasterio
from scripts import build_alphaearth_full_grid as b
from scripts import alphaearth_overview_check as ov
from scripts import alphaearth_gcs_pilot as g
from scripts.alphaearth_full_grid_change import CODEBOOK


def main():
    b.verify_inputs()
    path = b.band_path(2023)
    report = ov.checked_json(b.OUT / "2023_qa.json")
    if report["sha256"] != g.sha256_file(path) or report["decision"] != "pass":
        raise ValueError("Unverified annual input")
    n = dict(
        joint_inside=0,
        match_inside=0,
        gcs_only_inside=0,
        legacy_only_inside=0,
        both_missing_inside=0,
        legacy_valid_outside=0,
    )
    peak = 0.0
    with rasterio.open(g.REFERENCE) as ref, rasterio.open(path) as src:
        inside, *_ = b.grid(ref)
        for _, win in src.block_windows(1):
            rr, cc = win.toslices()
            roi = inside[rr, cc]
            old = ref.read(window=win, masked=True).filled(np.nan)
            q = src.read(window=win)
            v0 = np.isfinite(old).all(0) & old.any(0)
            v1 = b.semantic_mask(q.transpose(1, 2, 0))
            joint = v0 & v1 & roi
            n["joint_inside"] += int(joint.sum())
            n["gcs_only_inside"] += int((roi & v1 & ~v0).sum())
            n["legacy_only_inside"] += int((roi & v0 & ~v1).sum())
            n["both_missing_inside"] += int((roi & ~v0 & ~v1).sum())
            n["legacy_valid_outside"] += int((~roi & v0).sum())
            if joint.any():
                delta = np.abs(
                    old[:, joint] - CODEBOOK[q[:, joint].astype("int16") + 128]
                ).max(0)
                n["match_inside"] += int((delta <= 1e-7).sum())
                peak = max(peak, float(delta.max()))
    if n["joint_inside"] + n["gcs_only_inside"] != report["valid"]:
        raise ValueError("Coverage mismatch")
    g.write_new(
        b.OUT / "legacy_2023_diagnostic.json",
        dict(
            **n,
            all_axis_atol=1e-7,
            max_abs_error=peak,
            annual_sha256=report["sha256"],
            reference_sha256=g.EXPECTED_REFERENCE_SHA256,
            interpretation="Delivery-route diagnostic only; no replacement, filtering or inference about physical change.",
        ),
    )
    print(n, peak)


if __name__ == "__main__":
    main()
