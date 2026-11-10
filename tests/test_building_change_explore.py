"""Scientific denominator and missing-support checks for the Day 1 helpers."""
import numpy as np
from scripts.building_change_explore.analyse import labels,metrics


def test_missing_is_neither_low_nor_ambiguous():
    ref=np.zeros((4,3,1,4),np.float32)
    ref[:,2]=[0,.94,.95,1]
    ref[:,0]=[0,0,.095,.2]
    _,valid,low,high,amb=labels(ref)
    assert valid[0].tolist()==[[False,False,True,True]]
    assert low[0].tolist()==[[False,False,True,False]]
    assert amb[0].tolist()==[[False,False,False,True]]
    assert not high.any()


def test_coverage_uses_supported_area_not_full_cell():
    ref=np.zeros((4,3,1,1),np.float32)
    ref[:,2]=.95;ref[:,0]=.38
    coverage,_,_,high,_=labels(ref)
    np.testing.assert_allclose(coverage,.4)
    assert high.all()


def test_enrichment_capture_and_extreme_denominators():
    eligible=np.array([[True,True,True,True,False]])
    additions=np.array([[True,False,True,False,False]])
    extreme=np.array([[True,False,False,False,True]])
    local={'block_x':np.array([[1,1,2,2,3]]),'block_y':np.zeros((1,5),int)}
    m=metrics(eligible,additions,extreme,local)
    assert m['eligible_cells']==4 and m['eligible_extreme_cells']==1
    assert m['addition_prevalence']==.5 and m['extreme_addition_prevalence']==1
    assert m['enrichment']==2 and m['addition_capture_fraction']==.5
    assert m['blocks']==2 and m['extreme_addition_blocks']==1


def test_empty_is_unknown_not_zero():
    z=np.zeros((1,2),bool);local={'block_x':np.zeros((1,2),int),'block_y':np.zeros((1,2),int)}
    m=metrics(z,z,z,local)
    assert m['enrichment'] is None and m['addition_prevalence'] is None and m['addition_capture_fraction'] is None


def test_zero_additions_is_zero_prevalence_but_undefined_ratio():
    z=np.zeros((1,2),bool);e=~z;local={'block_x':np.zeros((1,2),int),'block_y':np.zeros((1,2),int)}
    m=metrics(e,z,e,local)
    assert m['addition_prevalence']==0 and m['extreme_addition_prevalence']==0 and m['enrichment'] is None
