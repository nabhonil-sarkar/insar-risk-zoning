"""Reference counts and support-only figures when the quality gate fails.

Never intersects addition labels with embedding extremes or computes enrichment.
"""
import csv
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scripts.building_change_explore.analyse import OUT, labels, block_counts, write


def save_rows(name, rows):
    write(name+'.json', rows)
    with (OUT/(name+'.csv')).open('x', newline='') as f:
        writer=csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def main():
    assert not json.loads((OUT/'reference_review.json').read_text())['reference_usable']
    assert not (OUT/'enrichment_metrics.json').exists()
    local=np.load(OUT/'local_arrays.npz');ref=np.load(OUT/'reference_fractions.npy')
    reference=[];support=[]
    for ti, threshold in enumerate([.41,.34]):
        _,valid,low,high,ambiguous=labels(ref,ti)
        endpoint=valid[0]&valid[3]
        clear=(low[0]|high[0])&(low[3]|high[3])
        for sid, sector in [(0,'NW'),(3,'W')]:
            for surface in ['combined','land','water']:
                geo=local['inside']&(local['sectors']==sid)
                if surface!='combined':geo &= (local['cover']==80) if surface=='water' else (local['cover']!=80)
                for rule in ['endpoint','persistence_2021_low','endpoint_common_2021_support']:
                    eligible=clear.copy();addition=low[0]&high[3]
                    if rule!='endpoint':eligible &=low[1]|high[1];addition &=eligible
                    if rule=='persistence_2021_low':addition &=low[1]
                    missing21=geo&clear&~valid[1] if rule!='endpoint' else np.zeros_like(geo)
                    amb21=geo&clear&ambiguous[1] if rule!='endpoint' else np.zeros_like(geo)
                    e=int((geo&eligible).sum());a=int((geo&addition).sum())
                    row=dict(threshold=threshold,rule=rule,sector=sector,surface=surface,
                             baseline_cells=int(geo.sum()),eligible_cells=e,
                             endpoint_missing_support=int((geo&~endpoint).sum()),
                             endpoint_ambiguous=int((geo&endpoint&~clear).sum()),
                             additional_2021_missing_support=int(missing21.sum()),
                             additional_2021_ambiguous=int(amb21.sum()),
                             candidate_addition_cells=a,candidate_prevalence=a/e if e else None,
                             usable_addition_cells=None,**block_counts(geo&addition,local),
                             status='candidate_labels_only_reference_quality_gate_failed')
                    assert row['baseline_cells']==e+sum(row[k] for k in ['endpoint_missing_support','endpoint_ambiguous','additional_2021_missing_support','additional_2021_ambiguous'])
                    reference.append(row)
                    for end in [2023,2025]:
                        for top in [1,5]:
                            extreme=geo&local[f'hot_{end}_{top}']
                            s=dict(threshold=threshold,rule=rule,sector=sector,surface=surface,
                                   period=f'2020-{end}',top_percent=top,
                                   original_extreme_cells=int(extreme.sum()),
                                   eligible_extreme_cells=int((extreme&eligible).sum()),
                                   extremes_missing_support=int((extreme&~endpoint).sum()),
                                   extremes_ambiguous=int((extreme&endpoint&~clear).sum()),
                                   additional_2021_extremes_missing_support=int((extreme&missing21).sum()),
                                   additional_2021_extremes_ambiguous=int((extreme&amb21).sum()),
                                   addition_extreme_cells=None,extreme_addition_prevalence=None,
                                   enrichment=None,addition_capture_fraction=None,
                                   status='support_only_enrichment_not_computed_reference_quality_gate')
                            assert s['original_extreme_cells']==sum(s[k] for k in ['eligible_extreme_cells','extremes_missing_support','extremes_ambiguous','additional_2021_extremes_missing_support','additional_2021_extremes_ambiguous'])
                            support.append(s)
    save_rows('reference_candidate_metrics',reference)
    save_rows('extreme_support_only',support)
    drift=json.loads((OUT/'addition_drift_diagnostic.json').read_text())
    fig,ax=plt.subplots(figsize=(10,5.1));x=np.arange(len(drift));width=.24
    for offset,key,label,color in [(-1,'approx_4m_coverage_2020','2020','#888888'),(0,'approx_4m_coverage_2023','2023','#176da2'),(1,'approx_4m_aligned_2023_coverage','2023 after diagnostic alignment','#e09836')]:
        values=[d[key] for d in drift]
        bars=ax.bar(x+offset*width,values,width,label=label,color=color)
        ax.bar_label(bars,labels=[f'{v:.2f}' for v in values],fontsize=8,padding=3)
    ax.axhline(.4,color='#333333',ls='--',lw=1);ax.text(5.65,.405,'High: 0.40',ha='right',fontsize=9)
    ax.axhline(.1,color='#555555',ls=':',lw=1)
    ax.set_xticks(x,[d['id'].replace('_addition_',' / ')+'\n'+str(abs(d['observed_patch_alignment_shift_m'][1]))+' m south' for d in drift])
    ax.set_ylabel('Approximate building-covered fraction of frozen cell')
    ax.set_ylim(0,.66);ax.legend(loc='upper left',frameon=False,fontsize=9)
    ax.set_title('Five of six selected addition-cell labels are sensitive to drift',loc='left',pad=15)
    fig.text(.08,.025,'Reference-only development sample. Alignment is diagnostic, not a validated correction.\n4 m aggregation makes cell-edge integration approximate; study arrays were not shifted.',fontsize=9)
    fig.tight_layout(rect=[0,.10,1,1]);fig.savefig(OUT/'drift_summary.png',dpi=160);plt.close(fig)
    selected=[r for r in support if r['threshold']==.41 and r['rule']=='endpoint' and r['sector']=='NW' and r['period']=='2020-2025' and r['top_percent']==1 and r['surface']!='combined']
    fig,ax=plt.subplots(figsize=(9,4.7));positions=np.arange(2)
    eligible=np.array([r['eligible_extreme_cells'] for r in selected]);amb=np.array([r['extremes_ambiguous'] for r in selected])
    b=ax.barh(positions,eligible,color='#176da2',label='Endpoint labels unambiguous')
    ax.bar_label(b,labels=[f'{v:,}' for v in eligible],label_type='center',color='white')
    b=ax.barh(positions,amb,left=eligible,color='#e09836',label='Endpoint coverage ambiguous')
    ax.bar_label(b,labels=[f'{v:,}' for v in amb],label_type='center',color='#222222')
    ax.set_yticks(positions,[r['surface'].capitalize()+f" ({r['original_extreme_cells']:,})" for r in selected]);ax.invert_yaxis()
    ax.set_xlabel('Original extreme cells, before reference exclusions');ax.set_xlim(0,12000)
    ax.set_title('Original northwest 2020–2025 top 1%: land, water and eligibility',loc='left',pad=16)
    ax.legend(loc='upper center',bbox_to_anchor=(.5,-.18),ncol=2,frameon=False)
    fig.text(.05,.025,'18,096 original cells: 10,799 baseline land and 7,297 baseline water.\nMissing reference support excludes zero cells. This figure contains no addition-overlap result.',fontsize=9)
    fig.tight_layout(rect=[0,.15,1,1]);fig.savefig(OUT/'northwest_extreme_support.png',dpi=160);plt.close(fig)
    print(json.dumps(selected,indent=2))


if __name__=='__main__':main()
