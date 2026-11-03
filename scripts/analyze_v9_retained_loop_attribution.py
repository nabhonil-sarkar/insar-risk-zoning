"""Reconstruct v9 retained loops and attribute North Jakarta loop-error burden."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
import matplotlib
import numpy as np
import rasterio
from rasterio.features import rasterize

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


EXPECTED_CHECKPOINT_SHA256 = (
    "3329cd9c75d5c96e604f0c9b3b950fe127018bfebc06d2c19f9426b3fb234efb"
)
EXPECTED_INVENTORY_SHA256 = (
    "cf06e2235374b36aa8d5ca790adf8356ebd8b1d40daf0aa2e45e739a016e52af"
)
EXPECTED_RESULTS_SHA256 = (
    "99f38ec03233f900a6c28ee629e279df8aed427e18c70c8101a9e4f094bbd23d"
)
EXPECTED_QC_SHA256 = (
    "c8293d4d33d208458a7677aa0e12ee935b9b74d753226c0022b78483dd68acc7"
)
EXPECTED_BOUNDARY_SHA256 = (
    "7bb4dd0589cec8bd64e8930c94b1835116701b6148f7b7de183e61196593c540"
)
LICSBAS_COMMIT = "a145e6c4217b29eb7348ea95630454a099809098"
CHECKPOINT_ROOT = "GEOCml5clip/"
RESULTS_ROOT = "TS_GEOCml5clip_reunw_mp/"
NORTH_NAME = "JAKARTA UTARA"
LOOP_ERROR_THRESHOLD_RAD = float(np.pi)
UNW_PATTERN = re.compile(
    r"^GEOCml5clip/(?P<pair>\d{8}_\d{8})/(?P=pair)\.unw$"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_reference_area(text: str) -> tuple[int, int, int, int]:
    """Parse LiCSBAS x1:x2/y1:y2 reference-area notation."""
    match = re.fullmatch(r"\s*(\d+):(\d+)/(\d+):(\d+)\s*", text)
    if match is None:
        raise ValueError(f"Invalid LiCSBAS reference area: {text!r}")
    x1, x2, y1, y2 = map(int, match.groups())
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"Empty LiCSBAS reference area: {text!r}")
    return x1, x2, y1, y2


def make_triangle_loops(ifgdates: Iterable[str]) -> list[tuple[str, str, str]]:
    """Reproduce LiCSBAS_loop_lib.make_loop_matrix as explicit pair triplets."""
    ordered = sorted(ifgdates)
    pair_set = set(ordered)
    pairs_by_first: dict[str, list[str]] = defaultdict(list)
    for pair in ordered:
        first, _ = pair.split("_")
        pairs_by_first[first].append(pair)

    loops: list[tuple[str, str, str]] = []
    for pair12 in ordered:
        first, second = pair12.split("_")
        for pair23 in pairs_by_first.get(second, []):
            _, third = pair23.split("_")
            pair13 = f"{first}_{third}"
            if pair13 in pair_set:
                loops.append((pair12, pair23, pair13))
    return loops


def referenced_loop_phase(
    unw12: np.ndarray,
    unw23: np.ndarray,
    unw13: np.ndarray,
    reference_area: tuple[int, int, int, int],
) -> np.ndarray:
    """Apply the reference correction used in LiCSBAS step 12's fourth loop."""
    x1, x2, y1, y2 = reference_area
    with np.errstate(invalid="ignore"):
        ref12 = np.nanmean(unw12[y1:y2, x1:x2])
        ref23 = np.nanmean(unw23[y1:y2, x1:x2])
        ref13 = np.nanmean(unw13[y1:y2, x1:x2])
        return unw12 + unw23 - unw13 - (ref12 + ref23 - ref13)


