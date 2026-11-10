"""Physical geometry and unknown-support safeguards for the v2 screen."""
import pytest
from shapely.geometry import box, GeometryCollection
from scripts.building_change_explore.v2 import compare_geometry


def test_baseline_outside_cell_buffers_into_cell():
    domain=box(-100,-100,100,100);cell=box(0,0,30,30)
    baseline=box(-5,0,-1,30);endpoint=box(0,0,10,30)
    result,*_=compare_geometry(baseline,endpoint,domain,domain,domain,cell)
    assert result['surviving_area_m2']==pytest.approx(90)
    assert result['comparison_area_m2']==900


def test_only_baseline_expands_and_eight_is_total_tolerance():
    domain=box(-100,-100,100,100);cell=box(0,0,30,30)
    baseline=box(0,0,10,30);endpoint=box(0,0,20,30)
    result,*_=compare_geometry(baseline,endpoint,domain,domain,domain,cell)
    assert result['surviving_area_m2']==pytest.approx(60)


def test_missing_neighbourhood_is_unknown_not_empty():
    domain=box(-100,-100,100,100);cell=box(0,0,30,30)
    valid0=domain.difference(box(-10,-50,-1,50))
    result,*_=compare_geometry(GeometryCollection(),cell,valid0,domain,domain,cell)
    assert result['comparison_area_m2']==pytest.approx(690)
    assert result['comparison_support_fraction']==pytest.approx(23/30)
    assert result['surviving_fraction']==1


def test_denominator_uses_actual_cell_and_valid_area():
    domain=box(-100,-100,100,100);cell=box(0,0,20,25)
    valid3=domain.difference(box(0,0,10,25));endpoint=box(10,0,15,25)
    result,*_=compare_geometry(GeometryCollection(),endpoint,domain,valid3,domain,cell)
    assert result['cell_area_m2']==500
    assert result['comparison_area_m2']==250
    assert result['surviving_fraction']==.5


def test_missing_all_support_has_undefined_growth():
    domain=box(-100,-100,100,100);cell=box(0,0,30,30)
    result,*_=compare_geometry(GeometryCollection(),cell,GeometryCollection(),domain,domain,cell)
    assert result['comparison_area_m2']==0
    assert result['surviving_fraction'] is None


def test_round_physical_buffer_not_square_or_pixel_count():
    baseline=box(0,0,.5,.5);domain=box(-100,-100,100,100)
    result,_,expanded,_=compare_geometry(baseline,domain,domain,domain,domain,domain.buffer(-10))
    from shapely.geometry import Point
    assert expanded.covers(Point(8.5,.25))
    assert not expanded.covers(Point(8.51,.25))
    assert not expanded.covers(Point(8,8))
