"""Fixed pilot coverage, area and persistence outputs; no network access."""

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from pyproj import Geod, Transformer

from scripts import coastal_pilot_rules as rules
from scripts.coastal_transport import GateError
from scripts.run_alphaearth_surface_type import write_new

SCENARIOS=[(c,b) for c in (-.05,0.,.05) for b in (60,120)]


def scenario_id(c,b):
    return f'centre_{c:+.2f}_buffer_{b}'


def fraction_gate(n,den,minimum):
    return bool(den>0 and n/den>=minimum)


def cell_areas(bounds):
    left,bottom,right,top=bounds
    if right-left!=1000 or top-bottom!=1000:raise GateError('Nonregistered core area')
    tr=Transformer.from_crs(32748,4326,always_xy=True);geod=Geod(ellps='WGS84')
    a=np.zeros((50,50))
    for row,col in np.ndindex(a.shape):
        x=left+20*col;y=top-20*row
        lon,lat=tr.transform([x,x+20,x+20,x],[y,y,y-20,y-20])
        a[row,col]=abs(geod.polygon_area_perimeter(lon,lat)[0])
    if not np.isfinite(a).all() or (a<=0).any():raise GateError('Invalid geodesic area')
    return a


def coverage_batch(dates, observations, windows):
    """Only clear support computed here; no spectral state or transitions."""
    from scipy import ndimage
    rows=[];arrays={}
    if len(dates)!=8:raise GateError('Seasonal selected-date count changed')
    for w in windows:
        wid=w['id'];observed=observations[wid]
        if len(observed)!=8:raise GateError('Incomplete season')
        for buffer in (60,120):
            clear=[]
            for a in observed:
                g,s,q=(a[k] for k in ('B03','B11','SCL'))
                if g.shape!=(66,66) or s.shape!=g.shape or q.shape!=g.shape or not np.isin(q,range(12)).all():
                    raise GateError('Invalid aligned coverage arrays')
                radius=buffer//20;yy,xx=np.ogrid[-radius:radius+1,-radius:radius+1]
                masked=ndimage.binary_dilation(np.isin(q,[2,3,8,9,10]),structure=xx*xx+yy*yy<=radius*radius)
                clear.append((np.isin(q,[4,5,6]) & ~masked & np.isfinite(g) & np.isfinite(s))[8:-8,8:-8])
            clear=np.stack(clear)
            support,_=rules.season_state(dates,clear,np.full(clear.shape,-1,dtype=np.int8))
            counts=clear.sum(axis=0)
            ordinals=np.array(dates,dtype='datetime64[D]').astype(int)
            month_count=sum(clear[[i for i,d in enumerate(dates) if d[5:7]==m]].any(axis=0) for m in sorted({d[5:7] for d in dates}))
            first=np.where(clear,ordinals[:,None,None],10**9).min(axis=0)
            last=np.where(clear,ordinals[:,None,None],-10**9).max(axis=0)
            last_spaced=np.full((50,50),-10**9);spaced=np.zeros((50,50),int)
            for day,c in zip(ordinals,clear):
                take=c & (day-last_spaced>=10);spaced+=take;last_spaced[take]=day
            area=cell_areas(w['core_bounds_utm'])
            row=dict(window=wid,year=int(dates[0][:4]),season='Jan-Apr' if int(dates[0][5:7])<5 else 'Jun-Sep',
                     buffer_m=buffer,selected_dates=8,acquired_dates=8,core_cells=2500,
                     supported_cells=int(support.sum()),support_fraction=float(support.mean()),
                     clear_cell_observations=int(clear.sum()),total_cell_observations=int(clear.size),
                     masked_fraction=float(1-clear.mean()),minimum_clear_count=int(counts.min()),
                     median_clear_count=float(np.median(counts)),maximum_clear_count=int(counts.max()),
                     three_clear_dates_cells=int((counts>=3).sum()),three_months_cells=int((month_count>=3).sum()),
                     sixty_day_span_cells=int(((last-first)>=60).sum()),three_spaced_dates_cells=int((spaced>=3).sum()),
                     supported_area_m2=float(area[support].sum()),unsupported_area_m2=float(area[~support].sum()),
                     support_gate_pass=fraction_gate(int(support.sum()),2500,.8),status='measured',dates=dates)
            rows.append(row);arrays[f'{wid}_{buffer}_support']=support;arrays[f'{wid}_{buffer}_clear_count']=counts
    return rows,arrays


