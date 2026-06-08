import rasterio
import numpy as np

with rasterio.open('data/raw/insar/jakarta_velocity_mmyr.tif') as src:
    vel = src.read(1)
    transform = src.transform

    rows, cols = np.where(vel < -10)
    
    lons = []
    lats = []
    for r, c in zip(rows, cols):
        lon, lat = rasterio.transform.xy(transform, r, c)
        lons.append(lon)
        lats.append(lat)
    
    lons = np.array(lons)
    lats = np.array(lats)

    # Focus on Jakarta area (rough filter)
    jakarta = ((lons >= 106.5) & (lons <= 107.2) & 
               (lats >= -6.5) & (lats <= -5.8))
    
    jk_lons = lons[jakarta]
    jk_lats = lats[jakarta]
    jk_vals = vel[rows[jakarta], cols[jakarta]]
    
    print(f"Subsidence pixels (<-10) in Jakarta area: {jakarta.sum()}")
    print(f"  Lon range: {jk_lons.min():.3f} to {jk_lons.max():.3f}")
    print(f"  Lat range: {jk_lats.min():.3f} to {jk_lats.max():.3f}")
    print(f"  Velocity range: {jk_vals.min():.1f} to {jk_vals.max():.1f} mm/yr")
    
    # Suggest ROI with padding
    pad = 0.05
    roi = [
        round(jk_lons.min() - pad, 2),
        round(jk_lats.min() - pad, 2),
        round(jk_lons.max() + pad, 2),
        round(jk_lats.max() + pad, 2)
    ]
    print(f"\nRecommended embedding ROI: {roi}")
    
    width_km = (roi[2] - roi[0]) * 111
    height_km = (roi[3] - roi[1]) * 111
    print(f"Approximate size: {width_km:.0f} x {height_km:.0f} km")