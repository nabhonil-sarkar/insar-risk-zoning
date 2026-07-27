"""
Sub-cluster analysis: divide the highest-risk land cover cluster into
sub-populations based on embedding features alone.

Reads pipeline_state.json (written by run_full_pipeline.py) to discover
file paths and auto-select the highest-risk cluster. All paths, cluster
IDs, and cluster counts are dynamic.

Usage:
    python scripts/subcluster_analysis.py                   # auto-select target
    python scripts/subcluster_analysis.py --cluster 2       # override target
    python scripts/subcluster_analysis.py --sub-k 3         # override sub-k
    python scripts/subcluster_analysis.py --state path.json  # custom state file
"""

import sys
import os
import json
import argparse
import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import silhouette_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    OUT_CLUSTERS_DIR, OUT_FIGURES_DIR, RANDOM_STATE,
    PIPELINE_STATE_FILE, PIPELINE_STATE_SCHEMA_VERSION,
    SUB_K_RANGE, SUBCLUSTER_MAX_SAMPLES,
)


# ══════════════════════════════════════════════════════════════════════════════
# STATE & CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

def load_pipeline_state(state_path=None):
    """
    Load pipeline state written by run_full_pipeline.py.

    Returns
    -------
    state : dict
        Contains 'paths', 'config', and 'risk_summary'.
    """
    if state_path is None:
        state_path = PIPELINE_STATE_FILE

    if not os.path.exists(state_path):
        print(f"ERROR: Pipeline state not found: {state_path}")
        print("Run the main pipeline first: python scripts/run_full_pipeline.py")
        sys.exit(1)

    with open(state_path, encoding="utf-8") as f:
        state = json.load(f)

    schema_version = state.get("schema_version")
    if schema_version != PIPELINE_STATE_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported pipeline-state schema {schema_version!r}; "
            f"expected {PIPELINE_STATE_SCHEMA_VERSION}. Rerun the main "
            "pipeline before sub-clustering."
        )
    required_sections = {"timestamp", "config", "paths", "risk_summary"}
    missing = required_sections - set(state)
    if missing:
        raise ValueError(
            f"Pipeline state is missing required sections: {sorted(missing)}"
        )

    print(f"Loaded pipeline state: {state_path}")
    print(f"  Pipeline ran: {state['timestamp']}")
    print(f"  Method: {state['config']['method']}, "
          f"k={state['config']['n_clusters']}")
    return state


def identify_target_cluster(state, target_cluster=None):
    """
    Determine which cluster to sub-cluster.

    If target_cluster is specified, validates it and returns it.
    Otherwise, picks the cluster with the highest risk level
    (breaking ties by highest pct_rapid).

    Parameters
    ----------
    state : dict
        Pipeline state with 'risk_summary'.
    target_cluster : int or None
        Explicit override.

    Returns
    -------
    target : int
        Cluster ID to sub-cluster.
    """
    risk_summary = state["risk_summary"]
    valid_ids = [r["cluster"] for r in risk_summary]

    if target_cluster is not None:
        if target_cluster not in valid_ids:
            print(f"ERROR: Cluster {target_cluster} not found. "
                  f"Valid clusters: {valid_ids}")
            sys.exit(1)
        print(f"Target cluster (user override): {target_cluster}")
        return target_cluster

    # Auto-select: highest assessed risk, then highest pct_rapid as
    # tiebreaker. Never auto-target a cluster whose coverage gate failed.
    risk_order = {"very_high": 4, "high": 3, "moderate": 2, "low": 1}
    eligible = [
        record for record in risk_summary
        if record.get("cluster_risk") in risk_order
    ]
    if not eligible:
        raise ValueError(
            "No cluster has sufficient velocity evidence for automatic "
            "sub-clustering"
        )
    best = max(eligible, key=lambda r: (
        risk_order.get(r["cluster_risk"], 0),
        r["pct_rapid"],
    ))
    target = int(best["cluster"])
    print(f"Auto-selected target cluster: {target} "
          f"(risk={best['cluster_risk']}, "
          f"rapid={best['pct_rapid']}%)")
    return target


# ══════════════════════════════════════════════════════════════════════════════
# SUB-CLUSTERING
# ══════════════════════════════════════════════════════════════════════════════

