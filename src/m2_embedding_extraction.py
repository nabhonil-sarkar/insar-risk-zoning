"""
Module 2 — Embedding Extraction & Processing

Handles loading AlphaEarth Satellite Embedding GeoTIFFs (exported from GEE),
reprojecting, normalizing, and preparing them for fusion.

Note: The actual Earth Engine export is in scripts/export_embeddings.py.
This module works with the downloaded GeoTIFFs.
"""

import os
import glob
import numpy as np
from src.utils.geo_utils import load_raster, save_raster, reproject_raster
from config.settings import (
    RAW_EMBEDDINGS_DIR, PROC_EMBEDDINGS_DIR, COMMON_CRS, COMMON_RESOLUTION,
    NORMALIZATION_METHOD,
)


# AlphaEarth band names: A01 through A64
EMBEDDING_BANDS = [f"A{i:02d}" for i in range(1, 65)]
N_EMBEDDING_DIMS = 64


def load_embeddings(filepath):
    """
    Load an AlphaEarth embedding GeoTIFF.

    Parameters
    ----------
    filepath : str
        Path to the exported GeoTIFF (64 bands).

    Returns
    -------
    data : np.ndarray
        Shape (64, H, W).
    profile : dict
    """
    data, profile = load_raster(filepath)
    assert data.shape[0] == N_EMBEDDING_DIMS, (
        f"Expected {N_EMBEDDING_DIMS} bands, got {data.shape[0]}. "
        f"Check that the file contains the full embedding."
    )
    print(f"Loaded embeddings: {filepath}")
    print(f"  Shape: {data.shape}")
    print(f"  CRS: {profile['crs']}")
    print(f"  Dtype: {data.dtype}")

    # Quick stats
    valid = ~np.isnan(data[0])
    print(f"  Valid pixels: {valid.sum():,} / {valid.size:,}")
    return data, profile


def find_embedding_files(directory=None, year=None):
    """
    Find embedding GeoTIFFs in the raw data directory.

    Parameters
    ----------
    directory : str, optional
        Directory to search. Defaults to RAW_EMBEDDINGS_DIR.
    year : int, optional
        Filter to files matching a specific year.

    Returns
    -------
    files : list of str
    """
    if directory is None:
        directory = RAW_EMBEDDINGS_DIR

    patterns = ["*.tif", "*.tiff"]
    files = []
    for pat in patterns:
        files.extend(glob.glob(os.path.join(directory, pat)))

    if year is not None:
        files = [f for f in files if str(year) in os.path.basename(f)]

    files.sort()
    print(f"Found {len(files)} embedding file(s) in {directory}")
    for f in files:
        print(f"  {os.path.basename(f)}")
    return files


def normalize_embeddings(data, method=None):
    """
    Normalize embedding values for clustering.

    Parameters
    ----------
    data : np.ndarray
        Shape (64, H, W).
    method : str
        'zscore' — per-band zero mean unit variance
        'minmax' — per-band scale to [0, 1]
        'unit_length' — normalize each pixel's vector to unit length
                        (AlphaEarth embeddings are already roughly unit-length,
                         but this ensures it after any processing)

    Returns
    -------
    normalized : np.ndarray
        Same shape as input.
    """
    if method is None:
        method = NORMALIZATION_METHOD

    normalized = data.copy().astype(np.float32)
    bands, h, w = normalized.shape

    if method == "zscore":
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
        print("Applied z-score normalization (per-band)")

    elif method == "minmax":
        for b in range(bands):
            band_data = normalized[b]
            valid = ~np.isnan(band_data)
            if valid.sum() > 0:
                vmin = band_data[valid].min()
                vmax = band_data[valid].max()
                if vmax > vmin:
                    band_data[valid] = (band_data[valid] - vmin) / (vmax - vmin)
                else:
                    band_data[valid] = 0
        print("Applied min-max normalization (per-band)")

    elif method == "unit_length":
        flat = normalized.reshape(bands, -1)  # (64, n_pixels)
        norms = np.linalg.norm(flat, axis=0, keepdims=True)
        norms[norms == 0] = 1  # avoid division by zero
        flat /= norms
        normalized = flat.reshape(bands, h, w)
        print("Applied unit-length normalization (per-pixel)")

    else:
        raise ValueError(f"Unknown normalization method: {method}")

    return normalized


def compute_embedding_change(data_year1, data_year2, metric="cosine"):
    """
    Compute per-pixel change between two annual embedding layers.

    Parameters
    ----------
    data_year1, data_year2 : np.ndarray
        Shape (64, H, W). Must be aligned to the same grid.
    metric : str
        'cosine' — 1 - cosine_similarity (0=identical, 2=opposite)
        'euclidean' — L2 distance between embedding vectors

    Returns
    -------
    change : np.ndarray
        Shape (1, H, W) — per-pixel change magnitude.
    """
    assert data_year1.shape == data_year2.shape, "Embedding layers must have same shape"
    bands, h, w = data_year1.shape

    flat1 = data_year1.reshape(bands, -1).T  # (n_pixels, 64)
    flat2 = data_year2.reshape(bands, -1).T

    if metric == "cosine":
        dot = np.sum(flat1 * flat2, axis=1)
        norm1 = np.linalg.norm(flat1, axis=1)
        norm2 = np.linalg.norm(flat2, axis=1)
        denom = norm1 * norm2
        denom[denom == 0] = 1
        cos_sim = dot / denom
        change = 1 - cos_sim  # 0 = no change, higher = more change

    elif metric == "euclidean":
        change = np.linalg.norm(flat1 - flat2, axis=1)

    else:
        raise ValueError(f"Unknown metric: {metric}")

    change_map = change.reshape(1, h, w).astype(np.float32)
    print(f"Embedding change ({metric}): "
          f"mean={np.nanmean(change_map):.4f}, "
          f"max={np.nanmax(change_map):.4f}")
    return change_map


def preprocess_embeddings(input_path, output_dir=None, normalize=True):
    """
    Full embedding preprocessing pipeline:
    1. Load raw embedding GeoTIFF
    2. Reproject to common CRS
    3. Normalize
    4. Save processed output

    Parameters
    ----------
    input_path : str
        Path to raw embedding GeoTIFF.
    output_dir : str, optional
    normalize : bool

    Returns
    -------
    output_path : str
    """
    if output_dir is None:
        output_dir = PROC_EMBEDDINGS_DIR
    os.makedirs(output_dir, exist_ok=True)

    basename = os.path.splitext(os.path.basename(input_path))[0]

    # Step 1: Reproject
    reproj_path = os.path.join(output_dir, f"{basename}_reproj.tif")
    reproject_raster(input_path, reproj_path, COMMON_CRS, COMMON_RESOLUTION)

    # Step 2: Load and normalize
    data, profile = load_raster(reproj_path)

    if normalize:
        data = normalize_embeddings(data)
        output_path = os.path.join(output_dir, f"{basename}_norm.tif")
    else:
        output_path = reproj_path

    # Step 3: Save
    if normalize:
        save_raster(output_path, data, profile, nodata=np.nan)

    return output_path
