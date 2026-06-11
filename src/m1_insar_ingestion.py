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
)


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


def preprocess_insar(velocity_path, coherence_path=None, output_dir=None):
    """
    Full InSAR preprocessing pipeline:
    1. Load velocity (and optionally coherence)
    2. Reproject to common CRS
    3. Project LOS velocity to vertical (if INSAR_VELOCITY_IS_LOS)
    4. Apply coherence mask (discard low-quality pixels)
    5. Save processed outputs

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
        Path to the processed, reprojected velocity file (vertical mm/yr).
    """
    if output_dir is None:
        output_dir = PROC_INSAR_DIR
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Reproject velocity to common CRS
    reproj_vel_path = os.path.join(output_dir, "velocity_reproj.tif")
    reproject_raster(velocity_path, reproj_vel_path, COMMON_CRS, COMMON_RESOLUTION)

    # Step 1b: Project LOS velocity to vertical so every downstream product
    # (calibration, severity, risk) is in vertical terms.
    if INSAR_VELOCITY_IS_LOS:
        vel_data, vel_profile = load_raster(reproj_vel_path)
        factor = 1.0 / np.cos(np.radians(INSAR_INCIDENCE_ANGLE_DEG))
        vel_data = los_to_vertical(vel_data)
        save_raster(reproj_vel_path, vel_data, vel_profile, nodata=np.nan)
        print(f"Converted LOS -> vertical velocity "
              f"(incidence={INSAR_INCIDENCE_ANGLE_DEG:g} deg, "
              f"factor={factor:.3f})")

    # Step 2: Apply coherence masking if available
    if coherence_path is not None:
        reproj_coh_path = os.path.join(output_dir, "coherence_reproj.tif")
        reproject_raster(coherence_path, reproj_coh_path, COMMON_CRS, COMMON_RESOLUTION)

        vel_data, vel_profile = load_raster(reproj_vel_path)
        coh_data, _ = load_raster(reproj_coh_path)

        # Mask pixels with coherence below threshold
        low_quality = coh_data[0] < COHERENCE_THRESHOLD
        vel_data[0][low_quality] = np.nan

        masked_path = os.path.join(output_dir, "velocity_masked.tif")
        save_raster(masked_path, vel_data, vel_profile, nodata=np.nan)
        print(f"Masked {low_quality.sum():,} low-coherence pixels (threshold={COHERENCE_THRESHOLD})")
        return masked_path
    else:
        return reproj_vel_path


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
