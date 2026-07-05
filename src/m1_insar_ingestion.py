"""
Module 1 — InSAR Ingestion & Processing

Handles downloading, processing, and geocoding InSAR displacement data.
Supports two workflows:
  A) Pre-processed velocity maps (e.g., from EGMS, COMET-LiCS, or ASF HyP3)
  B) Raw Sentinel-1 SLC processing via SNAP/ISCE (advanced)

This module focuses on Workflow A for practical accessibility.
"""

import os
import numpy as np
import rasterio
from src.utils.geo_utils import load_raster, save_raster, reproject_raster
from config.settings import (
    RAW_INSAR_DIR, PROC_INSAR_DIR, COMMON_CRS, COMMON_RESOLUTION,
    SUBSIDENCE_THRESHOLDS, COHERENCE_THRESHOLD,
    INSAR_VELOCITY_IS_LOS, INSAR_INCIDENCE_ANGLE_DEG,
    INSAR_NODATA_VALUES, INSAR_RESAMPLING,
)


def _mask_undeclared_nodata(src_path, dst_path):
    """
    Convert undeclared sentinel nodata values (e.g. 0.0 in LiCSBAS-derived
    GeoTIFFs) to NaN, and declare NaN as nodata, BEFORE any resampling.

    Root-cause fix for review finding 1.6: if gaps are stored as 0 without a
    declared nodata, interpolating resamplers blend them into neighboring
    real velocities, producing attenuated halo pixels around every coverage
    gap that then escape the downstream `!= 0` filters and enter the risk
    products as spurious "stable"/"slow" measurements.

    Returns dst_path (a float32 copy with NaN nodata).
    """
    data, profile = load_raster(src_path)
    data = data.astype(np.float32)

    n_converted = 0
    for sentinel in INSAR_NODATA_VALUES:
        hit = data == sentinel
        n_converted += int(hit.sum())
        data[hit] = np.nan
    declared = profile.get("nodata")
    if declared is not None and not np.isnan(declared):
        hit = data == declared
        n_converted += int(hit.sum())
        data[hit] = np.nan

    save_raster(dst_path, data, profile, nodata=np.nan)
    print(f"Nodata masking: {n_converted:,} sentinel-valued pixels -> NaN "
          f"(sentinels: {INSAR_NODATA_VALUES}, declared: {declared})")

    # Content-level poisoning heuristic (complements the name-based guard in
    # _discover_insar_inputs): a raw LiCSBAS export over a coastal frame has
    # a large nodata fraction (ocean + decorrelated land). If the input has
    # essentially no sentinel-valued pixels AND no NaN of its own, its gaps
    # have most likely been arithmetically shifted off the sentinel by prior
    # processing — the signature of an already-calibrated file. Masking is
    # then blind and every gap enters the risk products as fake measurement.
    n_total = data.size
    n_nan_native = int(np.isnan(data).sum())
    if n_total > 0 and (n_converted + n_nan_native) / n_total < 0.001:
        print(
            "WARNING: <0.1% of pixels were nodata (converted + native NaN). "
            "For a coastal frame this is implausible for RAW data. The file "
            "may be an already-processed product whose nodata was shifted "
            "off the sentinel (e.g. by a prior calibration). Verify the "
            "input with gdalinfo / a min-max check before trusting any "
            "downstream results, or adjust INSAR_NODATA_VALUES."
        )

    return dst_path


def load_velocity_map(filepath):
    """
    Load a pre-processed InSAR velocity map (GeoTIFF).
    Expects a single-band raster with values in mm/year.

    Parameters
    ----------
    filepath : str
        Path to the velocity GeoTIFF.

    Returns
    -------
    velocity : np.ndarray
        Shape (1, H, W) — velocity in mm/year.
    profile : dict
        Rasterio profile.
    """
    velocity, profile = load_raster(filepath)
    print(f"Loaded velocity map: {filepath}")
    print(f"  Shape: {velocity.shape}")
    print(f"  CRS: {profile['crs']}")
    print(f"  Value range: [{np.nanmin(velocity):.2f}, {np.nanmax(velocity):.2f}] mm/yr")
    return velocity, profile


def load_coherence_map(filepath):
    """
    Load an InSAR temporal coherence map.
    Values typically range from 0 (no coherence) to 1 (perfect coherence).

    Parameters
    ----------
    filepath : str

    Returns
    -------
    coherence : np.ndarray
        Shape (1, H, W).
    profile : dict
    """
    coherence, profile = load_raster(filepath)
    print(f"Loaded coherence map: {filepath}")
    print(f"  Value range: [{np.nanmin(coherence):.3f}, {np.nanmax(coherence):.3f}]")
    return coherence, profile


