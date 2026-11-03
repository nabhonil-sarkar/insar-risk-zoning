import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "LiCSBAS_Jakarta_reference_sensitivity_v14.ipynb"
BUILDER = ROOT / "scripts" / "build_v14_reference_sensitivity_notebook.py"


def load_notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def notebook_text() -> str:
    return "\n".join("".join(cell.get("source", [])) for cell in load_notebook()["cells"])


def cell_text(index: int) -> str:
    return "".join(load_notebook()["cells"][index]["source"])


def test_notebook_is_structurally_valid_and_every_code_cell_compiles() -> None:
    notebook = load_notebook()
    assert notebook["nbformat"] == 4
    assert len(notebook["cells"]) == 12
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            ast.parse("".join(cell["source"]), filename=f"v14-cell-{index}")


def test_builder_and_notebook_are_reproducible() -> None:
    before = hashlib.sha256(NOTEBOOK.read_bytes()).hexdigest()
    namespace = {"__name__": "__main__", "__file__": str(BUILDER)}
    exec(compile(BUILDER.read_text(encoding="utf-8"), str(BUILDER), "exec"), namespace)
    after = hashlib.sha256(NOTEBOOK.read_bytes()).hexdigest()
    assert after == before


def test_exact_v13_inputs_and_all_four_references_are_frozen() -> None:
    text = notebook_text()
    assert "54afa2dc1255af1dc04727ea0e6730e6975f6edbcf897744ef0724975d468187" in text
    assert "0a3d1378234eef757fdb07341abb96dc2934612d4a4124c8282cf40b619565b9" in text
    for reference in (
        "90:91/30:31", "78:79/72:73", "63:64/36:37", "92:93/37:38", "56:57/66:67",
    ):
        assert reference in text
    assert "EXPECTED_STRICT_NORTH_CELLS = 380" in text
    assert "QUALITY_REQUIRED_N_UNW = 347" in text
    assert "v14_reference_sensitivity_schema2" in text


def test_reference_selection_is_quality_only_and_frozen_before_reruns() -> None:
    selection = cell_text(6)
    assert "quality = {name: baseline_grid(name) for name in ('coh_avg', 'n_unw', 'n_gap', 'n_loop_err')}" in selection
    assert "velocity_used_for_reference_selection': False" in selection
    assert "SCHEMA-2 PREREGISTRATION FROZEN. STOP HERE" in selection
    assert "baseline_grid('vel')" not in selection
    assert "results / 'vel'" not in selection
    assert "west['col'], west['row']) != (63, 36)" in selection
    assert "east['col'], east['row']) != (92, 37)" in selection
    assert "south['col'], south['row']) != (56, 66)" in selection
    assert "direct_reference_support" in selection
    assert "supported_ifgs'] != QUALITY_REQUIRED_N_UNW" in selection
    assert "admissible_as_preliminary_12ref': False" in selection
    assert "120bad_ifg.txt" in selection


def test_all_decision_thresholds_and_three_outcomes_are_frozen() -> None:
    text = notebook_text()
    assert "REFERENCE_MEDIAN_SPREAD_MAX_MMYR = 3.0" in text
    assert "CENTERED_RMSE_MAX_MMYR = 0.5" in text
    assert "CENTERED_P95_ABS_MAX_MMYR = 1.0" in text
    assert "CENTERED_MAX_ABS_MAX_MMYR = 3.0" in text
    assert "MIN_PATTERN_CORRELATION = 0.99" in text
    assert "MAX_STRICT_VSTD_MMYR = 5.0" in text
    assert "outcome = 'full_pass'" in text
    assert "outcome = 'relative_pattern_only'" in text
    assert "outcome = 'failed'" in text


def test_alternative_runs_are_isolated_restart_safe_step13_14_only() -> None:
    text = notebook_text()
    run_cell = cell_text(7)
    assert "shutil.copytree(baseline_ts, target)" in run_cell
    assert "(target / 'info' / '12ref.txt').write_text" in run_cell
    assert "run_script('invert'" in run_cell
    assert "run_script('vstd'" in run_cell
    assert "atomic_archive(WORK, [ts_name], archive)" in run_cell
    assert "RESTORED verified v14 candidate" in run_cell
    assert "run_reference_candidate('quality_west')" in run_cell
    assert "run_reference_candidate('auto_13ref')" not in text
    assert "run_script('check'" not in text
    assert "run_script('loop'" not in text


def test_forbidden_rescue_shortcuts_and_promotion_claims_are_absent() -> None:
    text = notebook_text().lower()
    assert "--nullify" not in text
    assert "--multi_prime" not in text
    assert "gacos" in text and "does not" in text
    assert "manual pair" not in text
    assert "independent date-compatible gnss or levelling" in text
    assert "external_validation_still_required': true" in text


def test_final_summary_is_compact_and_preserves_candidate_archive_hashes() -> None:
    final = cell_text(11)
    assert "candidate_artifacts" in final
    assert "sha256_file(archive)" in final
    assert "v14_reference_area_sensitivity_summary_schema2.tar.gz" in notebook_text()
    assert "No rate is validated" in final
