"""Single diagnostic view of the verified 2020–2025 continuous embedding distance."""

import os
from pathlib import Path
import tempfile
import geopandas as gp
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
import rasterio
from scripts import alphaearth_full_grid_change as change
from scripts import alphaearth_gcs_pilot as g
from scripts import alphaearth_overview_check as ov

BOUND = Path("data/output/v9_qc/dki_kelurahan_official.geojson")


def main():
    base = change.DEST
    path = base / "cosine_2020_2025.tif"
    png = base / "Jakarta_2020_2025_embedding_difference.png"
    if png.exists():
        raise FileExistsError(png)
    record = next(
        v
        for v in ov.checked_json(base / "manifest.json")["comparisons"]
        if v["years"] == [2020, 2025]
    )
    if (
        g.sha256_file(path) != record["sha256"]
        or g.sha256_file(BOUND)
        != "7bb4dd0589cec8bd64e8930c94b1835116701b6148f7b7de183e61196593c540"
    ):
        raise ValueError("Unverified map inputs")
    with rasterio.open(path) as ds:
        data = ds.read(1, masked=True)
        left, bottom, right, top = ds.bounds
        crs = ds.crs
    municipalities = gp.read_file(BOUND).to_crs(crs)
    mainland = municipalities.loc[
        municipalities.wadmkk.str.startswith("JAKARTA ")
    ].copy()
    mainland.geometry = mainland.geometry.make_valid()
    outline = mainland.dissolve().boundary
    cap = float(np.percentile(data.compressed(), 99))
    if not np.isfinite(cap) or cap <= 0:
        raise ValueError("Non-positive display scale")
    fig, ax = plt.subplots(figsize=(10, 8.5))
    fig.subplots_adjust(left=0.09, right=0.95, top=0.86, bottom=0.19)
    fig.text(
        0.09, 0.95, "Jakarta  |  2020 to 2025", fontsize=23, fontweight="bold", va="top"
    )
    fig.text(
        0.09,
        0.901,
        "Difference in annual satellite embeddings",
        fontsize=14,
        va="top",
    )
    im = ax.imshow(
        data,
        extent=(left, right, bottom, top),
        origin="upper",
        interpolation="nearest",
        cmap="cividis",
        vmin=0,
        vmax=cap,
    )
    outline.plot(
        ax=ax,
        linewidth=0.95,
        color="white",
        path_effects=[pe.Stroke(linewidth=2.1, foreground="#212628"), pe.Normal()],
    )
    ax.set_xlim(left, right)
    ax.set_ylim(bottom, top)
    ax.set_aspect(1 / np.cos(np.deg2rad((bottom + top) / 2)))
    ax.set_xlabel("Longitude (°E)")
    ax.set_ylabel("Latitude (°)")
    cb = fig.colorbar(
        im,
        ax=ax,
        orientation="horizontal",
        pad=0.15,
        shrink=0.78,
        aspect=45,
        extend="max",
    )
    cb.set_label("Cosine distance across 64 axes  ·  larger values = less similar")
    fig.text(
        0.09,
        0.105,
        f"Outline: mainland DKI Jakarta. Colour saturates at the 99th percentile ({cap:.3f}); the GeoTIFF is not capped.",
        fontsize=9,
    )
    fig.text(
        0.09,
        0.078,
        "The rectangle includes water. Embedding differences do not by themselves identify construction, subsidence or risk.",
        fontsize=9,
    )
    fig.text(
        0.09,
        0.045,
        "The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google DeepMind.",
        fontsize=8,
        color="#4b5155",
    )
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        f = Path(tmp) / png.name
        fig.savefig(f, dpi=160, facecolor="white")
        os.link(f, png)
    plt.close(fig)


if __name__ == "__main__":
    main()
