"""Build the review-only v13 GNSS/levelling validation request package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from shapely.geometry import shape


EXPECTED_SHA256 = {
    "v13_strict_candidate_footprint_north_jakarta.geojson": (
        "dc5e5a9b5093751120f68e82d116f5af1630d2c3f95368d8003d098ad2d1a5e5"
    ),
    "v13_strict_candidate_footprint_north_jakarta.summary.json": (
        "7f4b86131740ef33ffb905e18faea0234ce8aa8cd48bead2b6dea526149c6af9"
    ),
    "v13_results_audit.json": (
        "775dac65e9793fcbbe5d4fc18c09bcfc90ab2a698b5e6fd11a037abf52b9244b"
    ),
    "v14_reference_sensitivity_audit.json": (
        "6a1e6945df0010821b01c60395771d8890c39bdfc1b0c2eac6a8cbbd374116ae"
    ),
}

FRAME = "047D_09652_111009"
CANDIDATE_START = "2020-01-10"
CANDIDATE_END = "2023-06-11"
STRICT_CELLS = 380
NORTH_AREA_FRACTION = 0.6839029554861018
FROZEN_AREA_M2 = 100_456_701.0359861
PARTS = 21

PROTOCOL_NAME = "v13_ground_validation_protocol.json"
TEMPLATE_NAME = "v13_ground_observation_inventory_template.csv"
REQUEST_NAME = "v13_BIG_ITB_DKI_data_request_draft.md"
MANIFEST_NAME = "v13_ground_validation_package_manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _require_hash(path: Path, expected: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    observed = sha256_file(path)
    if observed != expected.lower():
        raise ValueError(f"SHA-256 mismatch for {path.name}: {observed}")


def validate_footprint(footprint_path: Path, summary_path: Path) -> None:
    collection = json.loads(footprint_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    features = collection.get("features", [])
    if collection.get("type") != "FeatureCollection" or len(features) != 1:
        raise ValueError("Expected one-feature footprint FeatureCollection")
    feature = features[0]
    properties = feature.get("properties", {})
    geometry = shape(feature.get("geometry"))
    if geometry.geom_type != "MultiPolygon" or not geometry.is_valid:
        raise ValueError("Footprint must be a valid MultiPolygon")
    if len(geometry.geoms) != PARTS:
        raise ValueError(f"Footprint part count changed: {len(geometry.geoms)}")
    expected_properties = {
        "candidate_interval": f"{CANDIDATE_START}/{CANDIDATE_END}",
        "frame": FRAME,
        "orbit": "descending",
        "strict_cells": STRICT_CELLS,
        "velocity_values_included": False,
        "absolute_zero_level_validated": False,
        "vertical_subsidence_validated": False,
        "hazard_or_risk_map": False,
    }
    for key, expected in expected_properties.items():
        if properties.get(key) != expected:
            raise ValueError(f"Footprint property changed: {key}")
    expected_summary = {
        "geometry_type": "MultiPolygon",
        "multipolygon_parts": PARTS,
        "strict_cells": STRICT_CELLS,
        "rate_values_included": False,
        "frozen_gate_area_m2": FROZEN_AREA_M2,
        "north_area_fraction": NORTH_AREA_FRACTION,
    }
    for key, expected in expected_summary.items():
        if summary.get(key) != expected:
            raise ValueError(f"Footprint summary changed: {key}")


def protocol_payload(source_hashes: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "package_status": "review_only_not_authorized_for_external_send",
        "scientific_status": "relative_pattern_only",
        "purpose": (
            "Locate and assess date-compatible independent ground observations "
            "that could anchor or reject the v13 descending-LOS zero level."
        ),
        "candidate": {
            "frame": FRAME,
            "orbit": "descending",
            "interval_start": CANDIDATE_START,
            "interval_end": CANDIDATE_END,
            "strict_cells": STRICT_CELLS,
            "north_jakarta_area_fraction": NORTH_AREA_FRACTION,
            "frozen_intersection_area_m2": FROZEN_AREA_M2,
            "absolute_zero_validated": False,
            "vertical_subsidence_validated": False,
            "velocity_values_in_attachment": False,
        },
        "source_sha256": source_hashes,
        "requested_observation_types": [
            "continuous or campaign GNSS coordinate time series",
            "repeated precise levelling observations and benchmark metadata",
            "surface-benchmark displacement observations",
        ],
        "required_metadata": [
            "station or benchmark identifier",
            "longitude, latitude, coordinate reference system, and coordinate epoch",
            "observation epochs or campaign start and end dates",
            "datum and reference frame, including realization",
            "measured component or components and sign convention",
            "units and whether values are positions, displacements, or rates",
            "uncertainty, covariance if available, and confidence convention",
            "equipment, processing method, corrections, and quality flags",
            "offsets, equipment changes, earthquakes, discontinuities, or exclusions",
            "data owner, citation, licence, and redistribution restrictions",
        ],
        "method_specific_requirements": {
            "GNSS": [
                "east, north, and up coordinates or displacements whenever available",
                "raw epochs or time series preferred over a precomputed long-term rate",
                "reference-frame constraints, antenna changes, offsets, and covariance",
            ],
            "levelling": [
                "benchmark coordinates and identifiers",
                "campaign dates, elevation differences, datum, route, and closure metadata",
                "misclosure adjustment, benchmark stability, and uncertainty",
            ],
            "other_monitoring": [
                "measurement principle and physical component",
                "processing provenance and whether the product uses GNSS, levelling, wells, InSAR, or a model",
                "independence from the v13 Sentinel-1 result",
            ],
        },
        "compatibility_screen": {
            "spatial": (
                "Primary anchoring observations must fall within the exact attached "
                "strict footprint. Outside-footprint observations are retained as context only."
            ),
            "temporal": (
                "Use raw epochs or campaign observations to form a common interval within "
                f"{CANDIDATE_START} through {CANDIDATE_END}. Rates from materially different "
                "periods are context only unless a prospective harmonization rule is justified."
            ),
            "reference": (
                "Datum, reference frame, sign, units, offsets, and uncertainty must be explicit."
            ),
            "geometry": (
                "A descending LOS comparison requires a prospective projection rule and local "
                "look geometry. Vertical levelling is not directly equivalent to LOS motion."
            ),
            "independence": (
                "An InSAR-derived or model-assimilated product cannot serve as independent ground anchoring."
            ),
        },
        "analysis_sequence_after_receipt": [
            "Archive received files unchanged and record SHA-256, access terms, and provenance.",
            "Screen metadata, spatial overlap, dates, reference frame, component, and independence.",
            "Before inspecting comparison results, freeze temporal harmonization, LOS projection, uncertainty treatment, metrics, and numerical decision gates.",
            "Run the comparison only on compatible observations and report excluded records with reasons.",
            "Report residuals, uncertainty, sample size, spatial support, and sensitivity without extrapolating outside the strict footprint.",
            "Classify the outcome as anchored, rejected, or insufficient; do not create hazard or risk products here.",
        ],
        "prohibited_actions": [
            "external send without the project owner's explicit approval and signature details",
            "including velocity or rate values in the footprint attachment",
            "treating one descending LOS result as validated vertical subsidence",
            "using an InSAR-derived SIGA or other model product as independent ground truth",
            "choosing validation thresholds after inspecting comparison results",
            "extrapolating beyond the 380-cell strict footprint",
            "promoting a deformation-rate, hazard, or risk claim from this package alone",
        ],
        "open_question_for_SIGA": (
            "Are the 2021-2023 'Data Mounting' rates derived from GNSS, precise "
            "levelling, monitoring wells, InSAR, another sensor, or a model?"
        ),
    }


INVENTORY_COLUMNS = [
    "provider",
    "dataset_name",
    "station_or_benchmark_id",
    "observation_type",
    "longitude",
    "latitude",
    "horizontal_crs",
    "coordinate_epoch",
    "observation_start",
    "observation_end",
    "observation_epoch",
    "component",
    "value_type",
    "value",
    "units",
    "positive_direction",
    "reference_frame",
    "vertical_datum",
    "uncertainty",
    "uncertainty_convention",
    "covariance_available",
    "equipment_and_method",
    "processing_provenance",
    "offsets_or_discontinuities",
    "quality_flags",
    "source_citation",
    "licence_or_access_terms",
    "notes",
]


REQUEST_TEXT = """# Draft request for date-compatible North Jakarta ground observations