def loop_error_mask(loop_phase: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return LiCSBAS-compatible error and valid-data masks at the fixed pi gate."""
    valid = ~np.isnan(loop_phase)
    phase_for_gate = loop_phase.copy()
    phase_for_gate[~valid] = 0.0
    error = ~(np.abs(phase_for_gate) < LOOP_ERROR_THRESHOLD_RAD)
    return error, valid


def _read_text(bundle: tarfile.TarFile, name: str) -> str:
    stream = bundle.extractfile(name)
    if stream is None:
        raise ValueError(f"Archive is missing {name}")
    return stream.read().decode("utf-8", errors="replace")


def _read_list(bundle: tarfile.TarFile, name: str) -> list[str]:
    return [
        line.strip()
        for line in _read_text(bundle, name).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _read_float_grid(
    bundle: tarfile.TarFile, name: str, height: int, width: int
) -> np.ndarray:
    stream = bundle.extractfile(name)
    if stream is None:
        raise ValueError(f"Archive is missing {name}")
    values = np.frombuffer(stream.read(), dtype="<f4")
    expected = height * width
    if values.size != expected:
        raise ValueError(f"Unexpected grid size for {name}: {values.size} != {expected}")
    return values.reshape(height, width).copy()


def _load_unwrapped_stack(
    checkpoint: Path, height: int, width: int
) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    with tarfile.open(checkpoint, "r:gz") as bundle:
        for member in bundle.getmembers():
            if not member.isfile():
                continue
            match = UNW_PATTERN.fullmatch(member.name)
            if match is None:
                continue
            stream = bundle.extractfile(member)
            if stream is None:
                raise ValueError(f"Could not read {member.name}")
            values = np.frombuffer(stream.read(), dtype="<f4")
            expected = height * width
            if values.size != expected:
                raise ValueError(
                    f"Unexpected unwrapped grid size for {member.name}: "
                    f"{values.size} != {expected}"
                )
            array = values.reshape(height, width).copy()
            array[array == 0] = np.nan
            arrays[match.group("pair")] = array
    return arrays


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        raise ValueError(f"No records to write: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def _aggregate_participation(
    loop_records: list[dict[str, Any]], field: str
) -> list[dict[str, Any]]:
    aggregate: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {
            "retained_triangle_loops": 0,
            "north_valid_opportunities": 0,
            "north_error_events": 0,
            "north_error_loops": 0,
        }
    )
    for record in loop_records:
        for identifier in record[field]:
            values = aggregate[identifier]
            values["retained_triangle_loops"] += 1
            values["north_valid_opportunities"] += record["north_valid_pixels"]
            values["north_error_events"] += record["north_error_pixels"]
            values["north_error_loops"] += int(record["north_error_pixels"] > 0)

    records: list[dict[str, Any]] = []
    identifier_name = "pair" if field == "pairs" else "acquisition"
    for identifier, values in aggregate.items():
        opportunities = int(values["north_valid_opportunities"])
        errors = int(values["north_error_events"])
        record: dict[str, Any] = {
            identifier_name: identifier,
            **values,
            "north_error_rate_per_valid_opportunity": (
                errors / opportunities if opportunities else 0.0
            ),
        }
        if identifier_name == "pair":
            first, second = identifier.split("_")
            record["first"] = first
            record["second"] = second
            record["temporal_baseline_days"] = (
                dt.datetime.strptime(second, "%Y%m%d")
                - dt.datetime.strptime(first, "%Y%m%d")
            ).days
        records.append(record)
    records.sort(
        key=lambda item: (-int(item["north_error_events"]), str(item[identifier_name]))
    )
    return records


def _plot_rankings(
    path: Path,
    loop_records: list[dict[str, Any]],
    pair_records: list[dict[str, Any]],
    acquisition_records: list[dict[str, Any]],
) -> None:
    groups = [
        (
            sorted(loop_records, key=lambda item: -item["north_error_pixels"])[:12],
            "loop",
            "north_error_pixels",
            "Retained triangle loops",
        ),
        (pair_records[:12], "pair", "north_error_events", "Interferogram participation"),
        (
            acquisition_records[:12],
            "acquisition",
            "north_error_events",
            "Acquisition participation",
        ),
    ]
    figure, axes = plt.subplots(1, 3, figsize=(18, 7.2))
    colours = ("#7b3294", "#d95f02", "#1b9e77")
    for axis, (records, label_field, value_field, title), colour in zip(
        axes, groups, colours
    ):
        display = list(reversed(records))
        labels = [str(record[label_field]) for record in display]
        values = [int(record[value_field]) for record in display]
        axis.barh(np.arange(len(display)), values, color=colour)
        axis.set_yticks(np.arange(len(display)), labels, fontsize=8)
        axis.set_xlabel("North loop-error pixel events")
        axis.set_title(title)
        axis.grid(axis="x", linewidth=0.4, alpha=0.35)
    figure.suptitle(
        "V9 retained-loop attribution in measurable North Jakarta pixels", y=0.985
    )
    figure.text(
        0.01,
        0.012,
        "Pair and acquisition panels show triangle participation, not unique fault causation; pi threshold unchanged.",
        fontsize=8,
        color="#333333",
    )
    figure.tight_layout(rect=(0, 0.07, 1, 0.95))
    figure.savefig(path, dpi=180, facecolor="white")
    plt.close(figure)


def _top_share(values: list[int], top_n: int) -> float:
    total = sum(values)
    return sum(sorted(values, reverse=True)[:top_n]) / total if total else 0.0


def run(
    checkpoint_path: Path,
    checkpoint_checksum_path: Path,
    inventory_path: Path,
    results_archive_path: Path,
    qc_summary_path: Path,
    official_boundary_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    inputs = (
        checkpoint_path,
        checkpoint_checksum_path,
        inventory_path,
        results_archive_path,
        qc_summary_path,
        official_boundary_path,
    )
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)

    checkpoint_sha = sha256_file(checkpoint_path)
    supplied_checkpoint_sha = (
        checkpoint_checksum_path.read_text(encoding="utf-8").strip().split()[0].lower()
    )
    if not (
        checkpoint_sha == supplied_checkpoint_sha == EXPECTED_CHECKPOINT_SHA256
    ):
        raise ValueError("Checkpoint does not match both supplied and expected SHA-256")
    expected_hashes = {
        inventory_path: EXPECTED_INVENTORY_SHA256,
        results_archive_path: EXPECTED_RESULTS_SHA256,
        qc_summary_path: EXPECTED_QC_SHA256,
        official_boundary_path: EXPECTED_BOUNDARY_SHA256,
    }
    actual_hashes = {path: sha256_file(path) for path in expected_hashes}
    for path, expected in expected_hashes.items():
        if actual_hashes[path] != expected:
            raise ValueError(f"SHA-256 mismatch for {path}: {actual_hashes[path]} != {expected}")

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    qc = json.loads(qc_summary_path.read_text(encoding="utf-8"))
    metadata = qc["layer_statistics"]["vel"]
    height, width = map(int, metadata["shape"])
    transform = rasterio.Affine(*map(float, metadata["transform"][:6]))
    if metadata["crs"] != "EPSG:4326":
        raise ValueError(f"Expected EPSG:4326, found {metadata['crs']}")
    if inventory["pair_folders"] != 609 or inventory["complete_pairs"] != 609:
        raise ValueError("Checkpoint inventory does not contain 609 complete pairs")
    if int(inventory["resolution"]["multilooked_parameters"]["width"]) != width:
        raise ValueError("Checkpoint and QC-summary widths differ")
    if int(inventory["resolution"]["multilooked_parameters"]["nlines"]) != height:
        raise ValueError("Checkpoint and QC-summary heights differ")

    with tarfile.open(results_archive_path, "r:gz") as results_bundle:
        step11_bad = _read_list(results_bundle, RESULTS_ROOT + "info/11bad_ifg.txt")
        step12_bad = _read_list(results_bundle, RESULTS_ROOT + "info/12bad_ifg.txt")
        reference_area_text = _read_text(
            results_bundle, RESULTS_ROOT + "info/12ref.txt"
        ).strip()
        expected_n_loop_err = _read_float_grid(
            results_bundle,
            RESULTS_ROOT + "results/n_loop_err",
            height,
            width,
        )
        velocity = _read_float_grid(
            results_bundle, RESULTS_ROOT + "results/vel", height, width
        )
        vstd = _read_float_grid(
            results_bundle, RESULTS_ROOT + "results/vstd", height, width
        )
    reference_area = parse_reference_area(reference_area_text)

    boundary_json = json.loads(official_boundary_path.read_text(encoding="utf-8"))
    kelurahan = gpd.GeoDataFrame.from_features(boundary_json["features"], crs="EPSG:4326")
    kelurahan["wadmkk"] = kelurahan["wadmkk"].astype(str).str.strip()
    kelurahan.geometry = kelurahan.geometry.make_valid()
    north_features = kelurahan[kelurahan["wadmkk"] == NORTH_NAME]
    if north_features.empty:
        raise ValueError("Official boundary contains no North Jakarta features")
    north_inside = rasterize(
        [(north_features.geometry.union_all(), 1)],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=False,
        dtype="uint8",
    ).astype(bool)
    measurable_north = north_inside & np.isfinite(velocity) & np.isfinite(vstd)
    loop_failed_north = measurable_north & (expected_n_loop_err > 0)

    unwrapped = _load_unwrapped_stack(checkpoint_path, height, width)
    if len(unwrapped) != 609:
        raise ValueError(f"Expected 609 unwrapped phase arrays, found {len(unwrapped)}")
    unknown_step11 = sorted(set(step11_bad) - set(unwrapped))
    unknown_step12 = sorted(set(step12_bad) - set(unwrapped))
    if unknown_step11 or unknown_step12:
        raise ValueError(
            f"Rejected lists contain unknown pairs: step11={unknown_step11}, "
            f"step12={unknown_step12}"
        )

    step11_network = sorted(set(unwrapped) - set(step11_bad))
    all_loops = make_triangle_loops(step11_network)
    reconstructed = np.zeros((height, width), dtype="uint16")
    loop_records: list[dict[str, Any]] = []
    north_error_phase_values: list[np.ndarray] = []
    skipped_step12_loops = 0
    for pair12, pair23, pair13 in all_loops:
        pairs = (pair12, pair23, pair13)
        if any(pair in step12_bad for pair in pairs):
            skipped_step12_loops += 1
            continue
        phase = referenced_loop_phase(
            unwrapped[pair12],
            unwrapped[pair23],
            unwrapped[pair13],
            reference_area,
        )
        error, valid = loop_error_mask(phase)
        reconstructed += error.astype("uint16")
        dates = (pair12[:8], pair12[-8:], pair23[-8:])
        selected_errors = error & loop_failed_north
        selected_valid = valid & loop_failed_north
        selected_phase = np.abs(phase[selected_valid])
        error_phase = np.abs(phase[selected_errors])
        if error_phase.size:
            north_error_phase_values.append(error_phase)
        loop_records.append(
            {
                "loop": "_".join(dates),
                "date1": dates[0],
                "date2": dates[1],
                "date3": dates[2],
                "pair12": pair12,
                "pair23": pair23,
                "pair13": pair13,
                "pairs": pairs,
                "acquisitions": dates,
                "north_valid_pixels": int(selected_valid.sum()),
                "north_error_pixels": int(selected_errors.sum()),
                "north_error_fraction_of_failed_pixels": float(
                    selected_errors.sum() / loop_failed_north.sum()
                ),
                "north_error_rate_per_valid_pixel": float(
                    selected_errors.sum() / selected_valid.sum()
                    if selected_valid.any()
                    else 0.0
                ),
                "north_abs_phase_median_rad": (
                    float(np.median(selected_phase)) if selected_phase.size else None
                ),
                "north_abs_error_phase_median_rad": (
                    float(np.median(error_phase)) if error_phase.size else None
                ),
                "whole_grid_error_pixels": int(error.sum()),
            }
        )

    if not np.all(np.isfinite(expected_n_loop_err)):
        raise ValueError("Saved n_loop_err contains non-finite values")
    expected_counts = expected_n_loop_err.astype("uint16")
    difference = reconstructed.astype("int32") - expected_counts.astype("int32")
    exact_reproduction = bool(np.array_equal(reconstructed, expected_counts))
    if not exact_reproduction:
        raise RuntimeError(
            "Retained-loop reconstruction does not reproduce saved n_loop_err: "
            f"different_pixels={int((difference != 0).sum())}, "
            f"max_abs_difference={int(np.abs(difference).max())}"
        )

    pair_records = _aggregate_participation(loop_records, "pairs")
    acquisition_records = _aggregate_participation(loop_records, "acquisitions")
    loop_records.sort(key=lambda item: (-item["north_error_pixels"], item["loop"]))
    serializable_loop_records = [
        {key: value for key, value in record.items() if key not in {"pairs", "acquisitions"}}
        for record in loop_records
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    loop_path = output_dir / "v9_north_retained_loop_attribution.csv"
    pair_path = output_dir / "v9_north_retained_pair_participation.csv"
    acquisition_path = output_dir / "v9_north_retained_acquisition_participation.csv"
    plot_path = output_dir / "v9_north_retained_loop_attribution.png"
    _write_csv(loop_path, serializable_loop_records)
    _write_csv(pair_path, pair_records)
    _write_csv(acquisition_path, acquisition_records)
    _plot_rankings(plot_path, loop_records, pair_records, acquisition_records)

    loop_event_values = [int(record["north_error_pixels"]) for record in loop_records]
    total_north_error_events = int(reconstructed[loop_failed_north].sum())
    if total_north_error_events != sum(loop_event_values):
        raise RuntimeError("Loop-record event sum differs from reconstructed North total")
    top_loops = serializable_loop_records[:20]
    top_pairs = pair_records[:20]
    top_acquisitions = acquisition_records[:20]
    all_north_error_phase = np.concatenate(north_error_phase_values)
    nearest_cycle_count = np.rint(all_north_error_phase / (2 * np.pi)).astype("int16")
    distance_to_integer_cycle = np.abs(
        all_north_error_phase - nearest_cycle_count * (2 * np.pi)
    )
    cycle_count_values, cycle_count_frequencies = np.unique(
        nearest_cycle_count, return_counts=True
    )
    summary: dict[str, Any] = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scientific_status": "exact_retained_loop_reconstruction_and_descriptive_attribution",
        "source": {
            "checkpoint": checkpoint_path.name,
            "checkpoint_sha256": checkpoint_sha,
            "checkpoint_checksum": checkpoint_checksum_path.name,
            "checkpoint_checksum_sha256": sha256_file(checkpoint_checksum_path),
            "inventory": inventory_path.name,
            "inventory_sha256": actual_hashes[inventory_path],
            "results_archive": results_archive_path.name,
            "results_archive_sha256": actual_hashes[results_archive_path],
            "qc_summary": qc_summary_path.name,
            "qc_summary_sha256": actual_hashes[qc_summary_path],
            "official_boundary": official_boundary_path.name,
            "official_boundary_sha256": actual_hashes[official_boundary_path],
        },
        "method": {
            "licsbas_source_commit": LICSBAS_COMMIT,
            "step11_removed_before_triangle_construction": True,
            "step12_rejected_loops_skipped": True,
            "reference_area_xy": reference_area_text,
            "loop_error_threshold_rad": LOOP_ERROR_THRESHOLD_RAD,
            "threshold_changed": False,
            "north_boundary_assignment": "pixel centre inside official polygon",
            "attribution_scope": "measurable North Jakarta pixels with saved n_loop_err > 0",
            "pair_and_acquisition_ranks_are_participation_not_unique_causation": True,
        },
        "reproduction_gate": {
            "passed": exact_reproduction,
            "whole_grid_pixels": int(height * width),
            "different_pixels": int((difference != 0).sum()),
            "max_absolute_count_difference": int(np.abs(difference).max()),
            "saved_n_loop_err_max": int(expected_counts.max()),
            "reconstructed_n_loop_err_max": int(reconstructed.max()),
        },
        "network": {
            "checkpoint_interferograms": len(unwrapped),
            "step11_rejected_interferograms": len(step11_bad),
            "step11_network_interferograms": len(step11_network),
            "triangles_before_step12_skip": len(all_loops),
            "triangles_skipped_for_step12_rejections": skipped_step12_loops,
            "retained_triangles_evaluated": len(loop_records),
        },
        "north_jakarta": {
            "boundary_pixel_centres": int(north_inside.sum()),
            "measurable_pixel_centres": int(measurable_north.sum()),
            "measurable_loop_failed_pixels": int(loop_failed_north.sum()),
            "total_loop_error_pixel_events": total_north_error_events,
            "loops_with_at_least_one_north_error": int(
                sum(value > 0 for value in loop_event_values)
            ),
            "loop_event_concentration": {
                "top_1_share": _top_share(loop_event_values, 1),
                "top_5_share": _top_share(loop_event_values, 5),
                "top_10_share": _top_share(loop_event_values, 10),
                "top_20_share": _top_share(loop_event_values, 20),
            },
            "error_phase_cycle_diagnostic": {
                "event_count": int(all_north_error_phase.size),
                "median_absolute_error_phase_rad": float(
                    np.median(all_north_error_phase)
                ),
                "fraction_within_0_5_rad_of_integer_2pi": float(
                    np.mean(distance_to_integer_cycle <= 0.5)
                ),
                "fraction_within_1_0_rad_of_integer_2pi": float(
                    np.mean(distance_to_integer_cycle <= 1.0)
                ),
                "nearest_integer_cycle_counts": {
                    str(int(value)): int(frequency)
                    for value, frequency in zip(
                        cycle_count_values, cycle_count_frequencies
                    )
                },
                "interpretation": (
                    "Concentration near non-zero integer multiples of 2pi is "
                    "consistent with unwrapping branch ambiguity; it is not by "
                    "itself proof of which interferogram edge is wrong."
                ),
            },
        },
        "top_retained_loops": top_loops,
        "top_interferogram_participation": top_pairs,
        "top_acquisition_participation": top_acquisitions,
        "interpretation_guard": (
            "A non-zero closure residual belongs to a three-interferogram triangle; "
            "these rankings cannot uniquely assign the fault to one edge or acquisition."
        ),
        "outputs": {
            "loops": loop_path.name,
            "loops_sha256": sha256_file(loop_path),
            "pairs": pair_path.name,
            "pairs_sha256": sha256_file(pair_path),
            "acquisitions": acquisition_path.name,
            "acquisitions_sha256": sha256_file(acquisition_path),
            "plot": plot_path.name,
            "plot_sha256": sha256_file(plot_path),
        },
    }
    summary_path = output_dir / "v9_north_retained_loop_attribution_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    summary["outputs"].update(
        {"summary": summary_path.name, "summary_sha256": sha256_file(summary_path)}
    )
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--checkpoint-checksum", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--results-archive", required=True, type=Path)
    parser.add_argument("--qc-summary", required=True, type=Path)
    parser.add_argument("--official-boundary", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    arguments = _parse_args()
    summary = run(
        checkpoint_path=arguments.checkpoint,
        checkpoint_checksum_path=arguments.checkpoint_checksum,
        inventory_path=arguments.inventory,
        results_archive_path=arguments.results_archive,
        qc_summary_path=arguments.qc_summary,
        official_boundary_path=arguments.official_boundary,
        output_dir=arguments.output_dir,
    )
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
