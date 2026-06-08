"""
Plotting utilities for maps, cluster profiles, and evaluation charts.
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.patches import Patch
import rasterio
from rasterio.plot import show as rioshow
import os


def plot_cluster_map(label_raster, transform, title="Cluster Map",
                     cmap="tab10", nodata_value=-1, save_path=None):
    """
    Plot a cluster label raster as a colored map.

    Parameters
    ----------
    label_raster : np.ndarray
        Shape (1, H, W) or (H, W) with integer cluster labels.
    transform : rasterio.Affine
        Geotransform for spatial axes.
    title : str
    cmap : str
        Matplotlib colormap name.
    nodata_value : int
        Value indicating no-data pixels.
    save_path : str, optional
        If provided, saves the figure.
    """
    if label_raster.ndim == 3:
        label_raster = label_raster[0]

    masked = np.ma.masked_where(label_raster == nodata_value, label_raster)
    n_clusters = len(np.unique(label_raster[label_raster != nodata_value]))

    fig, ax = plt.subplots(1, 1, figsize=(12, 10))
    im = ax.imshow(masked, cmap=cmap, interpolation="nearest")
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel("Column")
    ax.set_ylabel("Row")

    cbar = plt.colorbar(im, ax=ax, shrink=0.7)
    cbar.set_label("Cluster ID")

    plt.tight_layout()
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path, dpi=200, bbox_inches="tight")
        print(f"Saved figure: {save_path}")
    plt.show()


def plot_cluster_profiles(features, labels, feature_names=None,
                          title="Cluster Profiles", save_path=None):
    """
    Plot the mean feature values for each cluster as a grouped bar/line chart.

    Parameters
    ----------
    features : np.ndarray
        Shape (n_pixels, n_features).
    labels : np.ndarray
        Shape (n_pixels,).
    feature_names : list of str, optional
        Names for each feature dimension.
    """
    unique_labels = np.unique(labels[labels >= 0])
    n_features = features.shape[1]

    if feature_names is None:
        feature_names = [f"F{i}" for i in range(n_features)]

    fig, ax = plt.subplots(figsize=(14, 6))
    x = np.arange(n_features)

    for label in unique_labels:
        cluster_mask = labels == label
        means = features[cluster_mask].mean(axis=0)
        ax.plot(x, means, marker="o", markersize=3, label=f"Cluster {label}", alpha=0.8)

    ax.set_xlabel("Feature Dimension")
    ax.set_ylabel("Mean Value (normalized)")
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.legend(bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)

    # Only show a subset of tick labels if many features
    if n_features > 20:
        step = max(n_features // 15, 1)
        ax.set_xticks(x[::step])
        ax.set_xticklabels([feature_names[i] for i in range(0, n_features, step)],
                           rotation=45, ha="right", fontsize=8)
    else:
        ax.set_xticks(x)
        ax.set_xticklabels(feature_names, rotation=45, ha="right", fontsize=8)

    plt.tight_layout()
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path, dpi=200, bbox_inches="tight")
        print(f"Saved figure: {save_path}")
    plt.show()


def plot_subsidence_by_cluster(subsidence_values, labels,
                               title="Subsidence Distribution by Cluster",
                               save_path=None):
    """
    Box plot of subsidence velocity grouped by cluster.

    Parameters
    ----------
    subsidence_values : np.ndarray
        Shape (n_pixels,) — InSAR velocity in mm/year.
    labels : np.ndarray
        Shape (n_pixels,) — cluster assignments.
    """
    unique_labels = sorted(np.unique(labels[labels >= 0]))

    data_by_cluster = []
    tick_labels = []
    for label in unique_labels:
        vals = subsidence_values[labels == label]
        data_by_cluster.append(vals)
        tick_labels.append(f"C{label}\n(n={len(vals):,})")

    fig, ax = plt.subplots(figsize=(12, 6))
    bp = ax.boxplot(data_by_cluster, labels=tick_labels, patch_artist=True,
                    showfliers=False, medianprops=dict(color="black", linewidth=2))

    colors = plt.cm.tab10(np.linspace(0, 1, len(unique_labels)))
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    ax.set_ylabel("Subsidence Velocity (mm/year)")
    ax.set_xlabel("Cluster")
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.8)

    plt.tight_layout()
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path, dpi=200, bbox_inches="tight")
        print(f"Saved figure: {save_path}")
    plt.show()


def plot_elbow_silhouette(k_values, inertias, silhouettes, save_path=None):
    """
    Plot the elbow curve (inertia) and silhouette scores side by side.

    Parameters
    ----------
    k_values : list of int
    inertias : list of float
    silhouettes : list of float
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    ax1.plot(k_values, inertias, "bo-", linewidth=2, markersize=6)
    ax1.set_xlabel("Number of Clusters (k)")
    ax1.set_ylabel("Inertia")
    ax1.set_title("Elbow Method")
    ax1.grid(True, alpha=0.3)

    ax2.plot(k_values, silhouettes, "rs-", linewidth=2, markersize=6)
    ax2.set_xlabel("Number of Clusters (k)")
    ax2.set_ylabel("Silhouette Score")
    ax2.set_title("Silhouette Analysis")
    ax2.grid(True, alpha=0.3)

    best_k = k_values[np.argmax(silhouettes)]
    ax2.axvline(x=best_k, color="green", linestyle="--", alpha=0.7,
                label=f"Best k = {best_k}")
    ax2.legend()

    plt.suptitle("Cluster Count Evaluation", fontsize=14, fontweight="bold")
    plt.tight_layout()
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path, dpi=200, bbox_inches="tight")
        print(f"Saved figure: {save_path}")
    plt.show()


def plot_rgb_embedding(data, bands=(0, 15, 8), vmin=-0.3, vmax=0.3,
                       title="AlphaEarth Embedding RGB", save_path=None):
    """
    Visualize 3 embedding bands as an RGB composite.

    Parameters
    ----------
    data : np.ndarray
        Shape (64, H, W).
    bands : tuple of int
        0-indexed band indices to assign to R, G, B.
    """
    rgb = np.stack([data[b] for b in bands], axis=-1)
    rgb = np.clip((rgb - vmin) / (vmax - vmin), 0, 1)

    fig, ax = plt.subplots(figsize=(12, 10))
    ax.imshow(rgb)
    ax.set_title(f"{title} (bands {bands})", fontsize=14, fontweight="bold")
    ax.axis("off")

    plt.tight_layout()
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path, dpi=200, bbox_inches="tight")
        print(f"Saved figure: {save_path}")
    plt.show()
