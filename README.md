# InSAR-Informed Subsidence Risk Zoning

Unsupervised discovery of subsidence risk zones by fusing **InSAR displacement data** with **Google AlphaEarth Satellite Embeddings**.

## Overview

This project combines two views of the Earth's surface:

- **InSAR (Interferometric SAR):** measures *how fast the ground is moving* (mm/year subsidence velocity from Sentinel-1).
- **AlphaEarth Embeddings:** encode *what's on the surface* — 64-dimensional learned representations of land cover, vegetation phenology, and built environment from Google DeepMind's embedding model at 10m resolution.

Unsupervised clustering on the fused feature space discovers meaningful risk zones (e.g., rapidly-subsiding dense urban, slowly-subsiding wetland, stable elevated terrain) without any labeled training data.

## Study Area

**Jakarta, Indonesia** — one of the fastest-sinking cities in the world, with parts of North Jakarta subsiding up to 25 cm/year due to groundwater extraction.

## Pipeline Architecture

```
M1 InSAR Ingestion → M2 Embedding Extraction → M3 Feature Fusion → M4 Clustering → M5 Risk Interpretation
```

| Module | File | Purpose |
|--------|------|---------|
| Config | `config/settings.py` | Centralized parameters |
| M1 | `src/m1_insar_ingestion.py` | Load & preprocess InSAR velocity maps |
| M2 | `src/m2_embedding_extraction.py` | Load & normalize AlphaEarth embeddings |
| M3 | `src/m3_feature_fusion.py` | Align grids, normalize, concatenate |
| M4 | `src/m4_clustering.py` | K-Means, GMM, HDBSCAN + evaluation |
| M5 | `src/m5_risk_interpretation.py` | Cluster profiling, risk maps, reports |

## Quick Start

```bash
# 1. Clone and install
git clone <repo-url>
cd insar-risk-zoning
pip install -r requirements.txt

# 2. Authenticate with Earth Engine (once)
earthengine authenticate

# 3. Export embeddings from GEE to Google Drive
python scripts/export_embeddings.py

# 4. Download GeoTIFFs from Drive to data/raw/embeddings/

# 5. Run the full pipeline (uses synthetic InSAR data by default)
python scripts/run_full_pipeline.py
```

## Data Sources

- **AlphaEarth Satellite Embeddings:** `GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL` via Google Earth Engine (CC-BY 4.0)
- **InSAR Displacement:** Sentinel-1 via ASF HyP3, COMET-LiCS, or EGMS
- **Ancillary:** OpenStreetMap, Copernicus DEM, JRC Global Surface Water

## Outputs

- Cluster label raster (GeoTIFF)
- Risk zone map (GeoTIFF + GeoPackage)
- Cluster profile summaries
- Analysis report
- Visualization figures

## License

MIT
