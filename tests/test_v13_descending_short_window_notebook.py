import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_v13_descending_short_window_notebook.py"
NOTEBOOK = ROOT / "notebooks" / "LiCSBAS_Jakarta_descending_short_window_v13.ipynb"
V11_NOTEBOOK = ROOT / "notebooks" / "LiCSBAS_Jakarta_descending_diagnostic_v11.ipynb"

EXPECTED_V11_SHA256 = "119e495f1c6a7b1dbba6640997f5e9756d86e61679e1217223a57c1f2f35e067"
EXPECTED_CHECKPOINT_SHA256 = "0a3d1378234eef757fdb07341abb96dc2934612d4a4124c8282cf40b619565b9"
EXPECTED_CONFIGURATION_FINGERPRINT = "8aa6272c2f629684926140b864361cb15ff3a3c5c988c3bad0cd015b817984f9"


def notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def notebook_text() -> str:
    return "\n".join("".join(cell["source"]) for cell in notebook()["cells"])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_builder_reproduces_checked_in_notebook_exactly(tmp_path: Path) -> None:
    before = NOTEBOOK.read_bytes()
    subprocess.run([sys.executable, str(BUILDER)], cwd=ROOT, check=True)
    assert NOTEBOOK.read_bytes() == before


def test_v11_is_immutable_source_evidence() -> None:
    assert sha256(V11_NOTEBOOK) == EXPECTED_V11_SHA256


def test_every_code_cell_compiles_and_notebook_is_clean() -> None:
    data = notebook()
    assert data["nbformat"] == 4
    assert len(data["cells"]) == 12
    for index, cell in enumerate(data["cells"]):
        if cell["cell_type"] == "code":
            ast.parse("".join(cell["source"]), filename=f"v13-cell-{index}")
            assert cell["execution_count"] is None
            assert cell["outputs"] == []


def test_exact_short_window_and_verified_checkpoint_are_frozen() -> None:
    text = notebook_text()
    assert "START, END = '20200110', '20230611'" in text
    assert "EXPECTED_COMPLETE_PAIRS = 349" in text
    assert "EXPECTED_ACQUISITIONS = 76" in text
    assert EXPECTED_CHECKPOINT_SHA256 in text
    assert EXPECTED_CONFIGURATION_FINGERPRINT in text
    assert "catalogue_images[0] != START or catalogue_images[-1] != END" in text
    assert "approximately 40 MB regenerated v11 checkpoint" in text
    assert "Removing an incomplete ephemeral checkpoint extraction before retrying" in text
    assert "geocml_root.resolve().parent != WORK.resolve()" in text


def test_unchanged_processing_and_network_controls_are_enforced() -> None:
    text = notebook_text()
    required = [
        "NLOOK = 5",
        "UNWRAP_FILTER = 'gold'",
        "UNWRAP_CONSISTENCY_THRESHOLD = 0.3",
        "USE_GACOS = False",
        "LOOP_MODE = 'multi_prime'",
        "LOOP_THRESHOLD_RAD = 1.5",
        "'--multi_prime'",
        "MIN_LCC_IMAGE_FRACTION = 0.90",
        "MIN_LCC_TEMPORAL_SPAN_FRACTION = 0.95",
        "MIN_LCC_EDGE_TO_IMAGE_RATIO = 2.0",
        "MAX_LCC_BRIDGE_INTERFEROGRAMS = 0",
        "MAX_LCC_INTERFEROGRAMS_WITHOUT_TRIANGLE = 0",
    ]
    for fragment in required:
        assert fragment in text


def test_inversion_is_ordered_after_exact_window_gate() -> None:
    text = notebook_text()
    gate_pass = text.index("EXACT-WINDOW NETWORK + NORTH GATES PASSED")
    inversion = text.index("run_script('invert'")
    uncertainty = text.index("run_script('vstd'")
    assert gate_pass < inversion < uncertainty
    assert "LiCSBAS13_sb_inv.py" in text
    assert "LiCSBAS14_vel_std.py" in text


def test_prospective_post_inversion_gate_is_strict_and_spatial() -> None:
    text = notebook_text()
    required = [
        "strict_north = qualifies & finite_results & (n_gap == 0) & (final_n_loop_err == 0)",
        "MIN_NORTH_AREA_FRACTION = 0.50",
        "MIN_EACH_NORTH_DISTRICT_AREA_FRACTION = 0.25",
        "MIN_NORTH_LARGEST_PATCH_FRACTION = 0.75",
        "post-inversion North total area",
        "post-inversion North district minimum",
        "post-inversion North connected patch",
        "vstd_sensitivity_non_decisional",
        "(5.0, 10.0, 15.0, 20.0)",
        "reference-area sensitivity",
        "independent date-compatible GNSS or levelling validation",
    ]
    for fragment in required:
        assert fragment in text


def test_forbidden_shortcuts_and_promotion_language_are_absent() -> None:
    text = notebook_text().lower()
    forbidden = [
        "--nullify",
        "nullify_aggressive",
        "loop_threshold_rad = 2",
        "loop_threshold_rad = 3",
        "use_gacos = true",
        "factor 2",
        "validated hazard map",
    ]
    for fragment in forbidden:
        assert fragment not in text
    assert "does not use partial gacos, manual pair removal, nullification, or relaxed thresholds" in text
    assert "not a retroactive v11 pass" in text
    assert "shorter-period validation candidate" in text
    assert "do not promote rates, hazard, or risk" in text


def test_outputs_are_auditable_and_failure_archives_before_stopping() -> None:
    text = notebook_text()
    archive = text.index("results_sha = atomic_archive")
    stop = text.index("PREREGISTERED V13 STOP")
    assert archive < stop
    for fragment in (
        "north_strict_mask",
        "north_velocity_strict_masked",
        "POST_INVERSION_GATE_PATH",
        "QC_SUMMARY",
        "MANIFEST_PATH",
        "RESULTS_ARCHIVE_SHA",
    ):
        assert fragment in text
