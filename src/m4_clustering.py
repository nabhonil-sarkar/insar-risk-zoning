"""
Module 4 — Land Cover Clustering (Stage 1 of Option B)

Clusters ONLY on AlphaEarth embedding features to discover land cover types.
No InSAR data is involved in this step — subsidence analysis happens in Stage 2.

This separation ensures that land cover classes are discovered purely from
spectral-temporal signatures, without any influence from ground motion data.
"""

import os
import numpy as np
import pickle
from sklearn.cluster import MiniBatchKMeans
from sklearn.mixture import GaussianMixture
from sklearn.metrics import silhouette_score, davies_bouldin_score
from sklearn.decomposition import PCA

from src.utils.geo_utils import features_to_raster, save_raster
from config.settings import (
    K_RANGE, RANDOM_STATE, OUT_CLUSTERS_DIR,
    HDBSCAN_MIN_CLUSTER_SIZE, HDBSCAN_MIN_SAMPLES,
)


def find_optimal_k(features, k_range=None, method="kmeans"):
    """
    Evaluate multiple values of k on embedding features only.

    Parameters
    ----------
    features : np.ndarray
        Shape (n_samples, 64) — embedding features only.
    k_range : range or list of int
    method : str

    Returns
    -------
    results : dict
    """
    if k_range is None:
        k_range = K_RANGE

    k_values = list(k_range)
    inertias = []
    silhouettes = []
    db_scores = []

    max_sil = 30_000
    if len(features) > max_sil:
        sil_idx = np.random.RandomState(RANDOM_STATE).choice(
            len(features), max_sil, replace=False
        )
        sil_features = features[sil_idx]
    else:
        sil_features = features

    for k in k_values:
        print(f"  Testing k={k}...", end=" ")

        if method == "kmeans":
            model = MiniBatchKMeans(
                n_clusters=k, random_state=RANDOM_STATE,
                batch_size=10_000, n_init=3, max_iter=300,
            )
            model.fit(features)
            inertias.append(model.inertia_)
            labels_sil = model.predict(sil_features)
        elif method == "gmm":
            model = GaussianMixture(
                n_components=k, random_state=RANDOM_STATE,
                covariance_type="diag", n_init=2, max_iter=200,
            )
            model.fit(features)
            inertias.append(-model.lower_bound_)
            labels_sil = model.predict(sil_features)

        sil = silhouette_score(sil_features, labels_sil)
        db = davies_bouldin_score(sil_features, labels_sil)
        silhouettes.append(sil)
        db_scores.append(db)
        print(f"silhouette={sil:.4f}, DB={db:.4f}")

    best_k = k_values[np.argmax(silhouettes)]
    print(f"\nBest k by silhouette: {best_k}")

    return {
        "k_values": k_values,
        "inertias": inertias,
        "silhouettes": silhouettes,
        "davies_bouldin": db_scores,
        "best_k": best_k,
    }


def run_kmeans(features, n_clusters, full_features=None):
    """
    Run K-Means on embedding features.

    Parameters
    ----------
    features : np.ndarray
        Training samples, shape (n_samples, 64).
    n_clusters : int
    full_features : np.ndarray, optional

    Returns
    -------
    labels : np.ndarray
    model : MiniBatchKMeans
    """
    print(f"Running K-Means with k={n_clusters} on embeddings only...")
    model = MiniBatchKMeans(
        n_clusters=n_clusters,
        random_state=RANDOM_STATE,
        batch_size=10_000,
        n_init=5,
        max_iter=500,
    )
    model.fit(features)

    if full_features is not None:
        labels = model.predict(full_features)
        print(f"Predicted labels for {len(full_features):,} pixels")
    else:
        labels = model.labels_

    return labels, model