def extract_cluster_data(labels_raster, embeddings, velocity, target_cluster):
    """
    Extract embedding and velocity data for the target cluster.

    Returns
    -------
    emb_valid : np.ndarray
        Shape (n_valid, 64) — embedding features for valid target pixels.
    vel_valid : np.ndarray
        Shape (n_valid,) — velocity for valid target pixels.
    target_mask : np.ndarray
        Boolean (H, W) — which pixels belong to the target cluster.
    valid_within_target : np.ndarray
        Boolean (n_target,) — which target pixels have valid data.
    """
    target_mask = labels_raster == target_cluster
    target_emb = embeddings[:, target_mask].T      # (n_target, 64)
    target_vel = velocity[target_mask]              # (n_target,)

    valid = (~np.isnan(target_emb).any(axis=1)
             & ~np.isnan(target_vel)
             & (target_vel != 0))

    emb_valid = target_emb[valid]
    vel_valid = target_vel[valid]

    print(f"\nCluster {target_cluster}:")
    print(f"  Total pixels:   {target_mask.sum():,}")
    print(f"  Valid pixels:   {valid.sum():,}")
    print(f"  Velocity range: [{vel_valid.min():.1f}, "
          f"{vel_valid.max():.1f}] mm/yr")

    return emb_valid, vel_valid, target_mask, valid


def search_sub_k(emb_valid, vel_valid, k_range=None):
    """
    Test multiple sub-cluster counts on embedding features only.
    Reports silhouette scores and velocity stats per sub-cluster.

    Returns
    -------
    results : list of dict
        One entry per k with silhouette and sub-cluster stats.
    best_k : int
        k with highest silhouette score.
    """
    if k_range is None:
        k_range = SUB_K_RANGE

    rng = np.random.RandomState(RANDOM_STATE)
    n_sample = min(SUBCLUSTER_MAX_SAMPLES, len(emb_valid))
    idx = rng.choice(len(emb_valid), n_sample, replace=False)

    print("\n=== Sub-cluster k Search (embeddings only) ===\n")
    results = []

    for k in k_range:
        model = MiniBatchKMeans(
            n_clusters=k, random_state=RANDOM_STATE,
            batch_size=10_000, n_init=5,
        )
        model.fit(emb_valid[idx])
        sub_labels = model.predict(emb_valid)

        sil = silhouette_score(emb_valid[idx], model.predict(emb_valid[idx]))
        print(f"  k={k}: silhouette={sil:.4f}")

        sub_stats = []
        for sc in range(k):
            sc_vel = vel_valid[sub_labels == sc]
            stat = {
                "sub_cluster": sc,
                "n": len(sc_vel),
                "mean": float(sc_vel.mean()),
                "median": float(np.median(sc_vel)),
                "pct_below_neg25": float(
                    (sc_vel < -25).sum() / len(sc_vel) * 100
                ),
            }
            sub_stats.append(stat)
            print(f"    SC {sc}: n={stat['n']:,}, "
                  f"mean={stat['mean']:.1f}, "
                  f"pct<-25={stat['pct_below_neg25']:.1f}%")

        results.append({"k": k, "silhouette": sil, "sub_stats": sub_stats})

    best_k = max(results, key=lambda r: r["silhouette"])["k"]
    print(f"\n  Best k by silhouette: {best_k}")
    return results, best_k


def run_subclustering(emb_valid, vel_valid, k):
    """
    Run final sub-clustering at the chosen k.

    Sub-clusters are sorted by mean velocity (most negative first),
    so sub-cluster 0 = worst subsidence, sub-cluster k-1 = least.

    Returns
    -------
    sub_labels : np.ndarray
        Sub-cluster assignments (0 = worst subsidence).
    model : MiniBatchKMeans
    sorted_ids : list of int
        Original sub-cluster IDs sorted by severity (worst first).
    """
    rng = np.random.RandomState(RANDOM_STATE)
    n_sample = min(SUBCLUSTER_MAX_SAMPLES, len(emb_valid))
    idx = rng.choice(len(emb_valid), n_sample, replace=False)

    model = MiniBatchKMeans(
        n_clusters=k, random_state=RANDOM_STATE,
        batch_size=10_000, n_init=10,
    )
    model.fit(emb_valid[idx])
    raw_labels = model.predict(emb_valid)

    # Sort sub-clusters by mean velocity (most negative = worst = index 0)
    means = [vel_valid[raw_labels == sc].mean() for sc in range(k)]
    sorted_ids = list(np.argsort(means))  # ascending: most negative first

    # Remap labels so 0 = worst subsidence
    remap = {orig: new for new, orig in enumerate(sorted_ids)}
    sub_labels = np.array([remap[l] for l in raw_labels])

    print(f"\n=== Final Sub-clustering (k={k}) ===\n")
    for new_id in range(k):
        orig_id = sorted_ids[new_id]
        sc_vel = vel_valid[raw_labels == orig_id]
        label_char = chr(ord("A") + new_id)
        print(f"  Sub-cluster {label_char} "
              f"(new={new_id}, orig={orig_id}):")
        print(f"    n={len(sc_vel):,}, "
              f"mean={sc_vel.mean():.1f}, "
              f"median={np.median(sc_vel):.1f}")
        print(f"    Below -10: {(sc_vel < -10).sum():,} "
              f"({(sc_vel < -10).sum()/len(sc_vel)*100:.1f}%)")
        print(f"    Below -25: {(sc_vel < -25).sum():,} "
              f"({(sc_vel < -25).sum()/len(sc_vel)*100:.1f}%)")

    return sub_labels, model, sorted_ids


