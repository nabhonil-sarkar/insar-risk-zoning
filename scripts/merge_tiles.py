import shutil, os

src = 'data/raw/embeddings/AlphaEarth_Jakarta_2023-0000000000-0000000000.tif'
dst = 'data/raw/embeddings/AlphaEarth_Jakarta_2023_merged.tif'

shutil.copy(src, dst)
print(f'Copied main tile as: {dst}')
print(f'Size: {os.path.getsize(dst) / 1e6:.0f} MB')