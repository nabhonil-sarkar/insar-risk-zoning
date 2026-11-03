import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "LiCSBAS_Jakarta_descending_diagnostic_v11.ipynb"


def test_v11_notebook_is_valid_and_code_cells_compile():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    assert len(notebook["cells"]) == 10
    for index, cell in enumerate(notebook["cells"], start=1):
        if cell["cell_type"] == "code":
            assert cell["execution_count"] is None
            assert cell["outputs"] == []
            compile("".join(cell["source"]), f"v11_cell_{index}", "exec")


def test_v11_freezes_source_method_and_global_gates():
    text = NOTEBOOK.read_text(encoding="utf-8")
    required = (
        "FRAME = '047D_09652_111009'",
        "EXPECTED_COMPLETE_PAIRS = 349",
        "EXPECTED_ACQUISITIONS = 76",
        "GEOCML_NAME = 'GEOCml5clip'",
        "WRAPPED_PRODUCT = 'diff_unfiltered_pha'",
        "UNWRAP_CONSISTENCY_THRESHOLD = 0.3",
        "LOOP_THRESHOLD_RAD = 1.5",
        "--multi_prime",
        "MIN_LCC_IMAGE_FRACTION = 0.90",
        "MIN_LCC_TEMPORAL_SPAN_FRACTION = 0.95",
        "MIN_LCC_EDGE_TO_IMAGE_RATIO = 2.0",
        "GRID_TOLERANCE_PIXELS = 0.01",
        "set(disk_inventory['pairs']) != expected_pair_set",
        "cc_path.stat().st_size != cc_sizes[pair]",
        "rejection_fraction_role",
    )
    for item in required:
        assert item in text


def test_v11_contains_preregistered_north_gate():
    text = NOTEBOOK.read_text(encoding="utf-8")
    required = (
        "BOUNDARY_SHA256 = '7bb4dd0589cec8bd64e8930c94b1835116701b6148f7b7de183e61196593c540'",
        "MIN_NORTH_AREA_FRACTION = 0.50",
        "MIN_EACH_NORTH_DISTRICT_AREA_FRACTION = 0.25",
        "MIN_NORTH_LARGEST_PATCH_FRACTION = 0.75",
        "MIN_LOCAL_IMAGE_FRACTION = 0.90",
        "MIN_LOCAL_TEMPORAL_SPAN_FRACTION = 0.95",
        "MIN_LOCAL_EDGE_TO_IMAGE_RATIO = 2.0",
        "MAX_LOCAL_BRIDGES = 0",
        "MAX_LOCAL_EDGES_WITHOUT_TRIANGLE = 0",
        "MIN_NORTH_GRID_COVERAGE_FRACTION = 0.999999",
        "required_n_loop_err",
        "projected-area EPSG:32748 intersection",
        "all_finite_retained_edges_without_triangle_count",
        "district_grid_coverage_fractions",
        "North district grid coverage",
        "sensitivity_non_decisional",
    )
    for item in required:
        assert item in text


def test_v11_is_diagnostic_only_and_forbids_shortcuts():
    text = NOTEBOOK.read_text(encoding="utf-8")
    assert "LiCSBAS13_sb_inv" not in text
    assert "LiCSBAS14_vel_std" not in text
    assert "--rm_ifg_list" not in text
    assert "--nullify" not in text
    assert "EXPECTED_LEGACY_UNW_REPAIRS" not in text
    assert "USE_GACOS = False" in text
    assert "this notebook has no inversion" in text


def test_v11_is_self_contained_and_checkpoint_identity_is_frozen():
    text = NOTEBOOK.read_text(encoding="utf-8")
    for dependency in ("'shapely'", "'pyproj'"):
        assert dependency in text
    required = (
        "configuration_fingerprint",
        "catalogue_pairs_sha256",
        "require_matching_provenance",
        "source_archive_sha256",
        "licsbas_commit",
        "licsar_extra_commit",
        "pending_provenance",
        "set(restored['pairs']) != expected_pair_set",
        "set(regenerated['pairs']) != expected_pair_set",
    )
    for item in required:
        assert item in text


def test_v11_rechecks_final_identity_and_all_local_edges():
    text = NOTEBOOK.read_text(encoding="utf-8")
    required = (
        "set(all_ifgs) != expected_pair_set",
        "all_images != catalogue_images",
        "rejected - expected_pair_set",
        "def all_edge_redundancy",
        "all_local_bridges",
        "all_local_without_triangle",
        "n_ifg_noloop_present",
        "optional LiCSBAS output",
        "custom graph audit independently checks every retained edge",
    )
    for item in required:
        assert item in text
    assert "GEOCML_NAME = 'GEOCml5clip_desc47_reunw'" not in text


def test_v11_preflights_boundary_and_preserves_restored_inventory():
    text = NOTEBOOK.read_text(encoding="utf-8")
    assert "BOUNDARY_CACHE" in text
    assert "Verified official DKI boundary preflight" in text
    assert "rerun cell 5 before diagnostics" in text
    assert "archived_records != current_records" in text
    assert "v11_source_inventory_current_census.json" in text