def los_to_vertical(velocity, incidence_angle_deg=None):
    """
    Project line-of-sight (LOS) velocity to vertical velocity.

    Assumes deformation is purely vertical, so v_vert = v_los / cos(theta).
    This is a standard approximation for groundwater-extraction subsidence
    (predominantly vertical), but it ignores any horizontal component. For
    rigorous decomposition, combine ascending and descending geometries.

    Parameters
    ----------
    velocity : np.ndarray
        LOS velocity in mm/yr (any shape). NaNs pass through.
    incidence_angle_deg : float, optional
        Radar incidence angle. Defaults to INSAR_INCIDENCE_ANGLE_DEG.

    Returns
    -------
    np.ndarray
        Vertical velocity in mm/yr, same shape.
    """
    if incidence_angle_deg is None:
        incidence_angle_deg = INSAR_INCIDENCE_ANGLE_DEG
    factor = 1.0 / np.cos(np.radians(incidence_angle_deg))
    return velocity * factor


def _stamp_velocity_tags(path, is_vertical):
    """
    Write self-describing unit metadata into a velocity GeoTIFF's tags so the
    file's unit state can never be inferred ambiguously from a filename alone.

    Records whether the data is vertical or line-of-sight, and (when vertical)
    the incidence angle and scale factor used for the projection.
    """
    tags = {
        "velocity_units": "mm/yr",
        "velocity_reference": "vertical" if is_vertical else "line_of_sight",
    }
    if is_vertical and INSAR_VELOCITY_IS_LOS:
        tags["los_to_vertical_applied"] = "true"
        tags["incidence_angle_deg"] = f"{INSAR_INCIDENCE_ANGLE_DEG:g}"
        tags["los_to_vertical_factor"] = (
            f"{1.0 / np.cos(np.radians(INSAR_INCIDENCE_ANGLE_DEG)):.6f}"
        )
    else:
        tags["los_to_vertical_applied"] = "false"
    with rasterio.open(path, "r+") as ds:
        ds.update_tags(**tags)