**Status:** Review only. Not approved or authorized for external transmission.  
**Required before sending:** final recipient, project-owner approval, and signature/contact details.

## Suggested subject

Permohonan data GNSS/pengukuran sipat datar 2020-2023 untuk validasi independen kandidat InSAR Jakarta Utara

## Recipient routing

- **BIG:** Ina-CORS or other geodetic-reference GNSS observations, coordinates, time series, and processing metadata.
- **ITB:** research GNSS campaigns, precise levelling, benchmarks, or related North Jakarta deformation observations.
- **DKI Jakarta:** repeated levelling/benchmark or surface-monitoring records and provenance for SIGA's 2021-2023 `Data Mounting` rates.

Use the appropriate institution-specific line above; do not imply that all three institutions hold the same data.
Retain the SIGA `Data Mounting` paragraph for DKI Jakarta; omit it for BIG or ITB unless the exact recipient is responsible for that product.

## Draft request (Bahasa Indonesia)

Yth. [nama unit/pengelola data]  
[BIG / Institut Teknologi Bandung / Pemerintah Provinsi DKI Jakarta]

Dengan hormat,

Saya [nama], [jabatan/afiliasi], sedang melakukan penelitian mengenai pola deformasi permukaan di Jakarta Utara. Analisis Sentinel-1 yang sedang diuji mencakup periode 10 Januari 2020 sampai 11 Juni 2023. Hasil tersebut masih berupa **pola relatif line-of-sight (LOS) kandidat**; tingkat nol absolut, gerak vertikal, bahaya, dan risiko belum tervalidasi.

