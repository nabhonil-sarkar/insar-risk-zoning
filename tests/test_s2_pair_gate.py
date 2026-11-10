"""Data-free checks of fixed date, quality and four-group decision rules."""
import numpy as np
from scripts.building_change_explore.s2_pair_gate import eligible_scene, pair_order, gate_counts, allocation_inventory, GROUPS


def scene(year, date, **updates):
    value=dict(id=f'{year}-{date}',year=year,date=f'{year}-{date}T03:00:00',tile='48MXU',orbit=32,
               valid=1,edge_safe=1,clear=.97,target_clear=1)
    value.update(updates)
    return value


def test_full_footprint_and_target_quality_both_required():
    assert eligible_scene(scene(2020,'07-01'))
    for key,value in [('valid',.97),('edge_safe',.97),('clear',.89),('target_clear',.94)]:
        assert not eligible_scene(scene(2020,'07-01',**{key:value}))


def test_pair_rejects_season_mismatch_tile_and_orbit():
    a=scene(2020,'06-01')
    assert len(pair_order([a,scene(2023,'07-01')]))==1
    assert not pair_order([a,scene(2023,'07-02')])
    assert not pair_order([a,scene(2023,'06-01',tile='48MYU')])
    assert not pair_order([a,scene(2023,'06-01',orbit=75)])


def test_pair_selection_uses_worse_endpoint_then_deterministic_ties():
    a=scene(2020,'07-01',clear=.95)
    b=scene(2023,'07-01',clear=.93)
    c=scene(2023,'07-11',clear=.96)
    assert pair_order([b,c,a])[0][2]['id']==c['id']
    assert pair_order([a,b,c])==pair_order([c,b,a])


def test_leap_year_comparison_uses_calendar_dates():
    a=scene(2020,'08-01');b=scene(2023,'08-31')
    assert len(pair_order([a,b]))==1


def test_gate_requires_each_group_not_pooled_and_retains_unknowns():
    sites=[dict(id=f'{g}{i}',group=g,sector='NW' if i<5 else 'W',block=[j,i])
           for j,g in enumerate(GROUPS) for i in range(10)]
    reviews=[dict(id=s['id'],interpretable=(int(s['id'][-1])<7)) for s in sites]
    rows,passed=gate_counts(sites,reviews)
    assert passed and all(r['interpretable']==7 for r in rows)
    reviews=[r for r in reviews if r['id']!=GROUPS[0]+'0']
    rows,passed=gate_counts(sites,reviews)
    assert not passed and rows[0]['interpretable']==6 and rows[0]['sites']==10
    assert rows[0]['blocks']==10


def test_unavailable_development_stratum_is_not_filled_from_test_or_training():
    a=dict(inside=np.ones((1,4),bool),sectors=np.array([[0,0,3,3]]),
           hot_2023_1=np.ones((1,4),bool),cover=np.full((1,4),80),
           split=np.array([[0,2,1,1]]),buffer_retained=np.array([[True,True,True,False]]),
           block_x=np.array([[1,2,3,4]]),block_y=np.zeros((1,4),int))
    rows=allocation_inventory(a)
    nw=next(r for r in rows if r['sector']=='NW' and r['group']=='extreme_water')
    west=next(r for r in rows if r['sector']=='W' and r['group']=='extreme_water')
    assert nw['population_cells']==2 and nw['development_cells']==0
    assert west['development_cells']==2 and west['buffered_development_cells']==1