# ══════════════════════════════════════════════════════════════════════════════
# VISUALIZATION
# ══════════════════════════════════════════════════════════════════════════════

def plot_histograms(vel_valid, sub_labels, k, target_cluster, figures_dir):
    """Side-by-side velocity histograms per sub-cluster."""
    os.makedirs(figures_dir, exist_ok=True)

    n_cols = min(k, 3)
    n_rows = (k + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(7 * n_cols, 6 * n_rows),
                             sharey=True, squeeze=False)
    axes_flat = axes.flatten()

    colors = ["#c0392b", "#2980b9", "#27ae60", "#f39c12"]

    for sc in range(k):
        ax = axes_flat[sc]
        sc_vel = vel_valid[sub_labels == sc]
        label_char = chr(ord("A") + sc)
        color = colors[sc % len(colors)]

        ax.hist(sc_vel, bins=80, color=color, alpha=0.7, edgecolor="none")
        ax.axvline(x=-10, color="orange", linestyle="--", linewidth=1.5)
        ax.axvline(x=-25, color="red", linestyle="--", linewidth=1.5)
        ax.axvline(x=0, color="gray", linestyle="--", linewidth=0.8)
        ax.set_title(
            f"Sub-cluster {label_char}\n"
            f"mean={sc_vel.mean():.1f} mm/yr, n={len(sc_vel):,}",
            fontsize=12, fontweight="bold",
        )
        ax.set_xlabel("mm/yr")
        if sc % n_cols == 0:
            ax.set_ylabel("Pixel count")

    # Hide unused axes
    for i in range(k, len(axes_flat)):
        axes_flat[i].set_visible(False)

    plt.suptitle(
        f"Sub-clustering Cluster {target_cluster} (k={k})",
        fontsize=14, fontweight="bold",
    )
    plt.tight_layout()
    save_path = os.path.join(figures_dir, "subcluster_histograms.png")
    plt.savefig(save_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved: {save_path}")


def plot_spatial_map(labels_raster, target_cluster, target_mask,
                     valid_within_target, sub_labels, k,
                     cluster_risks, figures_dir):
    """
    Spatial map: non-target clusters at original IDs, target cluster
    split into sub-clusters with new IDs.
    """
    os.makedirs(figures_dir, exist_ok=True)

    all_cluster_ids = sorted(np.unique(labels_raster[labels_raster >= 0]))
    max_id = max(all_cluster_ids)

    # Build the refined raster
    refined = np.full_like(labels_raster, -1, dtype=np.int8)

    for c in all_cluster_ids:
        if c != target_cluster:
            refined[labels_raster == c] = c

    # Place sub-cluster labels at (max_id + 1), (max_id + 2), ...
    target_positions = np.where(target_mask)
    valid_positions = (
        target_positions[0][valid_within_target],
        target_positions[1][valid_within_target],
    )
    for sc in range(k):
        sc_mask = sub_labels == sc
        refined[
            valid_positions[0][sc_mask],
            valid_positions[1][sc_mask],
        ] = max_id + 1 + sc

    # Plot
    n_colors = max_id + 1 + k + 1
    # plt.cm.get_cmap(name, n) was removed in matplotlib 3.9; the colormap
    # registry + .resampled() is available from 3.6 onward.
    cmap = matplotlib.colormaps["tab10"].resampled(n_colors)
    masked = np.ma.masked_where(refined == -1, refined)

    fig, ax = plt.subplots(figsize=(14, 10))
    ax.imshow(masked, cmap=cmap, interpolation="nearest",
              vmin=0, vmax=n_colors - 1)

    # Build dynamic legend
    legend_elements = []
    for c in all_cluster_ids:
        if c != target_cluster:
            risk = cluster_risks.get(c, "?")
            legend_elements.append(
                Patch(facecolor=cmap(c), label=f"Cluster {c} ({risk})")
            )
    for sc in range(k):
        label_char = chr(ord("A") + sc)
        severity = "Severe" if sc == 0 else "Less Severe"
        legend_elements.append(
            Patch(
                facecolor=cmap(max_id + 1 + sc),
                label=f"Cluster {target_cluster}{label_char}: {severity}",
            )
        )

    ax.legend(handles=legend_elements, loc="lower right",
              fontsize=10, framealpha=0.9)
    ax.set_title(
        f"Land Cover Clusters with Cluster {target_cluster} Sub-divided",
        fontsize=14, fontweight="bold",
    )
    plt.tight_layout()
    save_path = os.path.join(figures_dir, "subcluster_map.png")
    plt.savefig(save_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved: {save_path}")

    return refined


def save_refined_raster(refined, profile, output_dir):
    """Save the refined cluster raster with sub-clusters."""
    os.makedirs(output_dir, exist_ok=True)
    profile_out = profile.copy()
    profile_out.update(dtype="int8", nodata=-1)
    output_path = os.path.join(output_dir, "refined_clusters.tif")
    with rasterio.open(output_path, "w", **profile_out) as dst:
        dst.write(refined[np.newaxis, :, :])
    print(f"Saved: {output_path}")
    return output_path


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main(state_path=None, target_cluster=None, sub_k=None):
    """
    Run the sub-cluster analysis.

    Parameters
    ----------
    state_path : str or None
        Path to pipeline_state.json. Defaults to data/output/.
    target_cluster : int or None
        Which cluster to sub-divide. Auto-selects highest-risk if None.
    sub_k : int or None
        Number of sub-clusters. Auto-selects via silhouette if None.
    """
    print("=" * 60)
    print("SUB-CLUSTER ANALYSIS")
    print("=" * 60)

    # ── Load pipeline state ──────────────────────────────────────────
    state = load_pipeline_state(state_path)
    paths = state["paths"]

    # ── Identify target cluster ──────────────────────────────────────
    target = identify_target_cluster(state, target_cluster)

    # Build cluster_id → risk_level lookup
    cluster_risks = {
        r["cluster"]: r["cluster_risk"]
        for r in state["risk_summary"]
    }

    # ── Load rasters ─────────────────────────────────────────────────
    print("\nLoading data...")

    label_path = paths["cluster_labels"]
    emb_path = paths["embeddings_norm"]
    vel_path = paths["velocity_for_overlay"]

    with rasterio.open(label_path) as src:
        labels_raster = src.read(1)
        profile = src.profile.copy()

    with rasterio.open(emb_path) as src:
        embeddings = src.read()

    with rasterio.open(vel_path) as src:
        velocity = src.read(1)

    # ── Extract target cluster data ──────────────────────────────────
    emb_valid, vel_valid, target_mask, valid_within = extract_cluster_data(
        labels_raster, embeddings, velocity, target,
    )

    # ── Search for optimal sub-k ─────────────────────────────────────
    search_results, best_k = search_sub_k(emb_valid, vel_valid)

    final_k = sub_k if sub_k is not None else best_k
    if sub_k is not None:
        print(f"\nUsing user-specified sub-k={sub_k} "
              f"(auto-selected was {best_k}).")

    # ── Run final sub-clustering ─────────────────────────────────────
    sub_labels, model, sorted_ids = run_subclustering(
        emb_valid, vel_valid, final_k,
    )

    # ── Visualize ────────────────────────────────────────────────────
    plot_histograms(vel_valid, sub_labels, final_k, target, OUT_FIGURES_DIR)

    refined = plot_spatial_map(
        labels_raster, target, target_mask, valid_within,
        sub_labels, final_k, cluster_risks, OUT_FIGURES_DIR,
    )

    # ── Save outputs ─────────────────────────────────────────────────
    save_refined_raster(refined, profile, OUT_CLUSTERS_DIR)

    print("\n" + "=" * 60)
    print("SUB-CLUSTER ANALYSIS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sub-cluster the highest-risk land cover cluster.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python subcluster_analysis.py                   "
            "# auto-select highest-risk cluster\n"
            "  python subcluster_analysis.py --cluster 2       "
            "# sub-divide cluster 2\n"
            "  python subcluster_analysis.py --sub-k 3         "
            "# force 3 sub-clusters\n"
        ),
    )
    parser.add_argument(
        "--state", type=str, default=None,
        help=f"Path to pipeline_state.json (default: {PIPELINE_STATE_FILE}).",
    )
    parser.add_argument(
        "--cluster", type=int, default=None,
        help="Target cluster to sub-divide. Auto-selects highest-risk if omitted.",
    )
    parser.add_argument(
        "--sub-k", type=int, default=None,
        help="Number of sub-clusters. Auto-selects via silhouette if omitted.",
    )
    args = parser.parse_args()
    main(
        state_path=args.state,
        target_cluster=args.cluster,
        sub_k=args.sub_k,
    )