def all_coverage_rows(measured,windows,season_records):
    result=[];lookup={(r['window'],r['year'],r['season'],r['buffer_m']):r for r in measured}
    for w in windows:
        for s in season_records:
            for buffer in (60,120):
                key=(w['id'],s['year'],s['season'],buffer)
                result.append(lookup.get(key,dict(window=w['id'],year=s['year'],season=s['season'],buffer_m=buffer,
                              selected_dates=8,acquired_dates=0,core_cells=2500,supported_cells=None,support_fraction=None,
                              support_gate_pass=None,status='not_acquired_after_stop',dates=s['dates'])))
    return result


def save_coverage(run,rows,arrays):
    write_new(run/'coverage.json',rows)
    keys=['window','year','season','buffer_m','status','selected_dates','acquired_dates','core_cells','supported_cells','support_fraction','support_gate_pass','minimum_clear_count','median_clear_count','maximum_clear_count','masked_fraction','three_clear_dates_cells','three_months_cells','sixty_day_span_cells','three_spaced_dates_cells','supported_area_m2','unsupported_area_m2']
    with (run/'coverage.csv').open('x',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=keys,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    with (run/'coverage_arrays.npz').open('xb') as stream:np.savez_compressed(stream,**arrays)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(11,6),layout='constrained')
    for ax,buffer in zip(axes,(60,120)):
        a=np.full((6,12),np.nan)
        for r in rows:
            if r['buffer_m']!=buffer:continue
            i=['C1','C2','C3','C4','L1','W1'].index(r['window']);j=(r['year']-2020)*2+(r['season']=='Jun-Sep')
            if r['support_fraction'] is not None:a[i,j]=r['support_fraction']
        cmap=plt.get_cmap('viridis').copy();cmap.set_bad('#dddddd')
        ax.imshow(a,vmin=0,vmax=1,cmap=cmap,aspect='auto')
        ax.set_yticks(range(6),['C1','C2','C3','C4','L1','W1']);ax.set_xticks(range(12),[f'{y}\n{s}' for y in range(2020,2026) for s in ('Jan-Apr','Jun-Sep')],fontsize=8)
        ax.set_title(f'{buffer} m cloud/shadow buffer; each cell needs >=3 clear dates/months and spacing')
        for i,j in np.ndindex(a.shape):
            ax.text(j,i,'not acquired' if np.isnan(a[i,j]) else f'{a[i,j]:.1%}',ha='center',va='center',fontsize=7,color='black' if np.isnan(a[i,j]) or a[i,j]>.65 else 'white')
    fig.suptitle('Temporal support fraction per fixed 1 km core; required >=80% in every entry')
    fig.savefig(run/'coverage.png',dpi=160);plt.close(fig)


def final_gates(annual,final,controls):
    """Deterministic per-window/per-sensitivity denominators; no pooled rescue."""
    primary=scenario_id(0.,60);rows=[]
    for wid,scenarios in final.items():
        base=scenarios[primary];eligible=np.isin(base,[0,1,2,3]);trans=np.isin(base,[2,3])
        for sid,result in scenarios.items():
            for yi,state in enumerate(annual[wid][sid]):
                n=int((state>=0).sum());rows.append(dict(gate='interpretability',window=wid,scenario=sid,year=2020+yi,n=n,den=2500,minimum=.7,passed=fraction_gate(n,2500,.7)))
            if sid!=primary:
                n=int(((result==base)&eligible).sum());den=int(eligible.sum())
                rows.append(dict(gate='robustness',window=wid,scenario=sid,n=n,den=den,minimum=.9,passed=fraction_gate(n,den,.9)))
                n=int(((result==base)&trans).sum());den=int(trans.sum())
                rows.append(dict(gate='direction_retention',window=wid,scenario=sid,n=n,den=den,minimum=.8,passed=fraction_gate(n,den,.8) if den else None,status='measured' if den else 'no_primary_transitions'))
            if wid in controls:
                mask,expected=controls[wid];den=int(mask.sum());n=int(((result==expected)&mask).sum())
                rows.append(dict(gate='control',window=wid,scenario=sid,n=n,den=den,minimum=.95,passed=fraction_gate(n,den,.95)))
    return rows


