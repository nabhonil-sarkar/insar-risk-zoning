"""Raw-input discovery and validation shared by the pipeline and QA CLI."""

from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np
import rasterio


PROCESSED_MARKERS = (
    "calibrated", "aligned", "vertical", "masked", "reproj",
    "nodata_masked",
)
AUX_ROLE_MARKERS = {
    "coherence": ("coh",),
    "vstd": ("vstd",),
    "n_unw": ("n_unw",),
}


def _period_token(name: str) -> str | None:
    match = re.search(r"(20\d{2})[_-](20\d{2})", name)
    return f"{match.group(1)}_{match.group(2)}" if match else None


def discover_insar_inputs(directory: str) -> dict[str, str | None]:
    """
    Return one unambiguous raw file per InSAR role.

    Processed-product names and multiple candidates fail loudly. When period
    tokens are present, every layer must carry the same token.
    """
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"InSAR input directory not found: {root}")
    all_tifs = sorted(
        p for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in {".tif", ".tiff"}
    )
    if not all_tifs:
        raise FileNotFoundError(f"No InSAR GeoTIFFs found in {root}")

    contaminated = [
        p.name for p in all_tifs
        if any(marker in p.name.lower() for marker in PROCESSED_MARKERS)
    ]
    if contaminated:
        raise ValueError(
            "Processed-product filenames are not allowed in raw InSAR "
            f"inputs: {contaminated}"
        )

    roles: dict[str, list[Path]] = {
        role: [
            p for p in all_tifs
            if any(marker in p.name.lower() for marker in markers)
        ]
        for role, markers in AUX_ROLE_MARKERS.items()
    }
    aux_paths = {p for paths in roles.values() for p in paths}
    velocity = [
        p for p in all_tifs
        if p not in aux_paths and "synthetic" not in p.name.lower()
    ]
    roles["velocity"] = velocity

    if len(velocity) != 1:
        raise ValueError(
            f"Expected exactly one velocity GeoTIFF; found "
            f"{[p.name for p in velocity]}"
        )
    ambiguous = {
        role: [p.name for p in paths]
        for role, paths in roles.items()
        if role != "velocity" and len(paths) > 1
    }
    if ambiguous:
        raise ValueError(
            f"Expected at most one quality GeoTIFF per role: {ambiguous}"
        )

    resolved = {
        role: str(paths[0]) if paths else None
        for role, paths in roles.items()
    }
    period_by_role = {
        role: _period_token(Path(path).name)
        for role, path in resolved.items() if path is not None
    }
    nonempty_tokens = {
        token for token in period_by_role.values() if token is not None
    }
    if len(nonempty_tokens) > 1:
        raise ValueError(
            f"InSAR layers carry mismatched period tokens: "
            f"{sorted(nonempty_tokens)}"
        )
    if nonempty_tokens:
        missing_period = sorted(
            role for role, token in period_by_role.items() if token is None
        )
        if missing_period:
            raise ValueError(
                "Some InSAR layers omit the period token while others "
                f"declare one: {missing_period}"
            )
    return resolved


def raster_summary(path: str, include_values: bool = True) -> dict:
    """Return JSON-serializable raster metadata and optional band-1 stats."""
    with rasterio.open(path) as src:
        nodata = src.nodata
        if isinstance(nodata, (float, np.floating)) and not np.isfinite(nodata):
            nodata = None
        summary = {
            "path": os.path.abspath(path),
            "width": src.width,
            "height": src.height,
            "count": src.count,
            "dtypes": list(src.dtypes),
            "crs": str(src.crs),
            "transform": list(src.transform),
            "bounds": list(src.bounds),
            "resolution": list(src.res),
            "nodata": nodata,
            "tags": src.tags(),
        }
        if include_values and src.count:
            values = src.read(1)
            finite = np.isfinite(values)
            selected = values[finite]
            summary["finite_pixels"] = int(finite.sum())
            summary["nan_pixels"] = int(np.isnan(values).sum())
            summary["zero_pixels"] = int((values == 0).sum())
            summary["min"] = (
                float(selected.min()) if selected.size else None
            )
            summary["median"] = (
                float(np.median(selected)) if selected.size else None
            )
            summary["max"] = (
                float(selected.max()) if selected.size else None
            )
    return summary


def validate_matched_insar_grids(inputs: dict[str, str | None]) -> None:
    """Require every supplied InSAR layer to share one native grid."""
    supplied = {
        role: path for role, path in inputs.items() if path is not None
    }
    if not supplied:
        raise ValueError("No InSAR layers supplied")
    reference_role = "velocity"
    reference = raster_summary(supplied[reference_role], include_values=False)
    grid_keys = ("width", "height", "crs", "transform")
    for role, path in supplied.items():
        current = raster_summary(path, include_values=False)
        differences = [
            key for key in grid_keys if current[key] != reference[key]
        ]
        if differences:
            raise ValueError(
                f"{role} does not match the native velocity grid; "
                f"different fields: {differences}"
            )


def validate_insar_value_domains(inputs: dict[str, str | None]) -> None:
    """Validate band counts and basic physical domains for supplied layers."""
    for role, path in inputs.items():
        if path is None:
            continue
        summary = raster_summary(path, include_values=True)
        if summary["count"] != 1:
            raise ValueError(
                f"{role} must be single-band; found {summary['count']} bands"
            )
        if summary["crs"] in {"None", ""}:
            raise ValueError(f"{role} has no CRS: {path}")
        minimum = summary["min"]
        maximum = summary["max"]
        if role in {"vstd", "n_unw"} and minimum is not None and minimum < 0:
            raise ValueError(
                f"{role} contains negative values (min={minimum})"
            )
        if role == "coherence" and minimum is not None:
            if minimum < 0 or maximum > 1:
                raise ValueError(
                    "coherence values must lie in [0, 1]; "
                    f"range=[{minimum}, {maximum}]"
                )
