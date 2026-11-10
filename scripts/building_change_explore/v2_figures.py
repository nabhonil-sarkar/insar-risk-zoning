"""Inspection panels for v2, retaining native geometry and original cells."""
import argparse
import numpy as np
import rasterio
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as Patch
from shapely.geometry import box
from scripts.building_change_explore.v2 import OUT,read,target_polygon,polygons,compare_geometry,TO_LL
from pyproj import Proj


def draw_geometry(ax,geom,**kwargs):
    if geom.is_empty:return
    for part in getattr(geom,'geoms',[geom]):
        if part.geom_type=='Polygon':ax.add_patch(Patch(np.asarray(part.exterior.coords),**kwargs))


def sheet(sites,name,metrics):
    fig,axes=plt.subplots(len(sites),3,figsize=(10,2.7*len(sites)),squeeze=False)
    for i,s in enumerate(sites):
        with rasterio.open(OUT/'native_binary'/(s['id']+'.tif')) as ds:a=ds.read().reshape(2,3,512,512);t=ds.transform;b=ds.bounds
        cell=target_polygon(s);p0=polygons(a[0,0],t);p3=polygons(a[1,0],t)
        f=Proj('EPSG:32748').get_factors(*TO_LL.transform(s['x'],s['y']));radius=8*np.sqrt(f.meridional_scale*f.parallel_scale)
        _,growth,expanded,known=compare_geometry(p0,p3,polygons(a[0,2],t),polygons(a[1,2],t),box(*b),cell,radius)
        m=next(r for r in metrics if r['id']==s['id'] and r['threshold']==.41)
        for j in range(3):
            ax=axes[i,j]
            if j<2:ax.imshow(a[j,0],cmap='Greys',vmin=0,vmax=1,extent=[b.left,b.right,b.bottom,b.top],interpolation='nearest')
            else:
                draw_geometry(ax,p3,facecolor='#dddddd',edgecolor='none')
                draw_geometry(ax,expanded,facecolor='none',edgecolor='#d58a26',lw=.5)
                draw_geometry(ax,growth,facecolor='#1c8c65',edgecolor='none')
            draw_geometry(ax,cell,facecolor='none',edgecolor='#d93232',lw=1.1)
            ax.set_xlim(s['x']-70,s['x']+70);ax.set_ylim(s['y']-70,s['y']+70);ax.set_aspect('equal');ax.set_xticks([]);ax.set_yticks([])
            ax.set_title(['2020 thresholded footprint','2023 thresholded footprint',f"Beyond 8 m: {m['surviving_fraction']:.3f} of cell"][j],fontsize=10)
            if j==0:ax.set_ylabel(s['id'].replace('v2_',''),fontsize=8)
    fig.suptitle('Native reference footprints · red: frozen cell · orange: expanded 2020\nGreen: surviving 2023 footprint inside cell; reference consistency only',fontsize=11)
    fig.tight_layout(rect=[0,0,1,.96]);fig.savefig(OUT/(name+'.png'),dpi=125);plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['settlement','fresh']);a=p.parse_args()
    sites=read(a.phase+'_sites.json');metrics=read(a.phase+'_metrics.json')
    if a.phase=='settlement':sheet(sites,'settlement_examples',metrics)
    else:
        for sector in ['NW','W']:
            for group in ['addition','stable_built','stable_nonbuilt']:
                selected=[s for s in sites if s['sector']==sector and s['stratum'].startswith(group)]
                sheet(selected,f'fresh_{sector}_{group}',metrics)
