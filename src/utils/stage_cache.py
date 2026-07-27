"""Config-fingerprint cache validation for the pipeline stage cascade.

Drop into src/utils/stage_cache.py.

Solves, in one mechanism:
  2.1  cluster cache ignoring requested k        (k is a fingerprinted param)
  2.2  calibration cache surviving a re-cluster  (labels raster is a
       fingerprinted *input*: its mtime/size change invalidates `cal`)
  2.3  existence-only invalidation generally     (any settings change in a
       stage's declared param set invalidates that stage)
  2.4  method mislabeling                        (requested vs used method are
       both recorded in the sidecar)
  NEW  CLUSTER_EXPOSURE bound to stale labels    (exposure dict is an m4b
       param AND the labels raster is an m4b input)

Design: each stage output gets a JSON sidecar `<output>.cachemeta.json`
recording (a) a hash of the settings values that stage depends on and
(b) the identity (path, size, mtime_ns) of its input rasters. A cache "hit"
requires: output exists, sidecar exists, param fingerprint matches, and all
input identities match. Anything else is a miss with a logged reason, so a
mismatch behaves exactly like --force for that stage (and therefore cascades,
because downstream stages list this stage's output among their inputs).

Integration into run_full_pipeline.py (per stage):

    from src.utils.stage_cache import cache_valid, write_sidecar, stage_params

    params = stage_params("m4", method=resolved_method, k=resolved_k)
    ok, reason = cache_valid(labels_path, params, inputs=[norm_emb_path])
    if ok and not forced:
        logger.info(f"[m4] cache hit: {labels_path}")
    else:
        logger.info(f"[m4] recomputing ({reason})")
        ... run stage ...
        write_sidecar(labels_path, params, inputs=[norm_emb_path],
                      extra={"requested_method": requested_method,
                             "used_method": used_method})

Notes:
- Values must be JSON-serializable after `default=str`; dicts/lists/ranges
  from settings.py are fine.
- mtime_ns+size identity is deliberate (hashing multi-GB rasters per run is
  wasteful). If you copy outputs around, prefer `cp -p` / preserve mtimes.
- `stage_params` centralizes which settings each stage depends on, so adding
  a new tunable means touching exactly one table.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

SIDECAR_SUFFIX = ".cachemeta.json"
SIDECAR_SCHEMA_VERSION = 2


# --------------------------------------------------------------------------
# Stage -> settings dependency table.
# Adjust names to match config/settings.py exactly; unknown names raise
# immediately (fail loud, not silently fingerprint nothing).
# --------------------------------------------------------------------------
_STAGE_SETTINGS: dict[str, list[str]] = {
    "m1": [
        "ACTIVE_ROI", "COMMON_RESOLUTION", "COMMON_CRS",
        "INSAR_VELOCITY_IS_LOS", "INSAR_INCIDENCE_ANGLE_DEG",
        "INSAR_NODATA_VALUES", "INSAR_VSTD_NODATA_VALUES",
        "INSAR_RESAMPLING", "COHERENCE_THRESHOLD",
        "INSAR_VSTD_THRESHOLD", "INSAR_VSTD_SWEEP_THRESHOLDS",
    ],
    "m2": [
        "ACTIVE_ROI", "COMMON_RESOLUTION", "COMMON_CRS",
        "NORMALIZATION_METHOD", "ANALYSIS_YEAR",
    ],
    "m3": [
        "ACTIVE_ROI", "COMMON_RESOLUTION", "COMMON_CRS",
        "INSAR_RESAMPLING",
    ],
    "m4": [
        "RANDOM_STATE", "SAMPLE_FRACTION",
        "MAX_CLUSTERING_SAMPLES", "SILHOUETTE_MAX_SAMPLES",
        "KMEANS_BATCH_SIZE", "K_RANGE",
        "HDBSCAN_MIN_CLUSTER_SIZE", "HDBSCAN_MIN_SAMPLES",
        "HDBSCAN_MAX_FIT_SAMPLES", "HDBSCAN_PCA_COMPONENTS",
        "HDBSCAN_MAX_NOISE_FRACTION", "HDBSCAN_MIN_USABLE_CLUSTERS",
        "HDBSCAN_FALLBACK_K",
    ],
    "cal": [
        "CALIBRATION_MIN_CLUSTER_PIXELS", "CALIBRATION_MAX_SHIFT",
        "CALIBRATION_CANDIDATE_TOLERANCE",
    ],
    "m4b": [
        "SUBSIDENCE_THRESHOLDS", "UPLIFT_REPORT_THRESHOLD",
        "MIN_CLUSTER_VELOCITY_COVERAGE_PCT",
        "CLUSTER_EXPOSURE", "DEFAULT_EXPOSURE", "EXPOSURE_RISK_MATRIX",
    ],
    "m5": [
        "EXPOSURE_RISK_MATRIX", "RISK_COLORMAP",
    ],
}


def stage_params(stage: str, settings_module=None, **runtime) -> dict:
    """Collect the fingerprinted parameter dict for a stage.

    Pulls the stage's declared settings from config.settings (or an injected
    module, for tests) and merges runtime-resolved values (e.g. method=,
    k=) which take precedence and are also fingerprinted.
    """
    if settings_module is None:
        from config import settings as settings_module  # type: ignore
    if stage not in _STAGE_SETTINGS:
        raise KeyError(f"Unknown stage {stage!r}; add it to _STAGE_SETTINGS")
    params: dict = {}
    for name in _STAGE_SETTINGS[stage]:
        if not hasattr(settings_module, name):
            raise AttributeError(
                f"settings.{name} declared for stage {stage!r} but missing "
                "from config/settings.py - fix the table or the settings file"
            )
        params[name] = getattr(settings_module, name)
    params.update(runtime)
    params["__stage__"] = stage
    return params


# --------------------------------------------------------------------------
# Core mechanics
# --------------------------------------------------------------------------

def config_fingerprint(params: dict) -> str:
    canon = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def file_identity(path: str) -> dict:
    st = os.stat(path)
    return {"path": os.path.abspath(path),
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns}


def sidecar_path(output_path: str) -> str:
    return output_path + SIDECAR_SUFFIX


def write_sidecar(output_path: str, params: dict,
                  inputs: Optional[Iterable[str]] = None,
                  extra: Optional[dict] = None) -> str:
    meta = {
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "fingerprint": config_fingerprint(params),
        "params": json.loads(json.dumps(params, sort_keys=True, default=str)),
        "inputs": [file_identity(p) for p in (inputs or [])],
    }
    if extra:
        meta["extra"] = extra
    sp = sidecar_path(output_path)
    temp_path = sp + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    os.replace(temp_path, sp)
    return sp


def cache_valid(output_path: str, params: dict,
                inputs: Optional[Iterable[str]] = None) -> tuple[bool, str]:
    """Return (hit, reason). Any miss reason means: recompute this stage."""
    if not os.path.exists(output_path):
        return False, "output missing"
    sp = sidecar_path(output_path)
    if not os.path.exists(sp):
        return False, "no cache sidecar (pre-fingerprint output)"
    try:
        with open(sp, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"unreadable sidecar ({exc})"

    if meta.get("schema_version") != SIDECAR_SCHEMA_VERSION:
        return False, (
            f"sidecar schema changed: {meta.get('schema_version')!r} -> "
            f"{SIDECAR_SCHEMA_VERSION}"
        )

    if meta.get("fingerprint") != config_fingerprint(params):
        changed = _diff_params(meta.get("params", {}), params)
        return False, f"config changed: {changed or 'unknown keys'}"

    recorded = {i["path"]: i for i in meta.get("inputs", [])}
    current_paths = [os.path.abspath(p) for p in (inputs or [])]
    recorded_paths = set(recorded)
    current_path_set = set(current_paths)
    if recorded_paths != current_path_set:
        added = sorted(current_path_set - recorded_paths)
        removed = sorted(recorded_paths - current_path_set)
        details = []
        if added:
            details.append(f"added: {', '.join(added)}")
        if removed:
            details.append(f"removed: {', '.join(removed)}")
        return False, f"input set changed ({'; '.join(details)})"

    for ap in current_paths:
        if ap not in recorded:
            return False, f"input not previously recorded: {ap}"
        if not os.path.exists(ap):
            return False, f"input missing: {ap}"
        cur = file_identity(ap)
        old = recorded[ap]
        if (cur["size"], cur["mtime_ns"]) != (old["size"], old["mtime_ns"]):
            return False, f"input changed since cache was written: {ap}"
    return True, "cache valid"


def _diff_params(old: dict, new: dict) -> str:
    new_canon = json.loads(json.dumps(new, sort_keys=True, default=str))
    keys = sorted(set(old) | set(new_canon))
    changed = [k for k in keys if old.get(k) != new_canon.get(k)]
    return ", ".join(changed)
