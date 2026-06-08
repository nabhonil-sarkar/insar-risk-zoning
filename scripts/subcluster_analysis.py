"""
Phase 4: Sub-cluster Cluster 0 to separate the bimodal
velocity distribution into distinct sub-populations.
"""

import numpy as np
import rasterio
import matplotlib.pyplot as plt
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import silhouette_score
import os


def main():
    print("Starting Phase 4...")

    # Load data
    with rasterio.open('data/output/clusters/landcover_clusters_kmeans_k4.tif') as src:
        labels_raster = src.read(1)
        profile = src.profile.copy()

    with rasterio.open('data/processed/embeddings/AlphaEarth_Jakarta_Wide_30m_2023_norm.tif') as src:
        embeddings = src.read()

    with rasterio.open('data/processed/fused/velocity_aligned.tif') as src:
        velocity = src.read(1)

    # Extract Cluster 0 pixels
    c0_mask = labels_raster == 0
    c0_embeddings = embeddings[:, c0_mask].T
    c0_velocity = velocity[c0_mask]

    valid = ~np.isnan(c0_embeddings).any(axis=1) & ~np.isnan(c0_velocity) & (c0_velocity != 0)
    c0_emb_valid = c0_embeddings[valid]
    c0_vel_valid = c0_velocity[valid]

    print(f"Cluster 0 pixels: {c0_mask.sum():,}")
    print(f"Valid for sub-clustering: {valid.sum():,}")
    print(f"Velocity range: [{c0_vel_valid.min():.1f}, {c0_vel_valid.max():.1f}] mm/yr\n")

    os.makedirs('data/output/figures', exist_ok=True)

    # Subsample for speed
    rng = np.random.RandomState(42)
    n_sample = min(200_000, len(c0_emb_valid))
    idx = rng.choice(len(c0_emb_valid), n_sample, replace=False)

    # Test k=2, 3, 4
    print("=== Testing Sub-cluster Counts ===\n")
    for k in [2, 3, 4]:
        model = MiniBatchKMeans(n_clusters=k, random_state=42, batch_size=10_000, n_init=5)
        model.fit(c0_emb_valid[idx])
        sub_labels = model.predict(c0_emb_valid)

        sil = silhouette_score(c0_emb_valid[idx], model.predict(c0_emb_valid[idx]))
        print(f"  k={k}: silhouette={sil:.4f}")

        for sc in range(k):
            sc_vel = c0_vel_valid[sub_labels == sc]
            print(f"    Sub-cluster {sc}: n={len(sc_vel):,}, "
                  f"mean={sc_vel.mean():.1f}, median={np.median(sc_vel):.1f}, "
                  f"pct<-25={((sc_vel < -25).sum() / len(sc_vel) * 100):.1f}%")
        print()

    # Final sub-clustering with k=2
    print("=== Running Final k=2 Sub-clustering ===\n")
    model = MiniBatchKMeans(n_clusters=2, random_state=42, batch_size=10_000, n_init=10)
    model.fit(c0_emb_valid[idx])
    sub_labels = model.predict(c0_emb_valid)

    # Identify which sub-cluster has worse subsidence
    means = [c0_vel_valid[sub_labels == sc].mean() for sc in [0, 1]]
    worse_id = np.argmin(means)
    better_id = 1 - worse_id

    sc_a = c0_vel_valid[sub_labels == worse_id]
    sc_b = c0_vel_valid[sub_labels == better_id]

    print(f"  Sub-cluster A (worse subsidence, id={worse_id}):")
    print(f"    n={len(sc_a):,}, mean={sc_a.mean():.1f}, median={np.median(sc_a):.1f}")
    print(f"    Below -10: {(sc_a < -10).sum():,} ({(sc_a < -10).sum()/len(sc_a)*100:.1f}%)")
    print(f"    Below -25: {(sc_a < -25).sum():,} ({(sc_a < -25).sum()/len(sc_a)*100:.1f}%)")

    print(f"\n  Sub-cluster B (less subsidence, id={better_id}):")
    print(f"    n={len(sc_b):,}, mean={sc_b.mean():.1f}, median={np.median(sc_b):.1f}")
    print(f"    Below -10: {(sc_b < -10).sum():,} ({(sc_b < -10).sum()/len(sc_b)*100:.1f}%)")
    print(f"    Below -25: {(sc_b < -25).sum():,} ({(sc_b < -25).sum()/len(sc_b)*100:.1f}%)")

    # 1. Side-by-side histograms
    fig, axes = plt.subplots(1, 2, figsize=(16, 6), sharey=True)

    axes[0].hist(sc_a, bins=80, color='#c0392b', alpha=0.7, edgecolor='none')
    axes[0].axvline(x=-10, color='orange', linestyle='--', linewidth=1.5)
    axes[0].axvline(x=-25, color='red', linestyle='--', linewidth=1.5)
    axes[0].axvline(x=0, color='gray', linestyle='--', linewidth=0.8)
    axes[0].set_title(f'Sub-cluster A: Severe Subsidence\n'
                      f'mean={sc_a.mean():.1f} mm/yr, n={len(sc_a):,}',
                      fontsize=12, fontweight='bold')
    axes[0].set_xlabel('mm/yr')
    axes[0].set_ylabel('Pixel count')

    axes[1].hist(sc_b, bins=80, color='#2980b9', alpha=0.7, edgecolor='none')
    axes[1].axvline(x=-10, color='orange', linestyle='--', linewidth=1.5)
    axes[1].axvline(x=-25, color='red', linestyle='--', linewidth=1.5)
    axes[1].axvline(x=0, color='gray', linestyle='--', linewidth=0.8)
    axes[1].set_title(f'Sub-cluster B: Less Severe\n'
                      f'mean={sc_b.mean():.1f} mm/yr, n={len(sc_b):,}',
                      fontsize=12, fontweight='bold')
    axes[1].set_xlabel('mm/yr')

    plt.suptitle('Phase 4: Sub-clustering Cluster 0', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('data/output/figures/subcluster_histograms.png', dpi=200, bbox_inches='tight')
    plt.close()
    print("\nSaved: subcluster_histograms.png")

    # 2. Spatial map
    subcluster_raster = np.full_like(labels_raster, -1, dtype=np.int8)

    c0_positions = np.where(c0_mask)
    valid_positions = (c0_positions[0][valid], c0_positions[1][valid])

    subcluster_raster[valid_positions] = np.where(
        sub_labels == worse_id, 5, 6
    )

    for c in [1, 2, 3]:
        subcluster_raster[labels_raster == c] = c

    fig, ax = plt.subplots(figsize=(14, 10))
    cmap = plt.cm.get_cmap('tab10', 7)
    masked = np.ma.masked_where(subcluster_raster == -1, subcluster_raster)
    im = ax.imshow(masked, cmap=cmap, interpolation='nearest', vmin=0, vmax=6)

    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=cmap(1), label='Cluster 1'),
        Patch(facecolor=cmap(2), label='Cluster 2'),
        Patch(facecolor=cmap(3), label='Cluster 3'),
        Patch(facecolor=cmap(5), label='Cluster 0A: Severe Subsidence'),
        Patch(facecolor=cmap(6), label='Cluster 0B: Less Severe'),
    ]
    ax.legend(handles=legend_elements, loc='lower right', fontsize=10, framealpha=0.9)
    ax.set_title('Land Cover Clusters with Cluster 0 Sub-divided', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('data/output/figures/subcluster_map.png', dpi=200, bbox_inches='tight')
    plt.close()
    print("Saved: subcluster_map.png")

    # 3. Save refined raster
    profile.update(dtype='int8', nodata=-1)
    with rasterio.open('data/output/clusters/refined_clusters.tif', 'w', **profile) as dst:
        dst.write(subcluster_raster[np.newaxis, :, :])
    print("Saved: refined_clusters.tif")

    print("\n=== Phase 4 Complete ===")


if __name__ == "__main__":
    main()