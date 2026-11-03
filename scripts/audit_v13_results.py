"""Independently audit the checksum-gated v13 shorter-window result bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tarfile
from pathlib import Path, PurePosixPath

import numpy as np


EXPECTED_ARCHIVE_SHA256 = "54afa2dc1255af1dc04727ea0e6730e6975f6edbcf897744ef0724975d468187"
EXPECTED_BOUNDARY_SHA256 = "7bb4dd0589cec8bd64e8930c94b1835116701b6148f7b7de183e61196593c540"
TS_NAME = "TS_GEOCml5clip_desc47_short_reunw_mp"
RUN_TAG = "desc47_short_reunw_unfiltered_roi_ml5_mp"
DATE_TAG = "20200110_20230611"


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def validate_members(bundle: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = bundle.getmembers()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
            raise RuntimeError(f"Unsafe archive member: {member.name}")
    return members


def member_bytes(bundle: tarfile.TarFile, name: str) -> bytes:
    try:
        member = bundle.getmember(name)
    except KeyError as exc:
        raise RuntimeError(f"Required archive member is missing: {name}") from exc
    stream = bundle.extractfile(member)
    if stream is None:
        raise RuntimeError(f"Archive member is not a regular file: {name}")
    return stream.read()


def parse_dem_parameters(raw: bytes) -> dict[str, float | int | str]:
    result: dict[str, float | int | str] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        token = value.strip().split()[0] if value.strip() else ""
        if key.strip() in {"width", "nlines"}:
            result[key.strip()] = int(token)
        else:
            try:
                result[key.strip()] = float(token)
            except ValueError:
                result[key.strip()] = value.strip()
    return result


def finite_statistics(values: np.ndarray) -> dict[str, int | float | None]:
    finite = np.isfinite(values)
    selected = values[finite]
    return {
        "total_pixels": int(values.size),
        "finite_pixels": int(finite.sum()),
        "min": float(selected.min()) if selected.size else None,
        "median": float(np.median(selected)) if selected.size else None,
        "max": float(selected.max()) if selected.size else None,
    }


def strict_candidate(
    ledger: list[dict], velocity: np.ndarray, velocity_std: np.ndarray,
    n_gap: np.ndarray, n_loop_err: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    eligible = np.zeros(velocity.shape, dtype=bool)
    for row in ledger:
        y, x = int(row["row"]), int(row["col"])
        if not (0 <= y < velocity.shape[0] and 0 <= x < velocity.shape[1]):
            raise RuntimeError(f"North ledger cell is outside the result grid: {(y, x)}")
        eligible[y, x] = bool(row["qualifies"])
    strict = (
        eligible
        & np.isfinite(velocity)
        & np.isfinite(velocity_std)
        & (n_gap == 0)
        & (n_loop_err == 0)
    )
    return eligible, strict


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} mismatch: {actual!r} != {expected!r}")


def assert_close(actual: float, expected: float, label: str, tolerance: float = 1e-6) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=tolerance, abs_tol=tolerance):
        raise RuntimeError(f"{label} mismatch: {actual!r} != {expected!r}")


def audit(
    archive_path: Path, sidecar_path: Path, qc_path: Path, manifest_path: Path,
) -> dict:
    archive_sha = sha256_file(archive_path)
    assert_equal(archive_sha, EXPECTED_ARCHIVE_SHA256, "final archive SHA-256")
    sidecar_fields = sidecar_path.read_text(encoding="utf-8").strip().split()
    if len(sidecar_fields) < 2:
        raise RuntimeError("Malformed final archive SHA-256 sidecar")
    assert_equal(sidecar_fields[0], archive_sha, "sidecar SHA-256")
    assert_equal(sidecar_fields[1], archive_path.name, "sidecar filename")

    external_qc_bytes = qc_path.read_bytes()
    external_manifest_bytes = manifest_path.read_bytes()
    external_qc = json.loads(external_qc_bytes)
    external_manifest = json.loads(external_manifest_bytes)

    info_root = f"{TS_NAME}/info"
    results_root = f"{TS_NAME}/results"
    qc_member = f"{info_root}/{qc_path.name}"
    manifest_member = f"{info_root}/{manifest_path.name}"
    ledger_member = f"{info_root}/{RUN_TAG}_north_pixel_ledger.json"
    gate_member = f"{info_root}/{RUN_TAG}_post_inversion_gate.json"

    with tarfile.open(archive_path, "r:gz") as bundle:
        members = validate_members(bundle)
        embedded_qc_bytes = member_bytes(bundle, qc_member)
        embedded_manifest_bytes = member_bytes(bundle, manifest_member)
        assert_equal(embedded_qc_bytes, external_qc_bytes, "embedded/downloaded QC bytes")
        assert_equal(embedded_manifest_bytes, external_manifest_bytes, "embedded/downloaded manifest bytes")
        ledger = json.loads(member_bytes(bundle, ledger_member))
        embedded_gate = json.loads(member_bytes(bundle, gate_member))
        boundary_sha = hashlib.sha256(member_bytes(bundle, "dki_kelurahan_official.geojson")).hexdigest()
        assert_equal(boundary_sha, EXPECTED_BOUNDARY_SHA256, "official DKI boundary SHA-256")

        dem = parse_dem_parameters(member_bytes(bundle, "GEOCml5clip/EQA.dem_par"))
        width, length = int(dem["width"]), int(dem["nlines"])
        shape = (length, width)
        expected_values = width * length

        arrays = {}
        for role in ("vel", "vstd", "coh_avg", "n_unw", "n_gap", "n_loop_err"):
            values = np.frombuffer(member_bytes(bundle, f"{results_root}/{role}"), dtype="<f4")
            if values.size != expected_values:
                raise RuntimeError(f"Unexpected {role} size: {values.size} != {expected_values}")
            arrays[role] = values.reshape(shape)

    assert_equal(external_qc["frame"], "047D_09652_111009", "QC frame")
    assert_equal(external_qc["orbit"], "descending", "QC orbit")
    assert_equal((external_qc["start"], external_qc["end"]), ("20200110", "20230611"), "QC interval")
    assert_equal(external_manifest["frame"], external_qc["frame"], "manifest/QC frame")
    assert_equal(external_manifest["network_gate"], external_qc["network_gate"], "manifest/QC network gate")
    assert_equal(external_manifest["post_inversion_gate"], external_qc["post_inversion_gate"], "manifest/QC post gate")
    assert_equal(embedded_gate, external_qc["post_inversion_gate"], "embedded/QC post gate")
    assert_equal(external_qc["network_gate"]["passed"], True, "network gate")
    assert_equal(external_qc["post_inversion_gate"]["passed"], True, "post-inversion gate")

    raw_stats = {}
    for role in ("vel", "vstd", "coh_avg", "n_unw"):
        observed = finite_statistics(arrays[role])
        recorded = external_qc["layer_statistics"][role]
        assert_equal(observed["total_pixels"], recorded["total_pixels"], f"{role} total pixels")
        assert_equal(observed["finite_pixels"], recorded["finite_or_domain_pixels"], f"{role} finite pixels")
        for statistic in ("min", "median", "max"):
            assert_close(observed[statistic], recorded[statistic], f"{role} {statistic}")
        raw_stats[role] = observed

    eligible, strict = strict_candidate(
        ledger, arrays["vel"], arrays["vstd"], arrays["n_gap"], arrays["n_loop_err"]
    )
    post_gate = external_qc["post_inversion_gate"]
    assert_equal(len(ledger), post_gate["north_candidate_cells"], "North candidate cells")
    assert_equal(int(eligible.sum()), 380, "prequalified North pixels")
    assert_equal(int(strict.sum()), post_gate["strict_qualifying_cells"], "strict North pixels")
    assert_equal(int(strict.sum()), 380, "strict North pixels")

    strict_stats = {
        role: finite_statistics(arrays[role][strict])
        for role in ("vel", "vstd", "coh_avg", "n_unw")
    }
    assert_close(
        strict_stats["vel"]["min"],
        external_qc["layer_statistics"]["north_velocity_strict_masked"]["min"],
        "strict velocity minimum",
    )
    assert_close(
        strict_stats["vel"]["median"],
        external_qc["layer_statistics"]["north_velocity_strict_masked"]["median"],
        "strict velocity median",
    )
    assert_close(
        strict_stats["vel"]["max"],
        external_qc["layer_statistics"]["north_velocity_strict_masked"]["max"],
        "strict velocity maximum",
    )
    if strict_stats["vstd"]["max"] > 5.0:
        raise RuntimeError("The strict candidate does not reproduce the reported <=5 mm/year vstd sensitivity")
    assert_equal(np.unique(arrays["n_gap"][strict]).tolist(), [0.0], "strict n_gap")
    assert_equal(np.unique(arrays["n_loop_err"][strict]).tolist(), [0.0], "strict n_loop_err")

    return {
        "audit_status": "passed",
        "scientific_status": "shorter_period_validation_candidate_only",
        "archive": {
            "path": str(archive_path), "bytes": archive_path.stat().st_size,
            "sha256": archive_sha, "member_count": len(members), "path_safety": "passed",
        },
        "sidecar_verified": True,
        "embedded_external_json_byte_identity": {"qc_summary": True, "manifest": True},
        "qc_summary_sha256": hashlib.sha256(external_qc_bytes).hexdigest(),
        "manifest_sha256": hashlib.sha256(external_manifest_bytes).hexdigest(),
        "official_boundary_sha256": boundary_sha,
        "grid": {"width": width, "length": length, "total_pixels": expected_values},
        "reference_area": external_qc.get("reference_area"),
        "network": {
            "interferograms": external_qc["network_gate"]["total_interferograms"],
            "retained_interferograms": (
                external_qc["network_gate"]["total_interferograms"]
                - external_qc["network_gate"]["unique_rejected_interferograms"]
            ),
            "images": external_qc["network_gate"]["total_images"],
            "passed": True,
        },
        "raw_layer_statistics": raw_stats,
        "strict_north": {
            "candidate_cells": len(ledger), "prequalified_cells": int(eligible.sum()),
            "strict_cells": int(strict.sum()),
            "area_fraction_from_frozen_gate": post_gate["strict_qualifying_area_fraction"],
            "district_area_fractions_from_frozen_gate": post_gate["district_area_fractions"],
            "largest_patch_fraction_from_frozen_gate": post_gate["largest_8_connected_patch_fraction_of_passing_area"],
            "layer_statistics": strict_stats,
            "n_gap_unique": [0.0], "n_loop_err_unique": [0.0],
        },
        "remaining_requirements": post_gate["promotion_still_requires"],
        "prohibited_claims": external_qc["prohibited_claims"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--sidecar", required=True, type=Path)
    parser.add_argument("--qc-summary", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    report = audit(arguments.archive, arguments.sidecar, arguments.qc_summary, arguments.manifest)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(arguments.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(arguments.output)
    print(json.dumps(report, indent=2, allow_nan=False))
    print("Audit report:", arguments.output)
    print("Audit report SHA-256:", sha256_file(arguments.output))


if __name__ == "__main__":
    main()
