"""Attribute v9 global pair/loop rejections and assess North-specific evidence limits."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import tarfile
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

from scripts.build_v9_strict_mask import EXPECTED_ARCHIVE_SHA256 as RESULTS_ARCHIVE_SHA256

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


EXPECTED_DIAGNOSTIC_SHA256 = (
    "b5f31f8e5d88c6b27394af357687535025503f963c856b94a63fc76659311c68"
)
ROOT = "TS_GEOCml5clip_reunw_mp/"
PAIR_LISTS = {
    "step11": "info/11bad_ifg.txt",
    "step12_loop": "12loop/bad_ifg_loop.txt",
    "step12_noref": "12loop/bad_ifg_noref.txt",
    "step12_loopref": "12loop/bad_ifg_loopref.txt",
    "step12_all": "info/12bad_ifg.txt",
    "step12_candidate": "info/12bad_ifg_cand.txt",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_ifg_stats(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) < 5:
            raise ValueError(f"Malformed interferogram-statistics row: {line}")
        pair = fields[0]
        first, second = pair.split("_")
        records.append(
            {
                "pair": pair,
                "first": first,
                "second": second,
                "perpendicular_baseline": float(fields[1]),
                "temporal_baseline_days": int(fields[2]),
                "unwrapped_coverage": float(fields[3]),
                "average_coherence": float(fields[4]),
            }
        )
    return records


def _read_text(bundle: tarfile.TarFile, relative: str) -> str:
    stream = bundle.extractfile(ROOT + relative)
    if stream is None:
        raise ValueError(f"Diagnostic archive is missing {relative}")
    return stream.read().decode("utf-8", errors="replace")


def _read_list(bundle: tarfile.TarFile, relative: str) -> list[str]:
    return [
        line.strip()
        for line in _read_text(bundle, relative).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _summary_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"count": 0}
    return {
        "count": len(records),
        "temporal_baseline_days": {
            "min": int(min(item["temporal_baseline_days"] for item in records)),
            "median": float(np.median([item["temporal_baseline_days"] for item in records])),
            "max": int(max(item["temporal_baseline_days"] for item in records)),
        },
        "unwrapped_coverage": {
            "min": float(min(item["unwrapped_coverage"] for item in records)),
            "median": float(np.median([item["unwrapped_coverage"] for item in records])),
            "max": float(max(item["unwrapped_coverage"] for item in records)),
        },
        "average_coherence": {
            "min": float(min(item["average_coherence"] for item in records)),
            "median": float(np.median([item["average_coherence"] for item in records])),
            "max": float(max(item["average_coherence"] for item in records)),
        },
    }


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        raise ValueError(f"No records to write: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def _plot_acquisition_ranking(path: Path, records: list[dict[str, Any]]) -> None:
    selected = [record for record in records if record["step11_or_step12_rejected_pairs"]]
    selected.sort(
        key=lambda item: (-item["step11_or_step12_rejected_pairs"], item["acquisition"])
    )
    selected = selected[:20]
    labels = [item["acquisition"] for item in reversed(selected)]
    step11 = [item["step11_rejected_pairs"] for item in reversed(selected)]
    step12 = [item["step12_rejected_pairs"] for item in reversed(selected)]
    figure, axis = plt.subplots(figsize=(9.2, 7.0), constrained_layout=True)
    positions = np.arange(len(labels))
    axis.barh(positions, step11, color="#4c78a8", label="Step 11")
    axis.barh(positions, step12, left=step11, color="#e45756", label="Step 12")
    axis.set_yticks(positions, labels)
    axis.set_xlabel("Incident rejected interferograms")
    axis.set_ylabel("Acquisition date")
    axis.set_title("V9 global rejection concentration by acquisition")
    axis.grid(axis="x", linewidth=0.4, alpha=0.35)
    axis.legend(loc="lower right")
    figure.text(
        0.01,
        0.005,
        "Global pair-level attribution; it does not identify the retained loops causing North Jakarta pixel errors.",
        fontsize=8,
        color="#333333",
    )
    figure.savefig(path, dpi=180, facecolor="white")
    plt.close(figure)


def run(
    diagnostic_archive: Path,
    checksum_file: Path,
    output_dir: Path,
) -> dict[str, Any]:
    for path in (diagnostic_archive, checksum_file):
        if not path.is_file():
            raise FileNotFoundError(path)
    supplied_sha = checksum_file.read_text(encoding="utf-8").strip().split()[0].lower()
    actual_sha = sha256_file(diagnostic_archive)
    if supplied_sha != EXPECTED_DIAGNOSTIC_SHA256 or actual_sha != EXPECTED_DIAGNOSTIC_SHA256:
        raise ValueError(
            "Step-12 diagnostic archive does not match both the supplied and expected SHA-256"
        )

    with tarfile.open(diagnostic_archive, "r:gz") as bundle:
        pair_lists = {
            role: _read_list(bundle, relative) for role, relative in PAIR_LISTS.items()
        }
        if sorted(pair_lists["step12_all"]) != sorted(
            pair_lists["step12_loop"]
            + pair_lists["step12_noref"]
            + pair_lists["step12_loopref"]
        ):
            raise ValueError("Step-12 reason lists do not partition info/12bad_ifg.txt")
        pair_stats = parse_ifg_stats(_read_text(bundle, "info/11ifg_stats.txt"))
        members = [member.name for member in bundle.getmembers() if member.isfile()]
        loop_preview_counts = {
            category: sum(f"/12loop/{category}/" in name for name in members)
            for category in ("good_loop_png", "bad_loop_cand_png", "bad_loop_png")
        }
        numeric_loop_members = [
            name
            for name in members
            if "/12loop/" in name
            and not name.endswith(".png")
            and name.rsplit("/", 1)[-1]
            not in {
                "loop_info.txt",
                "bad_ifg_loop.txt",
                "bad_ifg_noref.txt",
                "bad_ifg_loopref.txt",
                "loop_ph_rms_masked",
            }
        ]
        removed_step11_images = _read_list(bundle, "info/11removed_image.txt")
        removed_step12_images = _read_list(bundle, "info/12removed_image.txt")

    if len(pair_stats) != 609:
        raise ValueError(f"Expected 609 interferogram statistics, found {len(pair_stats)}")
    stats_by_pair = {record["pair"]: record for record in pair_stats}
    all_known_pairs = set(stats_by_pair)
    for role, pairs in pair_lists.items():
        unknown = sorted(set(pairs) - all_known_pairs)
        if unknown:
            raise ValueError(f"{role} contains unknown interferograms: {unknown[:5]}")

    reason_by_pair: dict[str, str] = {}
    for pair in pair_lists["step11"]:
        reason_by_pair[pair] = "step11_coverage"
    for role in ("step12_loop", "step12_noref", "step12_loopref"):
        for pair in pair_lists[role]:
            if pair in reason_by_pair:
                raise ValueError(f"Pair appears in multiple unique rejection reasons: {pair}")
            reason_by_pair[pair] = role

    pair_records: list[dict[str, Any]] = []
    for pair in sorted(reason_by_pair):
        pair_records.append(stats_by_pair[pair] | {"rejection_reason": reason_by_pair[pair]})

    all_degree = Counter()
    step11_degree = Counter()
    step12_degree = Counter()
    step12_reason_degree: dict[str, Counter[str]] = {
        role: Counter() for role in ("step12_loop", "step12_noref", "step12_loopref")
    }
    for record in pair_stats:
        all_degree.update((record["first"], record["second"]))
    for pair in pair_lists["step11"]:
        step11_degree.update(pair.split("_"))
    for role in step12_reason_degree:
        for pair in pair_lists[role]:
            dates = pair.split("_")
            step12_degree.update(dates)
            step12_reason_degree[role].update(dates)

    acquisition_records: list[dict[str, Any]] = []
    for acquisition in sorted(all_degree):
        rejected = step11_degree[acquisition] + step12_degree[acquisition]
        acquisition_records.append(
            {
                "acquisition": acquisition,
                "all_incident_pairs": all_degree[acquisition],
                "step11_rejected_pairs": step11_degree[acquisition],
                "step12_rejected_pairs": step12_degree[acquisition],
                "step12_loop_pairs": step12_reason_degree["step12_loop"][acquisition],
                "step12_noref_pairs": step12_reason_degree["step12_noref"][acquisition],
                "step12_loopref_pairs": step12_reason_degree["step12_loopref"][acquisition],
                "step11_or_step12_rejected_pairs": rejected,
                "incident_rejection_fraction": rejected / all_degree[acquisition],
            }
        )

    retained_pairs = [record for record in pair_stats if record["pair"] not in reason_by_pair]
    grouped_statistics = {
        "all_609": _summary_statistics(pair_stats),
        "retained_567": _summary_statistics(retained_pairs),
        "step11_8": _summary_statistics(
            [stats_by_pair[pair] for pair in pair_lists["step11"]]
        ),
        "step12_34": _summary_statistics(
            [stats_by_pair[pair] for pair in pair_lists["step12_all"]]
        ),
        "step12_loop_27": _summary_statistics(
            [stats_by_pair[pair] for pair in pair_lists["step12_loop"]]
        ),
        "step12_noref_5": _summary_statistics(
            [stats_by_pair[pair] for pair in pair_lists["step12_noref"]]
        ),
        "step12_loopref_2": _summary_statistics(
            [stats_by_pair[pair] for pair in pair_lists["step12_loopref"]]
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    pair_path = output_dir / "v9_rejected_pair_attribution.csv"
    acquisition_path = output_dir / "v9_acquisition_rejection_attribution.csv"
    plot_path = output_dir / "v9_acquisition_rejection_attribution.png"
    _write_csv(pair_path, pair_records)
    _write_csv(acquisition_path, acquisition_records)
    _plot_acquisition_ranking(plot_path, acquisition_records)

    top_acquisitions = sorted(
        acquisition_records,
        key=lambda item: (-item["step12_rejected_pairs"], item["acquisition"]),
    )[:10]
    summary: dict[str, Any] = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scientific_status": "global_pair_attribution_complete_north_loop_attribution_requires_numeric_stack",
        "source": {
            "diagnostic_archive": diagnostic_archive.name,
            "diagnostic_archive_sha256": actual_sha,
            "checksum_file": checksum_file.name,
            "checksum_file_sha256": sha256_file(checksum_file),
        },
        "census": {
            "interferograms": len(pair_stats),
            "step11_rejected": len(pair_lists["step11"]),
            "step12_rejected": len(pair_lists["step12_all"]),
            "step12_loop": len(pair_lists["step12_loop"]),
            "step12_noref": len(pair_lists["step12_noref"]),
            "step12_loopref": len(pair_lists["step12_loopref"]),
            "step12_candidates_not_removed": len(pair_lists["step12_candidate"]),
            "loop_previews": loop_preview_counts,
            "numeric_per_loop_phase_grids": len(numeric_loop_members),
            "removed_step11_images": removed_step11_images,
            "removed_step12_images": removed_step12_images,
        },
        "pair_group_statistics": grouped_statistics,
        "top_step12_acquisition_concentrations": top_acquisitions,
        "north_jakarta_attribution_limit": {
            "exact_attribution_possible_from_this_archive": False,
            "reason": "the archive retains global loop summaries and rendered PNG previews but no numeric phase grid for each loop",
            "official_algorithm_fact": "n_loop_err counts retained-loop pixels whose absolute referenced loop phase exceeds pi",
            "required_input": "GEOCml5clip_reunw_unfiltered_roi_ml5_mp_20200101_20231231_checkpoint.tar.gz and matching SHA-256",
            "expected_required_input_sha256": "3329cd9c75d5c96e604f0c9b3b950fe127018bfebc06d2c19f9426b3fb234efb",
            "planned_next_method": "recompute retained loop phase from the saved unwrapped stack and aggregate >pi errors within official North Jakarta pixels by loop, interferogram, and acquisition without changing thresholds",
        },
        "outputs": {
            "rejected_pairs": pair_path.name,
            "rejected_pairs_sha256": sha256_file(pair_path),
            "acquisitions": acquisition_path.name,
            "acquisitions_sha256": sha256_file(acquisition_path),
            "plot": plot_path.name,
            "plot_sha256": sha256_file(plot_path),
        },
        "provenance": {
            "licsbas_source_commit": "a145e6c4217b29eb7348ea95630454a099809098",
            "results_archive_expected_sha256": RESULTS_ARCHIVE_SHA256,
        },
    }
    summary_path = output_dir / "v9_pair_loop_attribution_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    summary["outputs"].update(
        {"summary": summary_path.name, "summary_sha256": sha256_file(summary_path)}
    )
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostic-archive", required=True, type=Path)
    parser.add_argument("--checksum-file", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    arguments = _parse_args()
    summary = run(
        diagnostic_archive=arguments.diagnostic_archive,
        checksum_file=arguments.checksum_file,
        output_dir=arguments.output_dir,
    )
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
