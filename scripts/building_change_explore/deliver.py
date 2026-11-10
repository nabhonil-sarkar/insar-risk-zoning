"""Apply the recorded Day 1 rule and render exploratory figures."""
from datetime import datetime,timezone
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import numpy as np
from scripts.building_change_explore.analyse import OUT,labels


def main():
    review=json.loads((OUT/'reference_review.json').read_text())
    quality=json.loads((OUT/'reference_quality_counts.json').read_text())['summary']
    if not review['reference_usable']:
        decision={'decision':'STOP_INCONCLUSIVE','reason':'Reference-quality screen did not pass','reference_quality':review,'day2_started':False}
    else:
        metrics=json.loads((OUT/'enrichment_metrics.json').read_text())
        checks=[]
        for sector in ['NW','W']:
            q=next(x for x in quality if x['sector']==sector)
            spread=q['primary_additions']>=100 and q['blocks_ge3']>=10 and q['largest_block_share']<=.25
            for top,floor in [(1,2),(5,1.5)]:
                rows=[x for x in metrics if x['sector']==sector and x['surface']=='combined' and x['period']=='2020-2023' and x['top_percent']==top]
                mainrow=next(x for x in rows if x['threshold']==.41 and x['rule']=='endpoint')
                sensitivities=[x for x in rows if x['rule']!='endpoint_common_2021_support' and (x['threshold']!=.41 or x['rule']!='endpoint')]
                practical=mainrow['enrichment'] is not None and mainrow['enrichment']>=floor
                robust=all(x['enrichment'] is not None and x['enrichment']>1 and x['addition_cells']>=50 and x['blocks']>=5 for x in sensitivities)
                leaveout=mainrow['leave_one_addition_block_out_min_enrichment'] is not None and mainrow['leave_one_addition_block_out_min_enrichment']>1
                checks.append({'sector':sector,'top_percent':top,'spread_pass':spread,'practical_enrichment_pass':practical,'sensitivity_pass':robust,'leave_one_block_out_pass':leaveout})
        if all(all(r[k] for k in ['spread_pass','practical_enrichment_pass','sensitivity_pass','leave_one_block_out_pass']) for r in checks):status='RECOMMEND_CONTINUE'
        elif not all(r['spread_pass'] for r in checks):status='STOP_INCONCLUSIVE'
        elif not all(r['practical_enrichment_pass'] for r in checks):status='STOP_OVERLAP_FINDING'
        else:status='STOP_INCONCLUSIVE'
        decision={'decision':status,'rule_checks':checks,'reference_quality_pass':True,'interpretation':'Co-location between reference-indicated additions and embedding differences; neither independent ground validation nor causal attribution. Water-labelled additions are not established reclamation.','day2_started':False,'later_work_requires_separate_assignment':True}
        plot_enrichment(metrics)
        plot_map()
    decision['decided_utc']=datetime.now(timezone.utc).isoformat()
    with (OUT/'day1_decision.json').open('x') as f:json.dump(decision,f,indent=2)
    print(json.dumps(decision,indent=2))


def plot_enrichment(metrics):
    fig,axes=plt.subplots(1,2,figsize=(12,6),sharey=True)
    groups=[('NW',1),('NW',5),('W',1),('W',5)]
    colors={'combined':'#222222','land':'#a86721','water':'#2675ac'}
    for ax,end in zip(axes,[2023,2025]):
        for index,(sector,top) in enumerate(groups):
            for offset,surface in zip([-.2,0,.2],['combined','land','water']):
                rows=[x for x in metrics if x['sector']==sector and x['surface']==surface and x['period']==f'2020-{end}' and x['top_percent']==top and x['rule']!='endpoint_common_2021_support']
                main=next(x for x in rows if x['threshold']==.41 and x['rule']=='endpoint');v=main['enrichment']
                bounds=[r['enrichment'] for r in rows if r['enrichment'] is not None and r['enrichment']>0]
                y=index+offset
                if v is not None and v>0:
                    ax.plot([min(bounds),max(bounds)],[y,y],color=colors[surface],alpha=.45,linewidth=2)
                    ax.scatter(v,y,c=colors[surface],s=36,label=surface if index==0 else None,zorder=3)
        ax.axvline(1,color='#888888',ls='--',lw=1);ax.set_xscale('log');ax.set_xlabel('Addition enrichment ratio (log scale)');ax.grid(axis='x',alpha=.2)
        ax.set_title(f'2020–{end} embedding difference'+('\nPrimary period' if end==2023 else '\nSecondary period'))
    axes[0].set_yticks(range(4),[f'{s} · top {t}%' for s,t in groups]);axes[0].invert_yaxis();axes[1].legend(title='2020 baseline surface',loc='best')
    fig.suptitle('Do reference-indicated additions co-locate with extreme embedding differences?',fontsize=14)
    fig.text(.5,.015,'Dots: presence ≥0.41 and endpoint additions. Lines: threshold / 2021-persistence sensitivity range, not confidence intervals.\nRankings fixed across the full valid rectangle. Eligible denominators vary with reference exclusions.',ha='center',fontsize=9)
    fig.tight_layout(rect=[0,.075,1,.94]);fig.savefig(OUT/'enrichment.png',dpi=180);plt.close(fig)


def plot_map():
    local=np.load(OUT/'local_arrays.npz');ref=np.load(OUT/'reference_fractions.npy');_,v,lo,hi,amb=labels(ref)
    eligible=(lo[0]|hi[0])&(lo[3]|hi[3])&local['inside'];addition=lo[0]&hi[3]&eligible
    grid=json.loads((OUT/'input_verification.json').read_text())['grid'];t=grid['transform'];extent=[t[2],t[2]+953*t[0],t[5]+1312*t[4],t[5]]
    fig,axes=plt.subplots(1,2,figsize=(9,10),sharey=True)
    cmap=ListedColormap(['#eeeeee','#c7ddeb','#555555','#ed9b37','#5476bc','#9b2b80'])
    for ax,end in zip(axes,[2023,2025]):
        a=np.where(local['cover']==80,1,0);a[~eligible]=2
        hot=local[f'hot_{end}_1']&eligible
        a[hot]=3;a[addition]=4;a[hot&addition]=5
        ax.imshow(a,cmap=cmap,vmin=0,vmax=5,extent=extent,interpolation='nearest')
        ax.axhline(t[5]+656*t[4],color='white',lw=1.2)
        ax.set_title(f'2020–{end} · top 1%');ax.set_xlabel('Longitude');ax.text(extent[0]+.01,t[5]-.025,'NW',weight='bold');ax.text(extent[0]+.01,t[5]+656*t[4]-.025,'W',weight='bold')
    axes[0].set_ylabel('Latitude')
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(facecolor=c,label=l) for c,l in zip(cmap.colors,['Baseline land','Baseline water','Missing / ambiguous','Extreme only','Addition only','Both'])],loc='lower center',ncol=3,frameon=False)
    fig.suptitle('Deliberately selected pilot sectors\nReference-indicated 2020–2023 additions and embedding extremes')
    fig.tight_layout(rect=[0,.07,1,.93]);fig.savefig(OUT/'colocation_map.png',dpi=180);plt.close(fig)


if __name__=='__main__':main()
