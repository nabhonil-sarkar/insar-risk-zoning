"""
Geospatial utility functions.
Handles raster I/O, reprojection, resampling, and grid alignment.
"""

import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.merge import merge
from rasterio.mask import mask as rio_mask
from shapely.geometry import box
import geopandas as gpd
import os


def load_raster(filepath, bands=None):
    """
    Load a raster file and return the array + metadata.

    Parameters
    ----------
    filepath : str
        Path to GeoTIFF file.
    bands : list of int, optional
        1-indexed band numbers to read. None reads all bands.

    Returns
    -------
    data : np.ndarray
        Array of shape (bands, height, width).
    profile : dict
        Rasterio profile (CRS, transform, dimensions, dtype, etc.).
    """
    with rasterio.open(filepath) as src:
        if bands is None:
            data = src.read()
        else:
            data = src.read(bands)
        profile = src.profile.copy()
    return data, profile


def save_raster(filepath, data, profile, nodata=None):
    """
    Save a numpy array as a GeoTIFF.

    Parameters
    ----------
    filepath : str
        Output path.
    data : np.ndarray
        Array of shape (bands, height, width).
    profile : dict
        Rasterio profile. Band count and dtype will be updated automatically.
    nodata : float, optional
        NoData value to set.
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    profile.update(
        count=data.shape[0],
        dtype=data.dtype,
        compress="lzw",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    )
    if nodata is not None:
        profile["nodata"] = nodata

    temp_path = filepath + ".tmp"
    try:
        with rasterio.open(temp_path, "w", **profile) as dst:
            dst.write(data)
        os.replace(temp_path, filepath)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    print(f"Saved: {filepath} — shape {data.shape}")


def _resolve_resampling(resampling):
    """Accept a Resampling enum or its lowercase string name."""
    if isinstance(resampling, str):
        try:
            return Resampling[resampling.lower()]
        except KeyError as exc:
            allowed = ", ".join(member.name for member in Resampling)
            raise ValueError(
                f"Unknown resampling method {resampling!r}; "
                f"allowed: {allowed}"
            ) from exc
    if not isinstance(resampling, Resampling):
        raise TypeError(
            "resampling must be a rasterio Resampling value or string name"
        )
    return resampling


def reproject_raster(src_path, dst_path, dst_crs, dst_resolution=None,
                     resampling=Resampling.bilinear):
    """
    Reproject a raster to a new CRS and optionally resample to a new resolution.

    Parameters
    ----------
    src_path : str
        Input raster path.
    dst_path : str
        Output raster path.
    dst_crs : str
        Target CRS (e.g., 'EPSG:32748').
    dst_resolution : float, optional
        Target pixel size in CRS units (meters for UTM). None keeps source resolution.
    resampling : rasterio.warp.Resampling or str
        Interpolation method. Use 'nearest' for categorical data or for
        sparse measurements that must not be blended (e.g. InSAR velocity
        upsampled far beyond its native resolution). Default bilinear.

    Returns
    -------
    dst_path : str
        Path to the reprojected raster.
    """
    resampling = _resolve_resampling(resampling)
    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds,
            resolution=dst_resolution,
        )
        profile = src.profile.copy()
        profile.update(
            crs=dst_crs,
            transform=transform,
            width=width,
            height=height,
            compress="lzw",
        )

        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        temp_path = dst_path + ".tmp"
        try:
            with rasterio.open(temp_path, "w", **profile) as dst:
                for i in range(1, src.count + 1):
                    reproject(
                        source=rasterio.band(src, i),
                        destination=rasterio.band(dst, i),
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=transform,
                        dst_crs=dst_crs,
                        src_nodata=src.nodata,
                        dst_nodata=profile.get("nodata"),
                        resampling=resampling,
                    )
            os.replace(temp_path, dst_path)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise
    print(f"Reprojected: {dst_path} -> {dst_crs} "
          f"(resampling={resampling.name})")
    return dst_path


def align_rasters(reference_path, target_path, output_path,
                  resampling=Resampling.bilinear):
    """
    Resample and align a target raster to match the grid of a reference raster.
    Both must already share the same CRS.

    Parameters
    ----------
    reference_path : str
        Path to the reference raster (defines the grid).
    target_path : str
        Path to the raster to be aligned.
    output_path : str
        Where to save the aligned raster.
    resampling : rasterio.warp.Resampling or str
        Interpolation method (see reproject_raster). Default bilinear.

    Returns
    -------
    output_path : str
    """
    resampling = _resolve_resampling(resampling)
    with rasterio.open(reference_path) as ref:
        ref_transform = ref.transform
        ref_crs = ref.crs
        ref_width = ref.width
        ref_height = ref.height

    with rasterio.open(target_path) as src:
        profile = src.profile.copy()
        profile.update(
            crs=ref_crs,
            transform=ref_transform,
            width=ref_width,
            height=ref_height,
            compress="lzw",
        )

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        temp_path = output_path + ".tmp"
        try:
            with rasterio.open(temp_path, "w", **profile) as dst:
                for i in range(1, src.count + 1):
                    reproject(
                        source=rasterio.band(src, i),
                        destination=rasterio.band(dst, i),
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=ref_transform,
                        dst_crs=ref_crs,
                        src_nodata=src.nodata,
                        dst_nodata=profile.get("nodata"),
                        resampling=resampling,
                    )
            os.replace(temp_path, output_path)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise
    print(f"Aligned {target_path} to reference grid -> {output_path} "
          f"(resampling={resampling.name})")
    return output_path


def raster_to_features(data, nodata=None):
    """
    Reshape a multi-band raster array into a 2D feature matrix for ML.

    Parameters
    ----------
    data : np.ndarray
        Shape (bands, height, width).
    nodata : float, optional
        Value to treat as missing. Pixels with nodata in any band are excluded.

    Returns
    -------
    features : np.ndarray
        Shape (n_valid_pixels, bands).
    valid_mask : np.ndarray
        Boolean array of shape (height, width). True where pixel is valid.
    """
    bands, height, width = data.shape
    flat = data.reshape(bands, -1).T  # (n_pixels, bands)

    if nodata is not None:
        valid_mask = ~np.any(np.isnan(flat) | (flat == nodata), axis=1)
    else:
        valid_mask = ~np.any(np.isnan(flat), axis=1)

    features = flat[valid_mask]
    valid_mask_2d = valid_mask.reshape(height, width)

    print(f"Feature matrix: {features.shape[0]:,} valid pixels × {features.shape[1]} features")
    return features, valid_mask_2d


def features_to_raster(labels, valid_mask, nodata_value=-1):
    """
    Map a 1D array of cluster labels back onto a 2D raster grid.

    Parameters
    ----------
    labels : np.ndarray
        Shape (n_valid_pixels,).
    valid_mask : np.ndarray
        Boolean array of shape (height, width).
    nodata_value : int
        Fill value for invalid pixels.

    Returns
    -------
    label_raster : np.ndarray
        Shape (1, height, width).
    """
    height, width = valid_mask.shape
    label_raster = np.full((height, width), nodata_value, dtype=np.int32)
    label_raster[valid_mask] = labels
    return label_raster[np.newaxis, :, :]  # add band dimension


def get_raster_bounds(filepath):
    """Return the bounding box of a raster as a Shapely geometry."""
    with rasterio.open(filepath) as src:
        return box(*src.bounds)
