"""Structural and scientific guard tests for the NISAR v12 feasibility notebook."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_v12_nisar_feasibility_notebook.py"
NOTEBOOK = ROOT / "notebooks" / "NISAR_Jakarta_north_feasibility_v12.ipynb"

PRODUCTS = {
    "NISAR_L2_PR_GUNW_024_010_A_174_025_4000_SH_20260626T223921_20260626T223956_20260708T223920_20260708T223955_P05023_N_F_J_001": 2_315_255_808,
    "NISAR_L2_PR_GUNW_025_010_A_174_026_4000_SH_20260708T223920_20260708T223955_20260720T223920_20260720T223954_P05023_N_F_J_001": 2_290_089_984,
    "NISAR_L2_PR_GUNW_024_018_D_092_025_4000_SH_20260627T111145_20260627T111223_20260709T111145_20260709T111222_P05023_N_F_J_001": 2_441_084_928,
    "NISAR_L2_PR_GUNW_025_018_D_092_026_4000_SH_20260709T111145_20260709T111222_20260721T111144_20260721T111222_P05023_N_F_J_001": 2_436_890_624,
}


def load_notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def notebook_text(notebook: dict) -> str:
    return "\n".join("".join(cell["source"]) for cell in notebook["cells"])


def code_text(notebook: dict) -> str:
    return "\n".join(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )


def test_builder_reproduces_notebook() -> None:
    before = NOTEBOOK.read_bytes()
    subprocess.run([sys.executable, str(BUILDER)], cwd=ROOT, check=True)
    assert NOTEBOOK.read_bytes() == before


def test_notebook_json_and_all_code_cells_compile() -> None:
    notebook = load_notebook()
    assert notebook["nbformat"] == 4
    assert notebook["nbformat_minor"] == 5
    assert len(notebook["cells"]) == 11
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            ast.parse("".join(cell["source"]), filename=f"v12-cell-{index}")


def test_exact_products_sizes_and_total_are_pinned() -> None:
    text = notebook_text(load_notebook())
    for product_id, size in PRODUCTS.items():
        assert product_id in text
        assert f"{size:_}" in text
    assert "EXPECTED_TOTAL_BYTES = 9_483_321_344" in text
    assert "P05023" in text
    assert "productionConfiguration') != 'PR'" in text


def test_inventory_and_download_are_guarded_before_analysis() -> None:
    notebook = load_notebook()
    text = notebook_text(notebook)
    assert text.index("Verify the official ASF inventory") < text.index("Restart-safe")
    assert "ASF_SEARCH_API" in text
    assert "_QA_SUMMARY.csv" in text
    assert "explicit ASF QA failure" in text
    assert "earthaccess.login" in text
    assert "Range" in text
    assert "Content-Range" in text
    assert "int(match.group(1)) != start" in text
    assert ".partial" in text
    assert "sha256_file(destination)" in text
    assert "HDF5 byte size changed" in text
    assert "'maxResults': 10" not in text
    assert "finalized_complete_partial" in text


def test_required_variables_and_exact_north_area_are_used() -> None:
    text = notebook_text(load_notebook())
    for variable in (
        "unwrappedPhase",
        "coherenceMagnitude",
        "connectedComponents",
        "ionospherePhaseScreen",
        "ionospherePhaseScreenUncertainty",
        "xCoordinates",
        "yCoordinates",
        "projection",
    ):
        assert variable in text
    assert "BOUNDARY_SHA256" in text
    assert "Jakarta Utara" in text
    assert "32748" in text
    assert "projected area in EPSG:32748" in text
    assert "equal-area" not in text
    assert "components != component_fill" in text
    assert "np.iinfo(component_ds.dtype).max" in text
    assert "Unexpected {key} shape" in text
    assert ".intersection(north_projected_area).area" in text
    assert "supplied_mask_flags" in text
    assert "GRID_PATH_CANDIDATES" in text
    assert "UNWRAPPED_GROUP + '/HH/xCoordinates'" in text
    assert "UNWRAPPED_GROUP + '/HH/yCoordinates'" in text
    assert "UNWRAPPED_GROUP + '/HH/projection'" in text
    assert "resolved_grid_paths" in text
    assert "generic_failure" in text


def test_frozen_gate_and_sensitivity_cannot_be_substituted() -> None:
    text = notebook_text(load_notebook())
    assert "PRIMARY_COHERENCE_THRESHOLD = 0.30" in text
    assert "SENSITIVITY_THRESHOLDS = (0.20, 0.40)" in text
    assert "MIN_FOOTPRINT_COVERAGE = 0.95" in text
    assert "MIN_EACH_IFG_USABLE_FRACTION = 0.50" in text
    assert "MIN_TWO_IFG_COMMON_USABLE_FRACTION = 0.40" in text
    assert "MIN_LARGEST_COMPONENT_SHARE = 0.80" in text
    assert "decisional=False" in text
    assert "strong_feasibility" in text
    assert "partial_feasibility" in text


def test_no_velocity_inversion_or_loop_closure_implementation_exists() -> None:
    code = code_text(load_notebook()).lower()
    forbidden = (
        "licsbas",
        "mintpy",
        "smallbaselineapp",
        "timeseries2velocity",
        "loop_closure.py",
        "snaphu",
        "phase_to_displacement",
        "wavelength / (4",
        "wavelength/(4",
        "velocity =",
        "subsidence_rate",
    )
    for token in forbidden:
        assert token not in code
    assert "no loop-closure test is possible" in notebook_text(load_notebook()).lower()
    assert "prohibited_claims" in code


def test_outputs_include_json_maps_and_verified_archive() -> None:
    text = notebook_text(load_notebook())
    assert "v12_nisar_north_feasibility_summary.json" in text
    assert "v12_nisar_north_coherence_and_usable.png" in text
    assert "v12_nisar_north_feasibility_outputs.tar.gz" in text
    assert "ARCHIVE_SHA_PATH" in text
    assert "Diagnostic archive inventory mismatch" in text
