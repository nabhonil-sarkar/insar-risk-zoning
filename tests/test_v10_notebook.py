import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "LiCSBAS_Jakarta_north_branch_recovery_v10.ipynb"


def test_v10_notebook_is_valid_and_all_code_cells_compile():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))

    assert notebook["nbformat"] == 4
    assert len(notebook["cells"]) == 16
    for index, cell in enumerate(notebook["cells"], start=1):
        if cell["cell_type"] == "code":
            assert cell["execution_count"] is None
            assert cell["outputs"] == []
            compile("".join(cell["source"]), f"v10_cell_{index}", "exec")


def test_v10_notebook_contains_every_preregistered_hard_gate():
    text = NOTEBOOK.read_text(encoding="utf-8")

    required = (
        "SHA256(loop_id) mod 5",
        "L1_ALPHA = 1e-2",
        "MIN_COMPONENT_PIXELS = 9",
        "MAX_COMPONENT_SAMPLES = 100",
        "whole original SNAPHU component",
        "wrapped phase changed by more than tolerance",
        "--multi_prime",
        "LOOP_THRESHOLD_RAD = 1.5",
        "EXPECTED_NORTH_LOOP_FAILED = 113",
        "EXPECTED_BASE_STRICT = 2477",
        "Partial improvement is evidence only",
        "independent GNSS_or_levelling_validation",
    )
    for item in required:
        assert item in text


def test_v10_notebook_does_not_enable_forbidden_shortcuts():
    text = NOTEBOOK.read_text(encoding="utf-8")

    assert "--nullify" not in text
    assert "--rm_ifg_list" not in text
    assert "np.random" not in text
    assert "selection='cyclic'" in text
    assert "LOOP_THRESHOLD_RAD = 1.5" in text
    assert "UNWRAP_CONSISTENCY_THRESHOLD = 0.3" in text