Untuk validasi independen, kami memohon informasi mengenai ketersediaan atau prosedur akses untuk data yang beririsan dengan poligon terlampir, khususnya:

1. deret waktu atau pengamatan kampanye GNSS pada 2020-2023;
2. pengukuran sipat datar presisi berulang beserta informasi titik benchmark; atau
3. pengamatan perpindahan permukaan lain yang independen dari hasil InSAR ini.

Apabila tersedia, kami memohon koordinat dan identitas stasiun/titik, tanggal atau epoch pengamatan, datum dan kerangka referensi, komponen yang diukur serta konvensi tandanya, satuan, ketidakpastian atau kovariansi, perubahan alat/offset/diskontinuitas, metode pengolahan, flag kualitas, serta ketentuan lisensi, sitasi, dan redistribusi. Data epoch atau kampanye asli lebih diutamakan daripada laju jangka panjang agar periode pembanding dapat diselaraskan secara transparan.

Khusus untuk informasi SIGA 2021-2023 yang disebut `Data Mounting`, mohon konfirmasi apakah nilai tersebut berasal dari GNSS, sipat datar, sumur pantau, InSAR, sensor lain, atau pemodelan, serta periode, datum, komponen, satuan, ketidakpastian, dan metode perhitungannya.

Lampiran GeoJSON hanya menunjukkan lokasi 380 sel kandidat yang lolos pemeriksaan teknis, mencakup 68,3903% luas Jakarta Utara. Lampiran tersebut **tidak memuat nilai kecepatan atau laju** dan bukan peta deformasi tervalidasi, bahaya, atau risiko. Data yang diterima akan digunakan hanya setelah pemeriksaan kesesuaian lokasi, tanggal, referensi, komponen, dan ketidakpastian. Sumber data dan pembatasan penggunaan akan dicantumkan sesuai ketentuan penyedia.

