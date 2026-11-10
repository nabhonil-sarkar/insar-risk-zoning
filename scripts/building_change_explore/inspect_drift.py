"""Reference-only cell-edge sensitivity; does not correct or rerank study maps."""
import json
import numpy as np
import rasterio
from rasterio.transform import Affine
from pyproj import Transformer
from shapely.geometry import Polygon,box
from scipy.ndimage import shift
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as PlotPolygon
from matplotlib.colors import ListedColormap
from scripts.building_change_explore.analyse import OUT


def main():
    samples=json.loads((OUT/'reference_sample.json').read_text());diag=json.loads((OUT/'inspection_diagnostics.json').read_text())
    t=Affine(*json.loads((OUT/'input_verification.json').read_text())['grid']['transform'])
    utm=Transformer.from_crs(4326,32748,always_xy=True);records=[]
    adds=[s for s in samples if s['stratum']=='addition'];fig,axes=plt.subplots(len(adds),3,figsize=(10,3*len(adds)),squeeze=False)
    for i,s in enumerate(adds):
        with rasterio.open(OUT/'inspection_windows'/(s['id']+'.tif')) as ds:a=ds.read().reshape(4,3,77,77);native=ds.transform;b=ds.bounds
        corners=[t*(s['col'],s['row']),t*(s['col']+1,s['row']),t*(s['col']+1,s['row']+1),t*(s['col'],s['row']+1)]
        corners=np.array([utm.transform(*p) for p in corners]);poly=Polygon(corners)
        weights=np.zeros((77,77))
        for r in range(77):
            for c in range(77):
                left,top=native*(c,r);right,bottom=native*(c+1,r+1)
                if right<poly.bounds[0] or left>poly.bounds[2] or top<poly.bounds[1] or bottom>poly.bounds[3]:continue
                weights[r,c]=poly.intersection(box(left,bottom,right,top)).area/poly.area
        assert abs(weights.sum()-1)<1e-6
        d=next(z for z in diag if z['id']==s['id']);dx,dy=d['best_shift_m'];aligned=shift(a[3,0],(-dy/4,dx/4),order=0,cval=0)
        cov0=float((weights*a[0,0]).sum());cov3=float((weights*a[3,0]).sum());covshift=float((weights*aligned).sum())
        shifted=[]
        for xx,yy in [(4,0),(-4,0),(0,4),(0,-4)]:
            cov=float((weights*shift(a[3,0],(-yy/4,xx/4),order=0,cval=0)).sum());shifted.append({'shift_m':[xx,yy],'coverage':cov})
        record={'id':s['id'],'native_target_coverage_2020':s['coverage_041'][0],'native_target_coverage_2023':s['coverage_041'][3],'approx_4m_coverage_2020':cov0,'approx_4m_coverage_2023':cov3,'observed_patch_alignment_shift_m':[dx,dy],'approx_4m_aligned_2023_coverage':covshift,'gain_removed_fraction_by_alignment':(cov3-covshift)/(cov3-cov0) if cov3>cov0 else None,'four_metre_cardinal_sensitivities':shifted,'limitation':'4 m aggregated fractions introduce cell-edge approximation. Alignment is a diagnostic selected from this reference patch, not a validated geolocation correction or new addition definition.'}
        records.append(record)
        base=a[0,0]>.5;last=a[3,0]>.5;after=aligned>.5
        for j,(candidate,title) in enumerate([(last,'2020 vs 2023'),(after,f'After diagnostic shift {dx},{dy} m')]):
            colors=np.where(base,1,0);colors[candidate&~base]=2;colors[base&~candidate]=3
            ax=axes[i,j];ax.imshow(colors,cmap=ListedColormap(['white','#555555','#1674c7','#e99827']),vmin=0,vmax=3,extent=[b.left,b.right,b.bottom,b.top]);ax.add_patch(PlotPolygon(corners,fill=False,edgecolor='red',lw=1));ax.set_title(title,fontsize=10);ax.set_xticks([]);ax.set_yticks([])
            if j==0:ax.set_ylabel(s['id'])
        ax=axes[i,2];ax.bar(['2020','2023','Shifted\n2023'],[cov0,cov3,covshift],color=['#777777','#1674c7','#68a6d8']);ax.axhline(.4,ls='--',color='black',lw=1);ax.axhline(.1,ls=':',color='black',lw=1);ax.set_ylim(0,.7);ax.set_title('Approximate cell coverage',fontsize=10)
    fig.suptitle('Reference-only drift diagnostic for all six selected addition cells\nGray: overlap; blue: gain; orange: loss; red: frozen cell',fontsize=13)
    fig.text(.5,.01,'No study map was shifted. Patch alignment is diagnostic, not a validated correction; 4 m cell-edge integration is approximate.',ha='center',fontsize=9)
    fig.tight_layout(rect=[0,.025,1,.96]);fig.savefig(OUT/'addition_drift_diagnostic.png',dpi=140);plt.close(fig)
    (OUT/'addition_drift_diagnostic.json').write_text(json.dumps(records,indent=2)+'\n');print(json.dumps(records,indent=2))


if __name__=='__main__':main()
