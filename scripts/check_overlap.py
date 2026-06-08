import rasterio
import numpy as np

with rasterio.open('data/raw/insar/jakarta_velocity_mmyr.tif') as src:
    vel = src.read(1)
    transform = src.transform

    # Find pixels with strong subsidence
    rows, cols = np.where(vel < -25)
    
    print(f"Pixels below -25 mm/yr: {len(rows)}")
    print(f"\nSubsidence hotspot locations:")
    
    lons = []
    lats = []
    for r, c in zip(rows, cols):
        lon, lat = rasterio.transform.xy(transform, r, c)
        lons.append(lon)
        lats.append(lat)
    
    lons = np.array(lons)
    lats = np.array(lats)
    
    print(f"  Lon range: {lons.min():.3f} to {lons.max():.3f}")
    print(f"  Lat range: {lats.min():.3f} to {lats.max():.3f}")
    
    # Check overlap with embedding ROI
    emb_lon_min, emb_lon_max = 106.65, 106.95
    emb_lat_min, emb_lat_max = -6.35, -6.10
    
    in_roi = ((lons >= emb_lon_min) & (lons <= emb_lon_max) & 
              (lats >= emb_lat_min) & (lats <= emb_lat_max))
    
    print(f"\nEmbedding ROI: lon [{emb_lon_min}, {emb_lon_max}], lat [{emb_lat_min}, {emb_lat_max}]")
    print(f"Subsidence pixels inside ROI: {in_roi.sum()} / {len(rows)}")
    
    if in_roi.sum() == 0:
        print("\n*** NONE of the strong subsidence falls in the embedding area! ***")
        print("We need to re-export embeddings covering the subsidence zone.")
        print(f"\nSuggested new ROI: [{lons.min():.2f}, {lats.min():.2f}, {lons.max():.2f}, {lats.max():.2f}]")