def classify(observations,windows,seasons,controls,run):
    annual={};final={};areas=[];archive={}
    for w in windows:
        wid=w['id'];annual[wid]={};final[wid]={};area=cell_areas(w['core_bounds_utm'])
        for centre,buffer in SCENARIOS:
            sid=scenario_id(centre,buffer);seasonal=[]
            for season in seasons:
                dates=season['dates'];clear=[];state=[]
                for d in dates:
                    a=observations[d][wid]
                    c,s=rules.date_states(a['B03'],a['B11'],a['SCL'],centre,buffer)
                    clear.append(c[8:-8,8:-8]);state.append(s[8:-8,8:-8])
                _,s=rules.season_state(dates,np.stack(clear),np.stack(state));seasonal.append(s)
            years=np.stack([rules.annual_state(seasonal[i],seasonal[i+1]) for i in range(0,12,2)])
            result=rules.persistence(years);annual[wid][sid]=years;final[wid][sid]=result
            archive[f'{wid}_{sid}_annual']=years;archive[f'{wid}_{sid}_persistence']=result
            row=dict(window=wid,role=w['role'],scenario=sid,total_area_m2=float(area.sum()))
            for code,label in [(-3,'insufficient_duration'),(-2,'reversal'),(-1,'unknown'),(0,'stable_land'),(1,'stable_water'),(2,'water_to_land'),(3,'land_to_water')]:
                row[label+'_m2']=float(area[result==code].sum())
            areas.append(row)
    gates=final_gates(annual,final,controls)
    with (run/'states.npz').open('xb') as stream:np.savez_compressed(stream,**archive)
    write_new(run/'areas.json',areas);write_new(run/'interpretation_gates.json',gates)
    return annual,final,gates