Jika data berada pada unit lain atau memerlukan prosedur/formulir khusus, kami sangat menghargai petunjuk kontak atau jalur permohonan yang tepat. Kami juga bersedia menerima data dalam format asli atau melakukan pembahasan teknis singkat sesuai kebijakan penyedia.

Terima kasih atas perhatian dan bantuannya.

Hormat kami,  
[nama lengkap]  
[jabatan/afiliasi]  
[alamat institusi]  
[email]  
[nomor telepon, bila dikehendaki]

## Attachments proposed for review

1. `v13_strict_candidate_footprint_north_jakarta.geojson` - exact no-rate colocation footprint.
2. `v13_strict_candidate_footprint_north_jakarta.summary.json` - geometry and area summary.
3. `v13_ground_validation_protocol.json` - compatibility and claim-control rules.
4. `v13_ground_observation_inventory_template.csv` - optional metadata inventory; native provider formats are acceptable.

## Internal pre-send checklist

- [ ] Correct recipient name, unit, institution, and approved delivery route.
- [ ] Project-owner approval recorded.
- [ ] Signature, affiliation, email, and optional telephone supplied by the project owner.
- [ ] Institution-specific routing sentence retained; irrelevant alternatives removed.
- [ ] SIGA paragraph retained only for DKI or another recipient responsible for that product.
- [ ] Attachment hashes match the package manifest.
- [ ] No velocity/rate values are present in the GeoJSON.
- [ ] No claim of validated deformation, vertical subsidence, hazard, or risk.
- [ ] Follow-up limited to one short message after ten business days.
"""


def build_package(
    output_dir: Path,
    v13_audit_path: Path,
    v14_audit_path: Path,
    expected_sha256: dict[str, str] | None = None,
) -> dict[str, Any]:
    expected = EXPECTED_SHA256 if expected_sha256 is None else expected_sha256
    output_dir.mkdir(parents=True, exist_ok=True)
    footprint_path = output_dir / "v13_strict_candidate_footprint_north_jakarta.geojson"
    summary_path = output_dir / "v13_strict_candidate_footprint_north_jakarta.summary.json"
    sources = [footprint_path, summary_path, v13_audit_path, v14_audit_path]
    for source in sources:
        _require_hash(source, expected[source.name])
    validate_footprint(footprint_path, summary_path)
    source_hashes = {source.name: sha256_file(source) for source in sources}

    protocol_path = output_dir / PROTOCOL_NAME
    template_path = output_dir / TEMPLATE_NAME
    request_path = output_dir / REQUEST_NAME
    manifest_path = output_dir / MANIFEST_NAME
    _write_json(protocol_path, protocol_payload(source_hashes))
    with template_path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, lineterminator="\n").writerow(INVENTORY_COLUMNS)
    request_path.write_text(REQUEST_TEXT, encoding="utf-8")

    generated = [protocol_path, template_path, request_path]
    manifest = {
        "schema_version": 1,
        "package_name": "v13_date_compatible_ground_validation_request",
        "generated_on": "2026-08-10",
        "authorization_status": "review_only_not_authorized_for_external_send",
        "scientific_status": "relative_pattern_only",
        "generator": "scripts/build_v13_ground_validation_package.py",
        "source_files": [
            {"path": source.as_posix(), "sha256": source_hashes[source.name]}
            for source in sources
        ],
        "package_files": [
            {
                "path": path.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in generated
        ],
        "external_send_requires": [
            "project-owner approval",
            "approved recipient and delivery route",
            "project-owner signature and contact details",
            "final attachment hash verification",
        ],
    }
    _write_json(manifest_path, manifest)
    return manifest


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/output/v13_validation"),
    )
    parser.add_argument(
        "--v13-audit",
        type=Path,
        default=Path("data/output/v13_audit/v13_results_audit.json"),
    )
    parser.add_argument(
        "--v14-audit",
        type=Path,
        default=Path("data/output/v14_audit/v14_reference_sensitivity_audit.json"),
    )
    args = parser.parse_args()
    manifest = build_package(args.output_dir, args.v13_audit, args.v14_audit)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    cli()
