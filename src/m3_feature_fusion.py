"""
Module 3 — Data Alignment (Option B: Two-Stage)

Aligns InSAR velocity data to the same spatial grid as the embeddings.
Does NOT fuse them into a single feature matrix — each dataset stays
separate for independent analysis.

Stage 1 clusters on embeddings only.
Stage 2 overlays InSAR onto the resulting clusters.
"""

import os
import numpy as np
from src.utils.geo_utils import (
    load_raster, save_raster, align_rasters, raster_to_features,
)
from config.settings import (
    PROC_FUSED_DIR, NORMALIZATION_METHOD, RANDOM_STATE,
    MAX_CLUSTERING_SAMPLES, SAMPLE_FRACTION,
)


def align_datasets(embedding_path, insar_velocity_path, output_dir=None):
    """
    Align InSAR velocity to the embedding grid. Both datasets are kept
    as separate files on the same pixel grid.

    Parameters
    ----------
    embedding_path : str
        Path to processed 64-band embedding GeoTIFF.
    insar_velocity_path : str
        Path to processed InSAR velocity GeoTIFF (single band, mm/yr).
    output_dir : str, optional

    Returns
    -------
    embedding_path : str
        Unchanged — just passed through.
    aligned_velocity_path : str
        Path to the velocity file aligned to the embedding grid.
    """
    if output_dir is None:
        output_dir = PROC_FUSED_DIR
    os.makedirs(output_dir, exist_ok=True)

    emb_data, emb_profile = load_raster(embedding_path)
    print(f"Reference grid: {emb_data.shape[1]}x{emb_data.shape[2]} pixels, "
          f"{emb_data.shape[0]} embedding bands")

    # Align InSAR velocity to the embedding grid
    aligned_vel_path = os.path.join(output_dir, "velocity_aligned.tif")
    align_rasters(embedding_path, insar_velocity_path, aligned_vel_path)

    return embedding_path, aligned_vel_path


def normalize_embedding_features(data, method=None):
    """
    Normalize embedding values per-band using z-score.

    Parameters
    ----------
    data : np.ndarray
        Shape (bands, H, W).
    method : str

    Returns
    -------
    normalized : np.ndarray
    """
    if method is None:
        method = NORMALIZATION_METHOD

    normalized = data.copy().astype(np.float32)
    bands = normalized.shape[0]

    for b in range(bands):
        band_data = normalized[b]
        valid = ~np.isnan(band_data)
        if valid.sum() > 0:
            mean = band_data[valid].mean()
            std = band_data[valid].std()
            if std > 0:
                band_data[valid] = (band_data[valid] - mean) / std
            else:
                band_data[valid] = 0

    return normalized


def prepare_embedding_features(embedding_path, sample=True):
    """
    Load embeddings, flatten to feature matrix, normalize,
    and optionally subsample for clustering.

    Parameters
    ----------
    embedding_path : str
    sample : bool

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

    # Normalize embeddings
    data = normalize_embedding_features(data)

    # Flatten to feature matrix
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
