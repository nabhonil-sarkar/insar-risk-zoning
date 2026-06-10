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
    HDBSCAN_MAX_FIT_SAMPLES, HDBSCAN_PCA_COMPONENTS,
    HDBSCAN_MAX_NOISE_FRACTION, HDBSCAN_MIN_USABLE_CLUSTERS, HDBSCAN_FALLBACK_K,
    KMEANS_BATCH_SIZE, SILHOUETTE_MAX_SAMPLES, DEFAULT_N_CLUSTERS,
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

    max_sil = SILHOUETTE_MAX_SAMPLES
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
                batch_size=KMEANS_BATCH_SIZE, n_init=3, max_iter=300,
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
        batch_size=KMEANS_BATCH_SIZE,
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


def run_hdbscan(features, full_features=None, min_cluster_size=None,
                min_samples=None, max_fit_samples=None, n_pca=None):
    """
    Run HDBSCAN on embedding features with safety constraints.

    HDBSCAN is O(n²) in distance computation, so it cannot run on
    millions of pixels directly. This function:
      1. Reduces dimensions via PCA (fitted on the training subsample)
      2. Further subsamples to `max_fit_samples` for HDBSCAN fitting
      3. Uses `approximate_predict` to label all remaining pixels

    Parameters
    ----------
    features : np.ndarray
        Training subsample, shape (n_samples, 64). Already subsampled
        by M3 (typically 500K), but may be further reduced here.
    full_features : np.ndarray, optional
        All valid pixels, shape (n_all, 64). If provided,
        approximate_predict labels every pixel after fitting.
    min_cluster_size : int
    min_samples : int
    max_fit_samples : int
        Cap on pixels for HDBSCAN fitting. Default 50,000.
    n_pca : int
        Number of PCA components for dimensionality reduction.

    Returns
    -------
    labels : np.ndarray
        Cluster labels for full_features (or features if not provided).
        Noise points are labeled -1.
    model : hdbscan.HDBSCAN
    quality : dict
        Quality assessment with keys: n_clusters, noise_fraction, usable.
        If usable is False, caller should fall back to another method.
    """
    import hdbscan as hdb

    if min_cluster_size is None:
        min_cluster_size = HDBSCAN_MIN_CLUSTER_SIZE
    if min_samples is None:
        min_samples = HDBSCAN_MIN_SAMPLES
    if max_fit_samples is None:
        max_fit_samples = HDBSCAN_MAX_FIT_SAMPLES
    if n_pca is None:
        n_pca = HDBSCAN_PCA_COMPONENTS

    predict_on_full = full_features is not None

    print(f"Running HDBSCAN on embeddings only...")
    print(f"  Training samples:    {len(features):,}")
    if predict_on_full:
        print(f"  Full prediction set: {len(full_features):,}")
    print(f"  Dimensions:          {features.shape[1]}")

    # ── Step 1: PCA dimensionality reduction ─────────────────────────
    pca = None
    if features.shape[1] > n_pca:
        print(f"  PCA: {features.shape[1]} → {n_pca} components...")
        pca = PCA(n_components=n_pca, random_state=RANDOM_STATE)
        features_reduced = pca.fit_transform(features)
        explained = pca.explained_variance_ratio_.sum()
        print(f"  PCA explains {explained:.1%} of variance")
    else:
        features_reduced = features

    # ── Step 2: Subsample for HDBSCAN fitting ────────────────────────
    if len(features_reduced) > max_fit_samples:
        rng = np.random.RandomState(RANDOM_STATE)
        fit_idx = rng.choice(len(features_reduced), max_fit_samples,
                             replace=False)
        fit_data = features_reduced[fit_idx]
        print(f"  Subsampled {max_fit_samples:,} / "
              f"{len(features_reduced):,} for fitting")
    else:
        fit_data = features_reduced

    # ── Step 3: Fit HDBSCAN ──────────────────────────────────────────
    print(f"  Fitting HDBSCAN (min_cluster_size={min_cluster_size}, "
          f"min_samples={min_samples})...")
    model = hdb.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        core_dist_n_jobs=-1,
        prediction_data=True,  # required for approximate_predict
    )
    model.fit(fit_data)

    n_clusters = len(set(model.labels_)) - (1 if -1 in model.labels_ else 0)
    n_noise_fit = int((model.labels_ == -1).sum())
    print(f"  Fit: {n_clusters} clusters, "
          f"{n_noise_fit:,} noise ({n_noise_fit / len(fit_data) * 100:.1f}%)")

    if n_clusters < 2:
        print("  WARNING: HDBSCAN found fewer than 2 clusters. "
              "Try lowering min_cluster_size or increasing max_fit_samples.")

    # ── Step 4: Predict labels for all pixels ────────────────────────
    if predict_on_full:
        print(f"  Predicting labels for {len(full_features):,} pixels "
              f"via approximate_predict...")
        if pca is not None:
            all_reduced = pca.transform(full_features)
        else:
            all_reduced = full_features

        labels, strengths = hdb.approximate_predict(model, all_reduced)

        n_noise_all = int((labels == -1).sum())
        pct_noise = n_noise_all / len(labels) * 100
        print(f"  Full: {n_noise_all:,} noise ({pct_noise:.1f}%)")

        if pct_noise > 50:
            print(f"  WARNING: {pct_noise:.0f}% noise — downstream analysis "
                  f"will exclude these pixels. Consider lowering "
                  f"min_cluster_size (current: {min_cluster_size}).")
    else:
        labels = model.labels_

    # ── Quality assessment ────────────────────────────────────────────
    n_final = len(set(labels)) - (1 if -1 in labels else 0)
    noise_fraction = float((labels == -1).sum()) / len(labels)
    usable = (n_final >= HDBSCAN_MIN_USABLE_CLUSTERS
              and noise_fraction <= HDBSCAN_MAX_NOISE_FRACTION)

    quality = {
        "n_clusters": n_final,
        "noise_fraction": round(noise_fraction, 4),
        "usable": usable,
    }
    print(f"  Final: {n_final} clusters, "
          f"{int(noise_fraction * len(labels)):,} noise "
          f"({noise_fraction:.1%})"
          f"{'' if usable else ' — UNUSABLE, fallback required'}")

    return labels, model, quality


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
    hdbscan_quality = None

    if method == "kmeans":
        labels, model = run_kmeans(features, n_clusters, full_features)
    elif method == "gmm":
        labels, probs, model = run_gmm(features, n_clusters, full_features)
    elif method == "hdbscan":
        labels, model, hdbscan_quality = run_hdbscan(features, full_features)

        if not hdbscan_quality["usable"]:
            fallback_k = n_clusters if n_clusters else HDBSCAN_FALLBACK_K
            print(f"\n  HDBSCAN produced unusable results "
                  f"({hdbscan_quality['n_clusters']} clusters, "
                  f"{hdbscan_quality['noise_fraction']:.0%} noise).")
            print(f"  Falling back to K-Means with k={fallback_k}...\n")
            labels, model = run_kmeans(features, fallback_k, full_features)
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
    if valid.sum() > SILHOUETTE_MAX_SAMPLES:
        idx = np.random.RandomState(RANDOM_STATE).choice(
            valid.sum(), SILHOUETTE_MAX_SAMPLES, replace=False
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

    # Record HDBSCAN outcome if it was attempted
    if hdbscan_quality is not None:
        metrics["hdbscan_quality"] = hdbscan_quality
        if not hdbscan_quality["usable"]:
            metrics["hdbscan_fallback"] = True
            metrics["note"] = (
                f"HDBSCAN unusable ({hdbscan_quality['n_clusters']} clusters, "
                f"{hdbscan_quality['noise_fraction']:.0%} noise) — "
                f"fell back to K-Means"
            )

    print("Land Cover Clustering Metrics:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    return labels, label_raster, metrics