def run_gmm(features, n_components, full_features=None):
    """Run GMM on embedding features."""
    print(f"Running GMM with {n_components} components on embeddings only...")
    model = GaussianMixture(
        n_components=n_components,
        random_state=RANDOM_STATE,
        covariance_type="diag",
        n_init=3,
        max_iter=300,
    )
    model.fit(features)

    predict_data = full_features if full_features is not None else features
    labels = model.predict(predict_data)
    probabilities = model.predict_proba(predict_data)

    return labels, probabilities, model


def run_hdbscan(features, min_cluster_size=None, min_samples=None):
    """Run HDBSCAN on embedding features."""
    import hdbscan

    if min_cluster_size is None:
        min_cluster_size = HDBSCAN_MIN_CLUSTER_SIZE
    if min_samples is None:
        min_samples = HDBSCAN_MIN_SAMPLES

    print(f"Running HDBSCAN on embeddings only...")

    if features.shape[1] > 20:
        print("  Reducing to 20 PCA components...")
        pca = PCA(n_components=20, random_state=RANDOM_STATE)
        features_reduced = pca.fit_transform(features)
        explained = pca.explained_variance_ratio_.sum()
        print(f"  PCA explains {explained:.1%} of variance")
    else:
        features_reduced = features

    model = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        core_dist_n_jobs=-1,
    )
    labels = model.fit_predict(features_reduced)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = (labels == -1).sum()
    print(f"  Found {n_clusters} clusters, {n_noise:,} noise points")

    return labels, model


def cluster_embeddings(features, valid_mask, full_features, profile,
                       method="kmeans", n_clusters=None, output_dir=None):
    """
    Run clustering on embedding features only.
    Save cluster label raster and model.

    Parameters
    ----------
    features : np.ndarray
        Training sample (embeddings only).
    valid_mask : np.ndarray
        Boolean (H, W).
    full_features : np.ndarray
        All valid pixels (embeddings only).
    profile : dict
    method : str
    n_clusters : int, optional
    output_dir : str, optional

    Returns
    -------
    labels : np.ndarray
    label_raster : np.ndarray
        Shape (1, H, W).
    metrics : dict
    """
    if output_dir is None:
        output_dir = OUT_CLUSTERS_DIR
    os.makedirs(output_dir, exist_ok=True)

    # Run clustering on embeddings only
    if method == "kmeans":
        labels, model = run_kmeans(features, n_clusters, full_features)
    elif method == "gmm":
        labels, probs, model = run_gmm(features, n_clusters, full_features)
    elif method == "hdbscan":
        labels, model = run_hdbscan(full_features)
    else:
        raise ValueError(f"Unknown method: {method}")

    # Map labels back to raster
    label_raster = features_to_raster(labels, valid_mask, nodata_value=-1)

    # Save
    k_str = f"k{n_clusters}" if n_clusters else "auto"
    label_path = os.path.join(output_dir, f"landcover_clusters_{method}_{k_str}.tif")
    save_raster(label_path, label_raster, profile, nodata=-1)

    model_path = os.path.join(output_dir, f"model_{method}_{k_str}.pkl")
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    print(f"Saved model: {model_path}")

    # Evaluate clustering quality
    valid = labels >= 0
    n_unique = len(np.unique(labels[valid]))
    max_sil = 50_000
    if valid.sum() > max_sil:
        idx = np.random.RandomState(RANDOM_STATE).choice(
            valid.sum(), max_sil, replace=False
        )
        feat_sub = full_features[valid][idx]
        lab_sub = labels[valid][idx]
    else:
        feat_sub = full_features[valid]
        lab_sub = labels[valid]

    if n_unique >= 2:
        sil = silhouette_score(feat_sub, lab_sub)
        db = davies_bouldin_score(feat_sub, lab_sub)
    else:
        sil = db = float("nan")

    metrics = {
        "silhouette": round(sil, 4) if not np.isnan(sil) else sil,
        "davies_bouldin": round(db, 4) if not np.isnan(db) else db,
        "n_clusters": n_unique,
        "n_valid_pixels": int(valid.sum()),
    }

    print("Land Cover Clustering Metrics:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    return labels, label_raster, metrics
