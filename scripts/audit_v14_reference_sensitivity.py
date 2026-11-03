"""Independently audit the checksum-gated v14 reference-sensitivity bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tarfile
from pathlib import Path, PurePosixPath

import numpy as np
from scipy.stats import spearmanr

from scripts.audit_v13_results import member_bytes, parse_dem_parameters, validate_members


EXPECTED_BASELINE_SHA256 = "54afa2dc1255af1dc04727ea0e6730e6975f6edbcf897744ef0724975d468187"
EXPECTED_SUMMARY_SHA256 = "065906f9e1b313fbc062e2ce016eced48dd947e73cf58245081682f109f7b3f6"
EXPECTED_FINGERPRINT = "b76aab7903de62b9068c4ed87f41b97692e26b1c15be6743d7a75023ab8db994"
EXPECTED_CHECKPOINT_SHA256 = "0a3d1378234eef757fdb07341abb96dc2934612d4a4124c8282cf40b619565b9"
BASELINE_TS_NAME = "TS_GEOCml5clip_desc47_short_reunw_mp"
PREREGISTRATION_NAME = "v14_reference_area_preregistration_schema2.json"
DECISION_NAME = "v14_reference_area_sensitivity_decision_schema2.json"
MANIFEST_NAME = "v14_reference_area_sensitivity_manifest_schema2.json"

CANDIDATES = {
    "quality_west": {
        "reference": "63:64/36:37",
        "sha256": "bbac3c3d712bbd21fa8705ab433674c54446fecfe1a0234b122443f085637da5",
        "bytes": 31_528_183,
    },
    "quality_east": {
        "reference": "92:93/37:38",
        "sha256": "bfdc6261dfb2ea6793f83c6fa9c864f44816b65706dbea9c63c6d6ce6caa2ad7",
        "bytes": 31_684_442,
    },
    "quality_south": {
        "reference": "56:57/66:67",
        "sha256": "60e6e4d4cca5ba0c71818cab027a9f730b8c74e2cb2ecd2aa9c107bb4bc76c74",
        "bytes": 31_659_916,
    },
}


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} mismatch: {actual!r} != {expected!r}")


def assert_close(actual: float, expected: float, label: str, tolerance: float = 1e-9) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=tolerance, abs_tol=tolerance):
        raise RuntimeError(f"{label} mismatch: {actual!r} != {expected!r}")


def verify_sidecar(archive: Path, sidecar: Path, expected_sha256: str) -> dict:
    archive_sha = sha256_file(archive)
    assert_equal(archive_sha, expected_sha256, f"{archive.name} SHA-256")
    fields = sidecar.read_text(encoding="utf-8").strip().split()
    if len(fields) != 2:
        raise RuntimeError(f"Malformed SHA-256 sidecar: {sidecar}")
    assert_equal(fields[0], archive_sha, f"{sidecar.name} digest")
    assert_equal(fields[1], archive.name, f"{sidecar.name} filename")
    return {"path": str(archive), "bytes": archive.stat().st_size, "sha256": archive_sha}


def fingerprint_preregistration(preregistration: dict) -> str:
    excluded = {"created_utc", "configuration_fingerprint"}
    payload = json.dumps(
        {key: value for key, value in preregistration.items() if key not in excluded},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def result_array(bundle: tarfile.TarFile, root: str, name: str, shape: tuple[int, int]) -> np.ndarray:
    values = np.frombuffer(member_bytes(bundle, f"{root}/results/{name}"), dtype="<f4")
    if values.size != shape[0] * shape[1]:
        raise RuntimeError(f"Unexpected {root}/{name} size: {values.size} != {shape[0] * shape[1]}")
    return values.reshape(shape)


def strict_mask(
    eligible: np.ndarray,
    velocity: np.ndarray,
    velocity_std: np.ndarray,
    n_gap: np.ndarray,
    n_loop_err: np.ndarray,
) -> np.ndarray:
    return (
        eligible
        & np.isfinite(velocity)
        & np.isfinite(velocity_std)
        & (n_gap == 0)
        & (n_loop_err == 0)
    )


def comparison_statistics(control: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    difference = candidate.astype("float64") - control.astype("float64")
    offset = float(np.median(difference))
    centred = difference - offset
    return {
        "median_offset_from_control_mm_per_year": offset,
        "centered_rmse_mm_per_year": float(np.sqrt(np.mean(centred**2))),
        "centered_p95_abs_mm_per_year": float(np.percentile(np.abs(centred), 95)),
        "centered_max_abs_mm_per_year": float(np.max(np.abs(centred))),
        "pearson_pattern_correlation": float(np.corrcoef(control, candidate)[0, 1]),
        "spearman_pattern_correlation": float(spearmanr(control, candidate).statistic),
    }


def compare_record(observed: dict, recorded: dict, reference_id: str) -> None:
    for key, actual in observed.items():
        expected = recorded[key]
        if isinstance(actual, float):
            assert_close(actual, expected, f"{reference_id} {key}")
        else:
            assert_equal(actual, expected, f"{reference_id} {key}")


def audit(
    baseline_archive: Path,
    baseline_sidecar: Path,
    summary_archive: Path,
    summary_sidecar: Path,
    decision_path: Path,
    manifest_path: Path,
    candidate_archives: dict[str, Path],
    candidate_sidecars: dict[str, Path],
) -> dict:
    baseline_identity = verify_sidecar(baseline_archive, baseline_sidecar, EXPECTED_BASELINE_SHA256)
    summary_identity = verify_sidecar(summary_archive, summary_sidecar, EXPECTED_SUMMARY_SHA256)

    with tarfile.open(summary_archive, "r:gz") as summary:
        summary_members = validate_members(summary)
        assert_equal(
            sorted(member.name for member in summary_members),
            sorted([PREREGISTRATION_NAME, DECISION_NAME, MANIFEST_NAME]),
            "summary archive members",
        )
        preregistration_bytes = member_bytes(summary, PREREGISTRATION_NAME)
        embedded_decision_bytes = member_bytes(summary, DECISION_NAME)
        embedded_manifest_bytes = member_bytes(summary, MANIFEST_NAME)

    assert_equal(embedded_decision_bytes, decision_path.read_bytes(), "embedded/downloaded decision bytes")
    assert_equal(embedded_manifest_bytes, manifest_path.read_bytes(), "embedded/downloaded manifest bytes")
    preregistration = json.loads(preregistration_bytes)
    decision = json.loads(embedded_decision_bytes)
    manifest = json.loads(embedded_manifest_bytes)

    fingerprint = fingerprint_preregistration(preregistration)
    assert_equal(fingerprint, EXPECTED_FINGERPRINT, "recomputed preregistration fingerprint")
    assert_equal(preregistration["configuration_fingerprint"], fingerprint, "preregistration fingerprint")
    assert_equal(decision["configuration_fingerprint"], fingerprint, "decision fingerprint")
    assert_equal(manifest["configuration_fingerprint"], fingerprint, "manifest fingerprint")
    assert_equal(preregistration["frozen_before_alternative_inversion"], True, "preregistration timing")
    assert_equal(preregistration["velocity_used_for_reference_selection"], False, "reference selection")
    assert_equal(preregistration["baseline_archive_sha256"], EXPECTED_BASELINE_SHA256, "baseline identity")
    assert_equal(
        preregistration["regenerated_checkpoint_sha256"], EXPECTED_CHECKPOINT_SHA256, "checkpoint identity"
    )

    assert_equal(
        hashlib.sha256(preregistration_bytes).hexdigest(),
        manifest["preregistration"]["sha256"],
        "manifest preregistration SHA-256",
    )
    assert_equal(
        hashlib.sha256(embedded_decision_bytes).hexdigest(),
        manifest["decision"]["sha256"],
        "manifest decision SHA-256",
    )
    assert_equal(manifest["decision"]["outcome"], decision["outcome"], "manifest decision outcome")
    assert_equal(manifest["baseline_results"]["sha256"], EXPECTED_BASELINE_SHA256, "manifest baseline SHA-256")

    info_root = f"{BASELINE_TS_NAME}/info"
    results_root = f"{BASELINE_TS_NAME}/results"
    with tarfile.open(baseline_archive, "r:gz") as baseline:
        baseline_members = validate_members(baseline)
        dem = parse_dem_parameters(member_bytes(baseline, "GEOCml5clip/EQA.dem_par"))
        shape = (int(dem["nlines"]), int(dem["width"]))
        ledger = json.loads(
            member_bytes(baseline, f"{info_root}/desc47_short_reunw_unfiltered_roi_ml5_mp_north_pixel_ledger.json")
        )
        eligible = np.zeros(shape, dtype=bool)
        for item in ledger:
            eligible[int(item["row"]), int(item["col"])] = bool(item["qualifies"])
        baseline_arrays = {
            name: result_array(baseline, BASELINE_TS_NAME, name, shape)
            for name in ("vel", "vstd", "n_gap", "n_loop_err")
        }
        baseline_reference = member_bytes(baseline, f"{info_root}/12ref.txt").decode().strip()

    baseline_strict = strict_mask(eligible, **{
        "velocity": baseline_arrays["vel"],
        "velocity_std": baseline_arrays["vstd"],
        "n_gap": baseline_arrays["n_gap"],
        "n_loop_err": baseline_arrays["n_loop_err"],
    })
    assert_equal(baseline_reference, "90:91/30:31", "baseline 12ref")
    assert_equal(int(eligible.sum()), 380, "eligible North cells")
    assert_equal(int(baseline_strict.sum()), 380, "baseline strict cells")

    control_values = baseline_arrays["vel"][baseline_strict].astype("float64")
    control_vstd = baseline_arrays["vstd"][baseline_strict].astype("float64")
    observed_comparison = {
        "control_12ref": {
            "reference": baseline_reference,
            "strict_cells": 380,
            "strict_mask_equals_baseline": True,
            "strict_vstd_max_mm_per_year": float(control_vstd.max()),
            "median_strict_velocity_mm_per_year": float(np.median(control_values)),
            "coverage_passed": True,
            "uncertainty_passed": bool(control_vstd.max() <= 5.0),
        }
    }

    candidate_report = {}
    member_counts = []
    for reference_id, expected in CANDIDATES.items():
        archive = candidate_archives[reference_id]
        sidecar = candidate_sidecars[reference_id]
        identity = verify_sidecar(archive, sidecar, expected["sha256"])
        assert_equal(identity["bytes"], expected["bytes"], f"{reference_id} archive bytes")
        manifest_record = manifest["candidate_artifacts"][reference_id]
        assert_equal(manifest_record["bytes"], identity["bytes"], f"{reference_id} manifest bytes")
        assert_equal(manifest_record["sha256"], identity["sha256"], f"{reference_id} manifest SHA-256")

        root = f"{BASELINE_TS_NAME}_ref_{reference_id}"
        with tarfile.open(archive, "r:gz") as candidate:
            members = validate_members(candidate)
            member_counts.append(len(members))
            names = {member.name for member in members}
            if f"{root}/info/120bad_ifg.txt" in names:
                raise RuntimeError(f"{reference_id} contains prohibited 120bad_ifg.txt")
            provenance = json.loads(member_bytes(candidate, f"{root}/info/v14_reference_run_provenance.json"))
            candidate_reference = member_bytes(candidate, f"{root}/info/12ref.txt").decode().strip()
            arrays = {
                name: result_array(candidate, root, name, shape)
                for name in ("vel", "vstd", "n_gap", "n_loop_err")
            }

        assert_equal(candidate_reference, expected["reference"], f"{reference_id} 12ref")
        assert_equal(provenance["reference_id"], reference_id, f"{reference_id} provenance id")
        assert_equal(provenance["reference"], candidate_reference, f"{reference_id} provenance reference")
        assert_equal(provenance["configuration_fingerprint"], fingerprint, f"{reference_id} fingerprint")
        assert_equal(provenance["baseline_archive_sha256"], EXPECTED_BASELINE_SHA256, f"{reference_id} baseline")
        assert_equal(provenance["checkpoint_sha256"], EXPECTED_CHECKPOINT_SHA256, f"{reference_id} checkpoint")
        assert_equal(provenance["only_changed_input"], "info/12ref.txt", f"{reference_id} changed input")
        assert_equal(provenance["steps"], ["13_LS_gamma_0.0001", "14"], f"{reference_id} steps")
        assert_equal(
            arrays["n_gap"].tobytes(), baseline_arrays["n_gap"].tobytes(), f"{reference_id} n_gap identity"
        )
        assert_equal(
            arrays["n_loop_err"].tobytes(),
            baseline_arrays["n_loop_err"].tobytes(),
            f"{reference_id} n_loop_err identity",
        )

        candidate_strict = strict_mask(
            eligible, arrays["vel"], arrays["vstd"], arrays["n_gap"], arrays["n_loop_err"]
        )
        exact_mask = bool(np.array_equal(candidate_strict, baseline_strict))
        values = arrays["vel"][baseline_strict].astype("float64")
        vstd_values = arrays["vstd"][baseline_strict].astype("float64")
        record = {
            "reference": candidate_reference,
            "strict_cells": int(candidate_strict.sum()),
            "strict_mask_equals_baseline": exact_mask,
            "strict_vstd_max_mm_per_year": float(vstd_values.max()),
            "median_strict_velocity_mm_per_year": float(np.median(values)),
            "coverage_passed": int(candidate_strict.sum()) == 380 and exact_mask,
            "uncertainty_passed": bool(np.isfinite(vstd_values).all() and vstd_values.max() <= 5.0),
        }
        record.update(comparison_statistics(control_values, values))
        rules = preregistration["decision_rules"]
        record["centered_pattern_passed"] = bool(
            record["pearson_pattern_correlation"] >= rules["min_pearson_and_spearman_pattern_correlation"]
            and record["spearman_pattern_correlation"] >= rules["min_pearson_and_spearman_pattern_correlation"]
            and record["centered_rmse_mm_per_year"] <= rules["max_centered_rmse_mm_per_year"]
            and record["centered_p95_abs_mm_per_year"]
            <= rules["max_centered_p95_absolute_difference_mm_per_year"]
            and record["centered_max_abs_mm_per_year"]
            <= rules["max_centered_absolute_difference_mm_per_year"]
        )
        observed_comparison[reference_id] = record
        candidate_report[reference_id] = {**identity, "member_count": len(members), "provenance_verified": True}

    assert_equal(len(set(member_counts)), 1, "candidate archive member-count consistency")
    for reference_id, record in observed_comparison.items():
        compare_record(record, decision["comparison"][reference_id], reference_id)

    median_rates = {
        reference_id: record["median_strict_velocity_mm_per_year"]
        for reference_id, record in observed_comparison.items()
    }
    spread = float(max(median_rates.values()) - min(median_rates.values()))
    coverage_uncertainty_passed = all(
        record["coverage_passed"] and record["uncertainty_passed"] for record in observed_comparison.values()
    )
    pattern_passed = all(
        observed_comparison[reference_id]["centered_pattern_passed"] for reference_id in CANDIDATES
    )
    zero_level_passed = spread <= preregistration["decision_rules"][
        "max_reference_median_rate_spread_mm_per_year"
    ]
    outcome = (
        "full_pass"
        if coverage_uncertainty_passed and pattern_passed and zero_level_passed
        else "relative_pattern_only"
        if coverage_uncertainty_passed and pattern_passed
        else "failed"
    )
    for reference_id, rate in median_rates.items():
        assert_close(rate, decision["median_rates_mm_per_year"][reference_id], f"{reference_id} median rate")
    assert_close(spread, decision["reference_median_rate_spread_mm_per_year"], "median-rate spread")
    assert_equal(decision["gates"]["coverage_and_uncertainty_passed"], coverage_uncertainty_passed, "coverage gate")
    assert_equal(decision["gates"]["centered_spatial_pattern_passed"], pattern_passed, "pattern gate")
    assert_equal(decision["gates"]["absolute_zero_level_passed"], zero_level_passed, "zero-level gate")
    assert_equal(decision["outcome"], outcome, "recomputed outcome")
    assert_equal(outcome, "relative_pattern_only", "expected terminal outcome")
    assert_equal(decision["external_validation_still_required"], True, "external-validation requirement")

    return {
        "audit_status": "passed",
        "experiment": preregistration["experiment"],
        "configuration_fingerprint": fingerprint,
        "archive_path_safety": "passed",
        "baseline": {**baseline_identity, "member_count": len(baseline_members)},
        "summary": {**summary_identity, "member_count": len(summary_members)},
        "candidate_archives": candidate_report,
        "embedded_external_json_byte_identity": {"decision": True, "manifest": True},
        "preregistration_sha256": hashlib.sha256(preregistration_bytes).hexdigest(),
        "decision_sha256": hashlib.sha256(embedded_decision_bytes).hexdigest(),
        "manifest_sha256": hashlib.sha256(embedded_manifest_bytes).hexdigest(),
        "grid": {"length": shape[0], "width": shape[1], "pixels": shape[0] * shape[1]},
        "eligible_north_cells": int(eligible.sum()),
        "baseline_strict_cells": int(baseline_strict.sum()),
        "comparison": observed_comparison,
        "median_rates_mm_per_year": median_rates,
        "reference_median_rate_spread_mm_per_year": spread,
        "gates": {
            "coverage_and_uncertainty_passed": coverage_uncertainty_passed,
            "centered_spatial_pattern_passed": pattern_passed,
            "absolute_zero_level_passed": zero_level_passed,
        },
        "outcome": outcome,
        "scientific_status": "validation_candidate_only",
        "interpretation": (
            "The strict relative descending-LOS spatial pattern is computationally reproduced, "
            "but the absolute zero level is not stable and no rate, vertical subsidence, hazard, or risk is validated."
        ),
        "next_required_stage": manifest["next_required_stage"],
        "prohibited_claims": decision["prohibited_claims"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-archive", required=True, type=Path)
    parser.add_argument("--baseline-sidecar", required=True, type=Path)
    parser.add_argument("--summary-archive", required=True, type=Path)
    parser.add_argument("--summary-sidecar", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    for reference_id in CANDIDATES:
        parser.add_argument(f"--{reference_id.replace('_', '-')}-archive", required=True, type=Path)
        parser.add_argument(f"--{reference_id.replace('_', '-')}-sidecar", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    candidate_archives = {
        reference_id: getattr(arguments, f"{reference_id}_archive") for reference_id in CANDIDATES
    }
    candidate_sidecars = {
        reference_id: getattr(arguments, f"{reference_id}_sidecar") for reference_id in CANDIDATES
    }
    report = audit(
        arguments.baseline_archive,
        arguments.baseline_sidecar,
        arguments.summary_archive,
        arguments.summary_sidecar,
        arguments.decision,
        arguments.manifest,
        candidate_archives,
        candidate_sidecars,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(arguments.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(arguments.output)
    print(json.dumps(report, indent=2, allow_nan=False))
    print("Audit report:", arguments.output)
    print("Audit report SHA-256:", sha256_file(arguments.output))


if __name__ == "__main__":
    main()