def deliver_states(annual,final,windows,observations,date_item,run,include_examples):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    primary=scenario_id(0.,60);intervals=[]
    for w in windows:
        wid=w['id'];area=cell_areas(w['core_bounds_utm'])
        for sid,years in annual[wid].items():
            for yi in range(5):
                before,after=years[yi:yi+2]
                intervals.append(dict(window=wid,scenario=sid,from_year=2020+yi,to_year=2021+yi,
                    description='Annual-state differences; persistent status reported separately',
                    water_to_land_m2=float(area[(before==1)&(after==0)].sum()),
                    land_to_water_m2=float(area[(before==0)&(after==1)].sum()),
                    unknown_m2=float(area[(before<0)|(after<0)].sum())))
        fig,axes=plt.subplots(2,6,figsize=(14,5),layout='constrained')
        for yi,ax in enumerate(axes[0]):
            ax.imshow(annual[wid][primary][yi],vmin=-1,vmax=1,cmap=matplotlib.colors.ListedColormap(['#bcbcbc','#a78a55','#469dbd']))
            ax.set_title(str(2020+yi));ax.set_xticks([]);ax.set_yticks([])
        for ax,(sid,states) in zip(axes[1],final[wid].items()):
            ax.imshow(states,vmin=-3,vmax=3,cmap=matplotlib.colors.ListedColormap(['#d8b5df','#e6af62','#bcbcbc','#a78a55','#469dbd','#56a85b','#cd5358']))
            ax.set_title(sid.replace('centre_','c=').replace('_buffer_',' b='),fontsize=8);ax.set_xticks([]);ax.set_yticks([])
        fig.suptitle(f'{wid} 1 km core: primary annual states and six persistence sensitivities\nGrey unknown; brown land; blue water; green water-to-land; red land-to-water; orange reversal; purple edge duration')
        fig.savefig(run/f'{wid}_states.png',dpi=160);plt.close(fig)
    write_new(run/'annual_intervals.json',intervals)
    totals=[]
    for sid in final['C1']:
        row=dict(scenario=sid)
        for value,label in [(2,'water_to_land'),(3,'land_to_water'),(-1,'unknown')]:
            row[label+'_m2']=sum(float(cell_areas(w['core_bounds_utm'])[final[w['id']][sid]==value].sum()) for w in windows if w['id'].startswith('C'))
        totals.append(row)
    write_new(run/'coastal_totals.json',dict(scenarios=totals,
        sensitivity_range_m2={key:[min(r[key] for r in totals),max(r[key] for r in totals)] for key in ('water_to_land_m2','land_to_water_m2','unknown_m2')},
        note='Four coastal cores only; gross directions separate; sensitivity range is not a confidence interval; no extrapolation'))
    if not include_examples:return
    groups={'water_to_land':[],'land_to_water':[],'unresolved':[],'L1':[],'W1':[]}
    for wid,states in final.items():
        for row,col in np.ndindex(states[primary].shape):
            value=int(states[primary][row,col])
            group=wid if wid in ('L1','W1') else {2:'water_to_land',3:'land_to_water'}.get(value,'unresolved' if value<0 else None)
            if group is None:continue
            key=f'{wid},{row},{col},{group}'
            groups[group].append((hashlib.sha256(key.encode('ascii')).hexdigest(),key,dict(window=wid,row=row,col=col,category=group)))
    selected=[]
    for group,candidates in groups.items():
        selected.extend(x[2] for x in sorted(candidates)[:5 if group in ('L1','W1') else 10])
    examples=run/'examples';examples.mkdir()
    dates=sorted(observations)
    for ex in selected:
        wid,row,col=ex['window'],ex['row'],ex['col'];rc=row+8;cc=col+8
        for start in range(0,96,8):
            part=dates[start:start+8];fig,axes=plt.subplots(2,8,figsize=(16,5),layout='constrained')
            for j,d in enumerate(part):
                a=observations[d][wid];native=np.stack([a[k+'_native'] for k in ('B04','B03','B02')],axis=-1)
                rr,cl=rc*2,cc*2;rgb=native[max(0,rr-12):rr+14,max(0,cl-12):cl+14]
                axes[0,j].imshow(np.nan_to_num(np.clip(rgb/.3,0,1))**(1/2.2))
                _,states=rules.date_states(a['B03'],a['B11'],a['SCL'])
                g,s=a['B03'],a['B11'];ix=np.divide(g-s,g+s,out=np.full(g.shape,np.nan),where=np.isfinite(g+s)&(g+s>.02)&(g>=0)&(s>=0))
                axes[1,j].imshow(ix[max(0,rc-6):rc+7,max(0,cc-6):cc+7],cmap='RdBu',vmin=-1,vmax=1)
                props=date_item[d]['properties'];axes[0,j].set_title(d+'\n'+props['platform']+' PB'+props['s2:processing_baseline'],fontsize=7)
                axes[1,j].set_title(f"MNDWI {ix[rc,cc]:.2f}; label {states[rc,cc]}",fontsize=7)
                for ax in axes[:,j]:ax.set_xticks([]);ax.set_yticks([]);ax.plot(.5,.5,'+',transform=ax.transAxes,color='yellow')
            fig.suptitle(f"{wid} row {row} col {col}: {ex['category']} | native 10 m RGB / 20 m green-SWIR index\nPrimary annual states: {annual[wid][primary][:,row,col].tolist()}; same-observation review, not independent validation")
            fig.savefig(examples/f'{wid}_{row}_{col}_{start//8:02}.png',dpi=140);plt.close(fig)
    write_new(run/'review_examples.json',dict(selected=selected,owner_review='pending; no scale-up authorized',
                                             counts={k:len(v) for k,v in groups.items()}))
