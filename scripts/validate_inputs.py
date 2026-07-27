"""Validate raw project inputs and optionally emit a JSON report."""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import ANALYSIS_YEAR, RAW_EMBEDDINGS_DIR, RAW_INSAR_DIR
from src.m2_embedding_extraction import find_embedding_files
from src.utils.input_validation import (
    discover_insar_inputs,
    raster_summary,
    validate_insar_value_domains,
    validate_matched_insar_grids,
)


def build_report() -> dict:
    embeddings = find_embedding_files(
        RAW_EMBEDDINGS_DIR, year=ANALYSIS_YEAR
    )
    if len(embeddings) != 1:
        raise ValueError(
            f"Expected exactly one embedding file for {ANALYSIS_YEAR}; "
            f"found {embeddings}"
        )
    insar = discover_insar_inputs(RAW_INSAR_DIR)
    validate_matched_insar_grids(insar)
    validate_insar_value_domains(insar)
    return {
        "status": "valid",
        "embeddings": [
            raster_summary(path, include_values=False) for path in embeddings
        ],
        "insar": {
            role: (
                raster_summary(path, include_values=True)
                if path is not None else None
            )
            for role, path in insar.items()
        },
    }


def cli(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate embedding and matched raw InSAR inputs"
    )
    parser.add_argument(
        "--json", dest="json_path",
        help="Write the complete validation report to this JSON path",
    )
    args = parser.parse_args(argv)

    report = build_report()
    if args.json_path:
        output_dir = os.path.dirname(os.path.abspath(args.json_path))
        os.makedirs(output_dir, exist_ok=True)
        temp_path = args.json_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
        os.replace(temp_path, args.json_path)

    print("Input validation passed.")
    print(f"  Embedding files: {len(report['embeddings'])}")
    for role, metadata in report["insar"].items():
        print(f"  {role}: {metadata['path'] if metadata else 'not supplied'}")
    if args.json_path:
        print(f"  JSON report: {os.path.abspath(args.json_path)}")
    return report


if __name__ == "__main__":
    cli()
