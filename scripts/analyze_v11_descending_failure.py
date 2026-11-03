"""Attribute the frozen v11 North-Jakarta failure without changing its decision."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tarfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import matplotlib.pyplot as plt
import numpy as np
from affine import Affine
from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform as shapely_transform, unary_union


EXPECTED_ARCHIVE_SHA256 = (
    "cfa62c3031527b94f2098c938a797fe95ab06f4f77aa6a63d650af8d3874d856"
)
EXPECTED_BOUNDARY_SHA256 = (
    "7bb4dd0589cec8bd64e8930c94b1835116701b6148f7b7de183e61196593c540"
)
EXPECTED_CELLS = 618


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe archive member: {member.name}")
    return members


def member_bytes(
    archive: tarfile.TarFile, members: list[tarfile.TarInfo], suffix: str
) -> bytes:
    matches = [member for member in members if member.isfile() and member.name.endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"Expected one archive member ending {suffix!r}, found {len(matches)}")
    stream = archive.extractfile(matches[0])
    if stream is None:
        raise ValueError(f"Could not read archive member: {matches[0].name}")
    return stream.read()


def parse_par(payload: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in payload.decode("utf-8", errors="replace").splitlines():
        fields = line.replace(":", " ").split()
        if len(fields) >= 2:
            values[fields[0]] = fields[1]
    required = {"width", "nlines", "corner_lon", "corner_lat", "post_lon", "post_lat"}
    if not required.issubset(values):
        raise ValueError(f"EQA.dem_par lacks fields: {sorted(required - values.keys())}")
    return values


def local_checks(row: dict[str, Any], global_span_fraction: float) -> dict[str, bool]:
    return {
        "image_fraction": row["image_fraction"] >= 0.90,
        "requested_window_span": row["temporal_span_fraction"] >= 0.95,
        "catalogue_relative_span": (
            row["temporal_span_fraction"] / global_span_fraction >= 0.95
        ),
        "edge_to_image_ratio": row["edge_to_image_ratio"] >= 2.0,
        "no_bridges": row["all_finite_retained_bridge_count"] == 0,
        "complete_triangle_coverage": (
            row["all_finite_retained_edges_without_triangle_count"] == 0
        ),
        "zero_loop_errors": row["n_loop_err"] == 0,
    }


def largest_patch(
    passing: set[tuple[int, int]], cell_areas: dict[tuple[int, int], float]
) -> tuple[int, float, int]:
    unseen = set(passing)
    components: list[set[tuple[int, int]]] = []
    while unseen:
        stack = [min(unseen)]
        component: set[tuple[int, int]] = set()
        while stack:
            cell = stack.pop()
            if cell in component or cell not in unseen:
                continue
            component.add(cell)
            unseen.remove(cell)
            row, col = cell
            stack.extend(
                (row + dr, col + dc)
                for dr in (-1, 0, 1)
                for dc in (-1, 0, 1)
                if (dr or dc) and (row + dr, col + dc) in unseen
            )
        components.append(component)
    areas = [sum(cell_areas[cell] for cell in component) for component in components]
    total = sum(areas)
    if not areas or total == 0:
        return 0, 0.0, 0
    largest_index = int(np.argmax(areas))
    return len(components), areas[largest_index] / total, len(components[largest_index])


def plot_boundary(axis: Any, geometry: Any, **kwargs: Any) -> None:
    polygons = geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]
    for polygon in polygons:
        x, y = polygon.exterior.xy
        axis.plot(x, y, **kwargs)


def analyze(archive_path: Path, output_dir: Path) -> dict[str, Any]:
    archive_sha = sha256_file(archive_path)
    if archive_sha != EXPECTED_ARCHIVE_SHA256:
        raise ValueError(f"Archive SHA-256 mismatch: {archive_sha}")

    with tarfile.open(archive_path, "r:gz") as archive:
        members = safe_members(archive)
        ledger = json.loads(member_bytes(archive, members, "_north_pixel_ledger.json"))
        gate = json.loads(member_bytes(archive, members, "_network_and_north_gate.json"))
        boundary_bytes = member_bytes(archive, members, "dki_kelurahan_official.geojson")
        boundary = json.loads(boundary_bytes)
        par = parse_par(member_bytes(archive, members, "/info/EQA.dem_par"))

    if hashlib.sha256(boundary_bytes).hexdigest() != EXPECTED_BOUNDARY_SHA256:
        raise ValueError("Official boundary checksum mismatch")
    if len(ledger) != EXPECTED_CELLS or gate.get("passed") is not False:
        raise ValueError("Archive does not contain the frozen failed 618-cell v11 result")
    if gate["total_interferograms"] != 349 or gate["total_images"] != 76:
        raise ValueError("Frozen v11 network identity changed")

    width, length = int(par["width"]), int(par["nlines"])
    post_lon, post_lat = float(par["post_lon"]), float(par["post_lat"])
    corner_lon, corner_lat = float(par["corner_lon"]), float(par["corner_lat"])
    transform = Affine(
        post_lon,
        0,
        corner_lon - post_lon / 2,
        0,
        post_lat,
        corner_lat - post_lat / 2,
    )

    district_parts: dict[str, list[Any]] = {}
    for feature in boundary["features"]:
        if "UTARA" not in str(feature["properties"].get("wadmkk", "")).upper():
            continue
        district = str(feature["properties"]["wadmkc"]).strip()
        district_parts.setdefault(district, []).append(shape(feature["geometry"]))
    districts_wgs84 = {name: unary_union(parts) for name, parts in district_parts.items()}
    if len(districts_wgs84) != 6:
        raise ValueError(f"Expected six North districts, found {sorted(districts_wgs84)}")
    to_projected = Transformer.from_crs(4326, 32748, always_xy=True).transform
    districts_projected = {
        name: shapely_transform(to_projected, geometry)
        for name, geometry in districts_wgs84.items()
    }

    district_cell_areas: dict[tuple[int, int], dict[str, float]] = {}
    cell_areas: dict[tuple[int, int], float] = {}
    for item in ledger:
        row, col = int(item["row"]), int(item["col"])
        left, top = transform * (col, row)
        right, bottom = transform * (col + 1, row + 1)
        cell_wgs84 = box(min(left, right), min(bottom, top), max(left, right), max(bottom, top))
        cell_projected = shapely_transform(to_projected, cell_wgs84)
        areas = {
            name: cell_projected.intersection(geometry).area
            for name, geometry in districts_projected.items()
        }
        areas = {name: area for name, area in areas.items() if area > 0}
        district_cell_areas[(row, col)] = areas
        cell_areas[(row, col)] = sum(areas.values())

    total_area = sum(cell_areas.values())
    recorded_total = gate["north_jakarta_gate"]["total_area_m2"]
    if not math.isclose(total_area, recorded_total, rel_tol=0, abs_tol=1e-5):
        raise ValueError(f"North area reconstruction changed: {total_area} != {recorded_total}")

    global_span = gate["global_network"]["temporal_span_fraction"]
    checks = [local_checks(item, global_span) for item in ledger]
    gate_names = list(checks[0])
    gate_counts = {
        name: {
            "passing_cells": sum(result[name] for result in checks),
            "passing_cell_fraction": sum(result[name] for result in checks) / len(ledger),
            "passing_area_fraction": sum(
                cell_areas[(int(item["row"]), int(item["col"]))]
                for item, result in zip(ledger, checks)
                if result[name]
            )
            / total_area,
        }
        for name in gate_names
    }

    non_temporal_names = [
        "image_fraction",
        "edge_to_image_ratio",
        "no_bridges",
        "complete_triangle_coverage",
        "zero_loop_errors",
    ]
    passing_non_temporal = {
        (int(item["row"]), int(item["col"]))
        for item, result in zip(ledger, checks)
        if all(result[name] for name in non_temporal_names)
    }
    passing_catalogue_relative = {
        (int(item["row"]), int(item["col"]))
        for item, result in zip(ledger, checks)
        if all(result[name] for name in [*non_temporal_names, "catalogue_relative_span"])
    }

    district_totals = {
        name: sum(areas.get(name, 0.0) for areas in district_cell_areas.values())
        for name in districts_projected
    }

    def summarize_counterfactual(passing: set[tuple[int, int]]) -> dict[str, Any]:
        passing_area = sum(cell_areas[cell] for cell in passing)
        district_passing = {
            name: sum(district_cell_areas[cell].get(name, 0.0) for cell in passing)
            for name in districts_projected
        }
        component_count, largest_share, largest_cells = largest_patch(passing, cell_areas)
        district_fractions = {
            name: district_passing[name] / district_totals[name]
            for name in districts_projected
        }
        return {
            "passing_cells": len(passing),
            "passing_cell_fraction": len(passing) / len(ledger),
            "passing_area_m2": passing_area,
            "passing_area_fraction": passing_area / total_area,
            "district_area_fractions": district_fractions,
            "connected_patch_count": component_count,
            "largest_8_connected_patch_cells": largest_cells,
            "largest_8_connected_patch_fraction_of_passing_area": largest_share,
            "would_meet_spatial_continuation_thresholds": (
                passing_area / total_area >= 0.50
                and all(value >= 0.25 for value in district_fractions.values())
                and largest_share >= 0.75
            ),
        }

    failure_combinations: Counter[tuple[str, ...]] = Counter()
    for result in checks:
        failures = tuple(name for name in non_temporal_names if not result[name])
        failure_combinations[failures] += 1

    report = {
        "source_archive": archive_path.name,
        "source_archive_sha256": archive_sha,
        "analysis_role": "descriptive_non_decisional_failure_attribution",
        "frozen_v11_decision": "failed_unchanged",
        "frozen_gate_failures": gate["gate_failures"],
        "catalogue": {
            "images": gate["total_images"],
            "interferograms": gate["total_interferograms"],
            "retained_interferograms": gate["global_network"]["lcc_interferograms"],
            "first_image": gate["global_network"]["lcc_images"][0],
            "last_image": gate["global_network"]["lcc_images"][-1],
            "requested_window_span_fraction": global_span,
        },
        "north_cells": len(ledger),
        "north_area_m2": total_area,
        "individual_gate_results": gate_counts,
        "non_temporal_counterfactual": {
            "definition": "All frozen local gates except requested-window temporal span",
            **summarize_counterfactual(passing_non_temporal),
        },
        "catalogue_relative_counterfactual": {
            "definition": "All non-temporal gates plus >=95% of the available catalogue span",
            **summarize_counterfactual(passing_catalogue_relative),
        },
        "non_temporal_failure_combinations": [
            {"failures": list(failures), "cells": count}
            for failures, count in failure_combinations.most_common()
        ],
        "interpretation": [
            "The preregistered 2020-2023 v11 continuation decision remains failed.",
            "Zero frozen qualifying cells was forced by the catalogue ending in June 2023, not by temporal-network fragmentation.",
            "The shorter-span counterfactual is descriptive and may justify a separately preregistered branch; it cannot retroactively pass v11.",
            "No inversion, velocity, subsidence, hazard, or risk claim is authorized by this report.",
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "v11_desc47_north_failure_attribution.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    status = np.full((length, width), np.nan, dtype=float)
    for item in ledger:
        cell = (int(item["row"]), int(item["col"]))
        status[cell] = 2 if cell in passing_non_temporal else 1
    west, north = transform * (0, 0)
    east, south = transform * (width, length)
    figure, axis = plt.subplots(figsize=(9, 6), constrained_layout=True)
    image = axis.imshow(
        status,
        extent=[west, east, south, north],
        origin="upper",
        vmin=1,
        vmax=2,
        cmap=plt.matplotlib.colors.ListedColormap(["#c95f45", "#2b8cbe"]),
        interpolation="nearest",
    )
    for geometry in districts_wgs84.values():
        plot_boundary(axis, geometry, color="black", linewidth=0.7)
    north_geometry = unary_union(list(districts_wgs84.values()))
    min_x, min_y, max_x, max_y = north_geometry.bounds
    axis.set_xlim(min_x - 0.01, max_x + 0.01)
    axis.set_ylim(min_y - 0.01, max_y + 0.01)
    colorbar = figure.colorbar(image, ax=axis, ticks=[1.25, 1.75], fraction=0.04)
    colorbar.ax.set_yticklabels(["Fails ≥1 non-temporal gate", "Passes all non-temporal gates"])
    axis.set_title("V11 North Jakarta descriptive attribution\nFrozen 2020–2023 decision remains failed")
    axis.set_xlabel("Longitude")
    axis.set_ylabel("Latitude")
    figure_path = output_dir / "v11_desc47_north_non_temporal_gate_map.png"
    figure.savefig(figure_path, dpi=180)
    plt.close(figure)

    result = {
        "report": str(report_path),
        "report_sha256": sha256_file(report_path),
        "map": str(figure_path),
        "map_sha256": sha256_file(figure_path),
        "summary": report["non_temporal_counterfactual"],
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    arguments = parser.parse_args()
    print(json.dumps(analyze(arguments.archive, arguments.output_dir), indent=2))


if __name__ == "__main__":
    main()
