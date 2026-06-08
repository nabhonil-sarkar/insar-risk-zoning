"""
Validation utilities.
Compare clustering results against ground truth or known subsidence hotspots.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import (
    silhouette_score,
    davies_bouldin_score,
    calinski_harabasz_score,
)


def compute_internal_metrics(features, labels):
    """
    Compute internal clustering quality metrics (no ground truth needed).

    Parameters
    ----------
    features : np.ndarray
        Shape (n_samples, n_features).
    labels : np.ndarray
        Cluster assignments.

    Returns
    -------
    metrics : dict
    """
    # Filter out noise labels (e.g., -1 from HDBSCAN)
    valid = labels >= 0
    if valid.sum() < 2:
        return {"silhouette": np.nan, "davies_bouldin": np.nan, "calinski_harabasz": np.nan}

    feat = features[valid]
    lab = labels[valid]

    n_unique = len(np.unique(lab))
    if n_unique < 2:
        return {"silhouette": np.nan, "davies_bouldin": np.nan, "calinski_harabasz": np.nan}

    # Subsample for silhouette if dataset is large (expensive O(n^2))
    max_sil_samples = 50_000
    if len(feat) > max_sil_samples:
        idx = np.random.RandomState(42).choice(len(feat), max_sil_samples, replace=False)
        sil = silhouette_score(feat[idx], lab[idx])
    else:
        sil = silhouette_score(feat, lab)

    db = davies_bouldin_score(feat, lab)
    ch = calinski_harabasz_score(feat, lab)

    metrics = {
        "silhouette": round(sil, 4),
        "davies_bouldin": round(db, 4),
        "calinski_harabasz": round(ch, 2),
        "n_clusters": n_unique,
        "n_valid_pixels": int(valid.sum()),
        "n_noise_pixels": int((~valid).sum()),
    }
    print("Clustering Metrics:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    return metrics


def cluster_summary_table(features, labels, feature_names=None,
                          subsidence_col_idx=None):
    """
    Generate a summary table with per-cluster statistics.

    Parameters
    ----------
    features : np.ndarray
        Shape (n_pixels, n_features).
    labels : np.ndarray
        Shape (n_pixels,).
    feature_names : list of str, optional
    subsidence_col_idx : int, optional
        Index of the subsidence velocity feature for special reporting.

    Returns
    -------
    summary : pd.DataFrame
    """
    unique_labels = sorted(np.unique(labels[labels >= 0]))
    rows = []

    for label in unique_labels:
        mask = labels == label
        cluster_data = features[mask]

        row = {
            "cluster": label,
            "pixel_count": int(mask.sum()),
            "pct_of_total": round(mask.sum() / (labels >= 0).sum() * 100, 1),
        }

        if subsidence_col_idx is not None:
            sub_vals = cluster_data[:, subsidence_col_idx]
            row["subsidence_mean_mm_yr"] = round(float(sub_vals.mean()), 2)
            row["subsidence_median_mm_yr"] = round(float(np.median(sub_vals)), 2)
            row["subsidence_std_mm_yr"] = round(float(sub_vals.std()), 2)
            row["subsidence_min_mm_yr"] = round(float(sub_vals.min()), 2)
            row["subsidence_max_mm_yr"] = round(float(sub_vals.max()), 2)

        # Mean of first few embedding dimensions for interpretation
        n_show = min(5, features.shape[1])
        for i in range(n_show):
            name = feature_names[i] if feature_names else f"feat_{i}"
            row[f"{name}_mean"] = round(float(cluster_data[:, i].mean()), 4)

        rows.append(row)

    summary = pd.DataFrame(rows)
    return summary
