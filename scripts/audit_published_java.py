"""Read-only source QA. Counts at printed coordinates, not interpolated coverage."""

import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

RAW = Path("data/raw/published_java_15786357/Java_VLM_EW.csv")
AUDIT = Path("data/output/published_java_15786357/source_audit.json")
FIELDS = [
    "Longitude",
    "Latitude",
    "VLM_cm_per_yr",
    "VLM_sd_cm_per_yr",
    "EW_cm_per_yr",
    "EW_sd_cm_per_yr",
]
ROI = (106.45, -6.54, 107.22, -6.01)
POLICY = "Group by exact reported longitude/latitude; collapse identical records, withhold groups with conflicting values. For vertical context require finite VLM and strictly positive finite VLM SD. No interpolation, averaging duplicates or rate-based selection."


def screen_locations(rows):
    coords = FIELDS[:2]
    unique = rows.drop_duplicates()
    sizes = rows.groupby(coords).size()
    conflict = unique.duplicated(coords, keep=False)
    clean = unique.loc[~conflict]
    ok = (
        np.isfinite(clean[FIELDS[2]])
        & np.isfinite(clean[FIELDS[3]])
        & (clean[FIELDS[3]] > 0)
    )
    eligible = clean.loc[ok]
    return eligible, dict(
        roi_rows=len(rows),
        unique_locations=len(sizes),
        repeated_locations=int((sizes > 1).sum()),
        duplicate_rows_identical=len(rows) - len(unique),
        conflicting_locations=len(unique.loc[conflict, coords].drop_duplicates()),
        withheld_nonpositive_or_missing_sd_or_rate=int((~ok).sum()),
    )


def summarize(rows):
    eligible, counts = screen_locations(rows)
    # Fixed 0.01-degree audit bins over the declared rectangle; not administrative land area.
    xy = eligible[FIELDS[:2]].to_numpy()
    bins = np.floor(np.round((xy - np.array(ROI[:2])) / 0.01, 10)).astype(int)
    bins = np.minimum(bins, [76, 52])  # include east/north limits in final bins
    return dict(
        **counts,
        eligible_unique_vertical_locations=len(eligible),
        occupied_001deg_bins=len(np.unique(bins, axis=0)),
        rectangle_bins=77 * 53,
        sd_cm_per_yr_quartiles=eligible[FIELDS[3]].quantile([0.25, 0.5, 0.75]).tolist(),
    )


def main():
    if AUDIT.exists():
        raise FileExistsError(AUDIT)
    with RAW.open("rb") as f:
        if (
            RAW.stat().st_size != 446891387
            or hashlib.file_digest(f, "md5").hexdigest()
            != "02ef53d4cb962e2c044fbf0d096824df"
        ):
            raise ValueError("Source integrity failed")
        f.seek(0)
        sha = hashlib.file_digest(f, "sha256").hexdigest()
    n = bad = 0
    samples = []
    for chunk in pd.read_csv(RAW, chunksize=200000, float_precision="round_trip"):
        if list(chunk.columns) != FIELDS:
            raise ValueError("Unknown CSV schema")
        n += len(chunk)
        x, y = chunk.Longitude, chunk.Latitude
        bad += int((~(x.between(-180, 180) & y.between(-90, 90))).sum())
        samples.append(
            chunk.loc[x.between(ROI[0], ROI[2]) & y.between(ROI[1], ROI[3])].copy()
        )
    result = dict(
        source_doi="10.5281/zenodo.15786357",
        sha256=sha,
        source_rows=n,
        invalid_coordinate_rows=bad,
        roi=ROI,
        policy=POLICY,
        period="2017–2023",
        vertical_frame="IGS14",
        ew_frame="local",
        units="cm/year",
        interpretation="Data availability only; no independent validation or risk map",
        **summarize(pd.concat(samples, ignore_index=True)),
    )
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT.open("x", encoding="utf8") as f:
        json.dump(result, f, indent=2, allow_nan=False)
    print(result)


if __name__ == "__main__":
    main()