def preprocess_insar(velocity_path, coherence_path=None, output_dir=None):
    """
    Full InSAR preprocessing pipeline:
    1. Reproject to common CRS                       -> velocity_reproj.tif
    2. Project LOS velocity to vertical (if enabled) -> velocity_vertical.tif
    3. Apply coherence mask (if coherence provided)  -> velocity_masked.tif

    Each stage writes a DISTINCT file rather than overwriting in place. This
    keeps the LOS->vertical conversion unambiguous: the reprojected file is
    always raw LOS units, and the vertical file is always converted. An
    interrupt can never leave a half-converted file that a later cached run
    mistakes for the wrong unit (review finding 1.2). Unit state is also
    stamped into each file's GeoTIFF tags so it is self-describing.

    Parameters
    ----------
    velocity_path : str
        Path to raw velocity GeoTIFF.
    coherence_path : str, optional
        Path to coherence GeoTIFF. If None, no quality masking is applied.
    output_dir : str, optional
        Output directory. Defaults to PROC_INSAR_DIR.

    Returns
    -------
    output_velocity_path : str
        Path to the final processed velocity file (vertical mm/yr unless
        INSAR_VELOCITY_IS_LOS is False). This is the file downstream stages
        should consume.
    """
    if output_dir is None:
        output_dir = PROC_INSAR_DIR
    os.makedirs(output_dir, exist_ok=True)

    # ── Step 0: Mask undeclared nodata BEFORE any resampling ──────────────
    nodata_masked_path = os.path.join(output_dir, "velocity_nodata_masked.tif")
    _mask_undeclared_nodata(velocity_path, nodata_masked_path)

    # ── Step 1: Reproject velocity to common CRS (stays in raw LOS units) ──
    # Resampling per INSAR_RESAMPLING: the raw grid (~1 km) is much coarser
    # than COMMON_RESOLUTION, so 'nearest' preserves measurement values
    # exactly instead of inventing gradients between them.
    reproj_vel_path = os.path.join(output_dir, "velocity_reproj.tif")
    reproject_raster(nodata_masked_path, reproj_vel_path, COMMON_CRS,
                     COMMON_RESOLUTION, resampling=INSAR_RESAMPLING)
    _stamp_velocity_tags(reproj_vel_path, is_vertical=False)

    # ── Step 2: Project LOS -> vertical into a DISTINCT file ──────────────
    # Every downstream product (calibration, severity, risk) consumes the
    # vertical file. Writing to a new path (not overwriting reproj) means the
    # conversion is atomic from the cache's perspective.
    if INSAR_VELOCITY_IS_LOS:
        vel_data, vel_profile = load_raster(reproj_vel_path)
        factor = 1.0 / np.cos(np.radians(INSAR_INCIDENCE_ANGLE_DEG))
        vel_data = los_to_vertical(vel_data)
        vertical_path = os.path.join(output_dir, "velocity_vertical.tif")
        save_raster(vertical_path, vel_data, vel_profile, nodata=np.nan)
        _stamp_velocity_tags(vertical_path, is_vertical=True)
        print(f"Converted LOS -> vertical velocity "
              f"(incidence={INSAR_INCIDENCE_ANGLE_DEG:g} deg, "
              f"factor={factor:.3f}) -> {os.path.basename(vertical_path)}")
        processed_vel_path = vertical_path
    else:
        # Data is already vertical (or the user has opted out of conversion).
        processed_vel_path = reproj_vel_path

    # ── Step 3: Apply coherence masking if available ──────────────────────
    if coherence_path is not None:
        reproj_coh_path = os.path.join(output_dir, "coherence_reproj.tif")
        reproject_raster(coherence_path, reproj_coh_path, COMMON_CRS,
                         COMMON_RESOLUTION, resampling=INSAR_RESAMPLING)

        vel_data, vel_profile = load_raster(processed_vel_path)
        coh_data, _ = load_raster(reproj_coh_path)

        # Mask pixels with coherence below threshold
        low_quality = coh_data[0] < COHERENCE_THRESHOLD
        vel_data[0][low_quality] = np.nan

        masked_path = os.path.join(output_dir, "velocity_masked.tif")
        save_raster(masked_path, vel_data, vel_profile, nodata=np.nan)
        _stamp_velocity_tags(masked_path,
                             is_vertical=INSAR_VELOCITY_IS_LOS)
        print(f"Masked {low_quality.sum():,} low-coherence pixels (threshold={COHERENCE_THRESHOLD})")
        return masked_path
    else:
        return processed_vel_path


def categorize_subsidence(velocity_data, thresholds=None):
    """
    Categorize velocity values into subsidence severity classes.
    Useful for quick visualization and validation.

    Parameters
    ----------
    velocity_data : np.ndarray
        Velocity in mm/year (negative = subsidence).
    thresholds : dict, optional

    Returns
    -------
    categories : np.ndarray
        Integer category labels (0=stable, 1=slow, 2=moderate, 3=rapid).
    """
    if thresholds is None:
        thresholds = SUBSIDENCE_THRESHOLDS

    categories = np.full_like(velocity_data, -1, dtype=np.int8)

    for i, (name, (lo, hi)) in enumerate(thresholds.items()):
        mask = (velocity_data >= lo) & (velocity_data < hi)
        categories[mask] = i

    return categories


def generate_synthetic_insar(shape, seed=42):
    """
    Generate synthetic InSAR velocity data for testing the pipeline
    when real data is not yet available.

    Creates a realistic-looking subsidence pattern with:
    - A coastal gradient (more subsidence near the coast)
    - Random hotspots of rapid subsidence
    - Gaussian noise

    Parameters
    ----------
    shape : tuple
        (height, width) of the output raster.
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    velocity : np.ndarray
        Shape (1, H, W) — synthetic velocity in mm/year.
    """
    rng = np.random.RandomState(seed)
    h, w = shape

    # Base: gradient from north (stable) to south (subsiding)
    gradient = np.linspace(0, -15, h)[:, np.newaxis] * np.ones((1, w))

    # Add subsidence hotspots
    hotspots = np.zeros((h, w))
    n_hotspots = 8
    for _ in range(n_hotspots):
        cy, cx = rng.randint(0, h), rng.randint(0, w)
        sigma = rng.randint(20, 80)
        amplitude = rng.uniform(-30, -5)
        yy, xx = np.ogrid[:h, :w]
        hotspots += amplitude * np.exp(-((yy - cy)**2 + (xx - cx)**2) / (2 * sigma**2))

    # Add noise
    noise = rng.normal(0, 2, (h, w))

    velocity = gradient + hotspots + noise
    return velocity[np.newaxis, :, :]  # (1, H, W)
