from scripts.analyze_v11_descending_failure import largest_patch, local_checks


def test_local_checks_separate_requested_and_catalogue_relative_span() -> None:
    row = {
        "image_fraction": 0.95,
        "temporal_span_fraction": 0.85,
        "edge_to_image_ratio": 2.5,
        "all_finite_retained_bridge_count": 0,
        "all_finite_retained_edges_without_triangle_count": 0,
        "n_loop_err": 0,
    }
    checks = local_checks(row, global_span_fraction=0.85)
    assert not checks["requested_window_span"]
    assert checks["catalogue_relative_span"]
    assert all(value for key, value in checks.items() if "span" not in key)


def test_largest_patch_uses_eight_connectivity_and_area() -> None:
    passing = {(0, 0), (1, 1), (5, 5)}
    areas = {(0, 0): 2.0, (1, 1): 3.0, (5, 5): 1.0}
    count, share, cells = largest_patch(passing, areas)
    assert count == 2
    assert share == 5 / 6
    assert cells == 2
