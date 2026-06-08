import rasterio
import numpy as np

with rasterio.open('data/raw/insar/jakarta_velocity_mmyr.tif') as src:
    vel = src.read(1)
    valid = vel[~np.isnan(vel)]
    valid = valid[valid != 0]
    print(f'Shape: {vel.shape}')
    print(f'Valid pixels: {len(valid)}')
    print(f'Min: {valid.min():.2f} mm/yr')
    print(f'Max: {valid.max():.2f} mm/yr')
    print(f'Mean: {valid.mean():.2f} mm/yr')
    print(f'Pixels below -10: {(valid < -10).sum()}')
    print(f'Pixels below -25: {(valid < -25).sum()}')
    print(f'Bounds: {src.bounds}')