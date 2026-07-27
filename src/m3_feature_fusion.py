"""
Module 3 — Data Alignment (Option B: Two-Stage)

Aligns InSAR velocity data to the same spatial grid as the embeddings,
then flattens the embedding raster into a feature matrix ready for
clustering.

Does NOT fuse embeddings and InSAR into a single feature matrix — each
dataset stays separate for independent analysis.

Does NOT normalize embeddings — that is handled once by M2 during
preprocessing (z-score / minmax / unit-length per settings). This module
loads the already-normalized `_norm.tif` and flattens it as-is.

Stage 1 clusters on embeddings only.
Stage 2 overlays InSAR onto the resulting clusters.
"""

import os
import numpy as np
import rasterio
from src.utils.geo_utils import (
    load_raster, save_raster, align_rasters, raster_to_features,
)
from config.settings import (
    PROC_FUSED_DIR, RANDOM_STATE,
    MAX_CLUSTERING_SAMPLES, SAMPLE_FRACTION,
    INSAR_RESAMPLING,
)


def align_datasets(embedding_path, insar_velocity_path, output_dir=None,
                   insar_vstd_path=None):
    """
    Align InSAR velocity (and optionally its vstd uncertainty layer) to the
    embedding grid. All datasets are kept as separate files on the same
    pixel grid.

    Parameters
    ----------
    embedding_path : str
        Path to processed 64-band embedding GeoTIFF.
    insar_velocity_path : str
        Path to processed InSAR velocity GeoTIFF (single band, mm/yr).
    output_dir : str, optional
    insar_vstd_path : str, optional
        Path to the vertical-scaled vstd GeoTIFF produced by M1
        (vstd_vertical.tif). Aligned onto the same grid as the velocity and
        carried through as a confidence product: Phase-2 GNSS validation
        needs per-pixel uncertainty, threshold tuning needs the survival
        distribution on the analysis grid, and the map can show confidence.

    Returns
    -------
    embedding_path : str
        Unchanged — just passed through.
    aligned_velocity_path : str
        Path to the velocity file aligned to the embedding grid.
    aligned_vstd_path : str or None
        Path to the aligned vstd file, or None if no vstd was provided.
    """
    if output_dir is None:
        output_dir = PROC_FUSED_DIR
    os.makedirs(output_dir, exist_ok=True)

    emb_data, emb_profile = load_raster(embedding_path)
    print(f"Reference grid: {emb_data.shape[1]}x{emb_data.shape[2]} pixels, "
          f"{emb_data.shape[0]} embedding bands")

    # Align InSAR velocity to the embedding grid
    aligned_vel_path = os.path.join(output_dir, "velocity_aligned.tif")
    # Same rationale as M1: the velocity grid is far coarser than the 30 m
    # embedding grid, so interpolation would fabricate sub-measurement
    # gradients. INSAR_RESAMPLING defaults to 'nearest'.
    align_rasters(embedding_path, insar_velocity_path, aligned_vel_path,
                  resampling=INSAR_RESAMPLING)

    # Align the uncertainty layer identically (same grid, same resampling),
    # so every velocity pixel has a co-registered vstd.
    aligned_vstd_path = None
    if insar_vstd_path is not None:
        if not os.path.exists(insar_vstd_path):
            raise FileNotFoundError(
                f"Configured vstd input does not exist: {insar_vstd_path}"
            )
        aligned_vstd_path = os.path.join(output_dir, "vstd_aligned.tif")
        align_rasters(embedding_path, insar_vstd_path, aligned_vstd_path,
                      resampling=INSAR_RESAMPLING)
        with rasterio.open(aligned_vel_path) as vel_src, \
                rasterio.open(aligned_vstd_path) as vstd_src:
            same_grid = (
                vel_src.width == vstd_src.width
                and vel_src.height == vstd_src.height
                and vel_src.crs == vstd_src.crs
                and vel_src.transform == vstd_src.transform
            )
            if not same_grid:
                raise ValueError(
                    "Aligned velocity and vstd do not share the same grid"
                )
        print(f"Aligned vstd confidence layer -> "
              f"{os.path.basename(aligned_vstd_path)}")

    return embedding_path, aligned_vel_path, aligned_vstd_path



def prepare_embedding_features(embedding_path, sample=True):
    """
    Load pre-normalized embeddings, flatten to feature matrix,
    and optionally subsample for clustering.

    Expects the input file to already be normalized by M2
    (preprocess_embeddings). No additional normalization is applied here.

    Parameters
    ----------
    embedding_path : str
        Path to the normalized embedding GeoTIFF (64 bands, *_norm.tif).
    sample : bool
        If True, subsample for clustering efficiency.

    Returns
    -------
    features : np.ndarray
        Training samples — shape (n_samples, 64).
    valid_mask : np.ndarray
        Boolean (H, W).
    full_features : np.ndarray
        All valid pixels — shape (n_valid_pixels, 64).
    profile : dict
    """
    data, profile = load_raster(embedding_path)

    # Flatten to feature matrix — data is already normalized by M2
    full_features, valid_mask = raster_to_features(data, nodata=np.nan)
    full_features = np.nan_to_num(full_features, nan=0.0)

    # Subsample for clustering if needed
    n_valid = full_features.shape[0]
    if sample and n_valid > MAX_CLUSTERING_SAMPLES:
        rng = np.random.RandomState(RANDOM_STATE)
        n_sample = min(MAX_CLUSTERING_SAMPLES, int(n_valid * SAMPLE_FRACTION))
        features = full_features[rng.choice(n_valid, n_sample, replace=False)]
        print(f"Sampled {n_sample:,} / {n_valid:,} pixels for clustering")
    else:
        features = full_features

    return features, valid_mask, full_features, profile
