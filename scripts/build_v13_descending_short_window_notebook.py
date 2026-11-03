"""Build the preregistered shorter-window descending Jakarta inversion notebook."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V11_NOTEBOOK = ROOT / "notebooks" / "LiCSBAS_Jakarta_descending_diagnostic_v11.ipynb"
OUTPUT = ROOT / "notebooks" / "LiCSBAS_Jakarta_descending_short_window_v13.ipynb"


def markdown(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(True)}


def code(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(True),
    }


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"Expected exactly one builder anchor: {old!r}")
    return text.replace(old, new, 1)


v11 = json.loads(V11_NOTEBOOK.read_text(encoding="utf-8"))
mount_cell = v11["cells"][1]
install_cell = v11["cells"][2]

config = "".join(v11["cells"][3]["source"])
config = replace_once(config, "START, END = '20200101', '20231231'", "START, END = '20200110', '20230611'")
config = replace_once(config, "WORK = Path('/content/insar_desc47_v11')", "WORK = Path('/content/insar_desc47_short_v13')")
config = replace_once(config, "TS_NAME = 'TS_GEOCml5clip_desc47_reunw_mp'", "TS_NAME = 'TS_GEOCml5clip_desc47_short_reunw_mp'")
config = replace_once(config, "RUN_TAG = 'desc47_reunw_unfiltered_roi_ml5_mp'", "RUN_TAG = 'desc47_short_reunw_unfiltered_roi_ml5_mp'")
config = replace_once(
    config,
    """SCRIPTS = {
    'download': resolve_script('download', 'LiCSBAS01_get_geotiff.py', ('01', 'get_geo')),
    'reunwrap': resolve_script('reunwrap', 'LiCSBAS02to05_unwrap.py', ('02to05', 'unwrap')),
    'check': resolve_script('check', 'LiCSBAS11_check_unw.py', ('11', 'check_unw')),
    'loop': resolve_script('loop', 'LiCSBAS12_loop_closure.py', ('12', 'loop')),
}
""",
    """SCRIPTS = {
    'check': resolve_script('check', 'LiCSBAS11_check_unw.py', ('11', 'check_unw')),
    'loop': resolve_script('loop', 'LiCSBAS12_loop_closure.py', ('12', 'loop')),
    'invert': resolve_script('invert', 'LiCSBAS13_sb_inv.py', ('13', 'sb_inv')),
    'vstd': resolve_script('vstd', 'LiCSBAS14_vel_std.py', ('14', 'vel_std')),
    'geotiff': resolve_script('GeoTIFF export', 'LiCSBAS_flt2geotiff.py', ('flt2geotiff',)),
}
""",
)
config = replace_once(
    config,
    "BOUNDARY_CACHE = ARCHIVE / f'dki_kelurahan_official_{BOUNDARY_SHA256[:12]}.geojson'",
    """BOUNDARY_CACHE = ARCHIVE / f'dki_kelurahan_official_{BOUNDARY_SHA256[:12]}.geojson'

V11_CHECKPOINT = ARCHIVE / 'GEOCml5clip_desc47_reunw_unfiltered_roi_ml5_mp_20200101_20231231_checkpoint.tar.gz'
V11_CHECKPOINT_SHA_FILE = ARCHIVE / 'GEOCml5clip_desc47_reunw_unfiltered_roi_ml5_mp_20200101_20231231_checkpoint.sha256'
EXPECTED_V11_CHECKPOINT_SHA256 = '0a3d1378234eef757fdb07341abb96dc2934612d4a4124c8282cf40b619565b9'
EXPECTED_V11_CONFIGURATION_FINGERPRINT = '8aa6272c2f629684926140b864361cb15ff3a3c5c988c3bad0cd015b817984f9'
RUN_ROLE = 'preregistered_descending_short_window_inversion_candidate'
POST_INVERSION_GATE_PATH = DRIVE_OUT / f'jakarta_licsbas_{DATE_TAG}_{RUN_TAG}_post_inversion_gate.json'
QC_SUMMARY = DRIVE_OUT / f'jakarta_licsbas_{DATE_TAG}_{RUN_TAG}_qc_summary.json'
MANIFEST_PATH = DRIVE_OUT / f'jakarta_licsbas_{DATE_TAG}_{RUN_TAG}_manifest.json'
RESULTS_ARCHIVE = ARCHIVE / f'{TS_NAME}_results_{DATE_TAG}.tar.gz'
RESULTS_ARCHIVE_SHA = ARCHIVE / f'{TS_NAME}_results_{DATE_TAG}.sha256'""",
)

network = "".join(v11["cells"][9]["source"])
network = replace_once(
    network,
    "# 8 - Run steps 11/12, then enforce global and North-Jakarta gates",
    "# 6 - Reproduce steps 11/12 and enforce the exact-window global and North gates",
)
network = replace_once(
    network,
    "Checksum-verified boundary preflight is unavailable; rerun cell 5 before diagnostics.",
    "Checksum-verified boundary preflight is unavailable; rerun the checkpoint-restore cell.",
)
network = replace_once(
    network,
    "'gate_basis': 'preregistered_descending_global_plus_north_local_network'",
    "'gate_basis': 'preregistered_descending_short_window_global_plus_north_local_network'",
)
network = replace_once(
    network,
    "'pass_action': 'Stop and return to Codex; a separate preregistered inversion notebook is required.'",
    "'pass_action': 'Continue to the prospectively gated v13 inversion; outputs remain diagnostic pending post-inversion QC and validation.'",
)
network = replace_once(
    network,
    "'promotion_prohibited_without': ['post_inversion_n_gap=0_and_n_loop_err=0', 'uncertainty_sensitivity',\n                                     'independent_GNSS_or_levelling_validation', 'explicit_exposure_validation']",
    "'promotion_prohibited_without': ['post_inversion_finite_velocity_and_vstd', 'post_inversion_n_gap=0_and_n_loop_err=0',\n                                     'unchanged_North_area_district_and_patch_gates', 'uncertainty_sensitivity',\n                                     'independent_GNSS_or_levelling_validation']",
)
network = replace_once(
    network,
    "print('DESCENDING GLOBAL + NORTH GATES PASSED. STOP HERE and return to Codex; this notebook has no inversion.')",
    "print('EXACT-WINDOW NETWORK + NORTH GATES PASSED. STOP HERE and return to Codex before running cell 7 inversion.')",
)

cells = [
    markdown(
        """# LiCSBAS Jakarta v13 — preregistered descending shorter-window inversion

V11 failed because the public descending catalogue ended on 11 June 2023 and could not span 95% of the originally requested 2020–2023 interval. Its retained network itself was strong, and the subsequent descriptive audit found that 68.39% of North Jakarta passed every non-temporal local requirement. V13 therefore asks a new, narrower question: can the exact available interval, **10 January 2020–11 June 2023**, produce a defensible North-Jakarta velocity candidate?

This is not a retroactive v11 pass. The selected interval and pre-inversion network behaviour are already known and are recorded as such. The prospective outcome is the post-inversion mask. A candidate pixel must have finite velocity and velocity uncertainty, satisfy the unchanged local network criteria, and have both `n_gap=0` and `n_loop_err=0`. Continuation still requires at least 50% qualifying North area, at least 25% in every northern district, and at least 75% of qualifying area in one eight-connected patch. Uncertainty survival at 5/10/15/20 mm/year is descriptive and cannot change the mask.

The notebook restores the exact checksum-verified v11 regenerated checkpoint and re-runs steps 11 and 12 with `--multi_prime` and the unchanged 1.5-radian threshold. **Stop after cell 6 and return to Codex before cell 7.** After that checkpoint, LiCSBAS steps 13 and 14 may run only if the exact-window gates passed. The notebook does not use partial GACOS, manual pair removal, nullification, or relaxed thresholds. Even a pass creates only a shorter-period validation candidate: rates remain relative and require reference sensitivity plus independent date-compatible GNSS or levelling before any deformation, hazard, or risk promotion.
"""
    ),
    mount_cell,
    install_cell,
    code(config),
    code(
        """# 4 - Validate the pinned tools and frozen v13 method
for role, script in SCRIPTS.items():
    help_run = subprocess.run([sys.executable, str(script), '-h'], cwd=WORK, env=run_env,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if help_run.returncode not in (0, 1):
        raise RuntimeError(f'{role} help check failed ({help_run.returncode})')
    print(f'--- {role}: {script.name} ---')
    print('\\n'.join(help_run.stdout.splitlines()[:14]))
loop_help = subprocess.run([sys.executable, str(SCRIPTS['loop']), '-h'], cwd=WORK, env=run_env,
                           text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout
if '--multi_prime' not in loop_help:
    raise RuntimeError('Pinned loop-closure command does not advertise --multi_prime.')
if USE_GACOS:
    raise RuntimeError('Partial GACOS is prohibited in this experiment.')
if (START, END) != ('20200110', '20230611'):
    raise RuntimeError('The preregistered v13 interval changed.')
print('Frozen v13 method verified: exact available descending interval, restored factor-5 checkpoint, 1.5-rad multi-prime loops, then gated inversion.')
"""
    ),
    markdown(
        """## Exact checkpoint restoration

This stage performs only a lightweight live catalogue identity check, restores the approximately 40 MB regenerated v11 checkpoint, verifies its fixed SHA-256 and embedded configuration fingerprint, and acquires the checksum-frozen official DKI boundary. It does not download the 8.45 GB wrapped-phase source archive or regenerate interferograms.
"""
    ),
    code(
        """# 5 - Restore and verify the exact regenerated stack and exact catalogue interval
session = requests.Session()
session.headers.update({'User-Agent': 'Jakarta-InSAR-v13-short-window-preflight'})

if BOUNDARY_CACHE.exists():
    boundary_bytes = BOUNDARY_CACHE.read_bytes()
    if hashlib.sha256(boundary_bytes).hexdigest() != BOUNDARY_SHA256:
        raise RuntimeError('Cached official DKI boundary checksum mismatch.')
else:
    response = session.get(BOUNDARY_URL, timeout=120)
    response.raise_for_status()
    boundary_bytes = response.content
    if hashlib.sha256(boundary_bytes).hexdigest() != BOUNDARY_SHA256:
        raise RuntimeError('Official DKI boundary checksum changed; review it before continuing.')
    partial = BOUNDARY_CACHE.with_suffix(BOUNDARY_CACHE.suffix + '.partial')
    partial.write_bytes(boundary_bytes)
    os.replace(partial, BOUNDARY_CACHE)
BOUNDARY_LOCAL.write_bytes(boundary_bytes)

index_response = session.get(CEDA_DATA + '/', timeout=90)
index_response.raise_for_status()
catalogue_pairs = sorted({
    pair for pair in re.findall(r'(?<!\\d)(\\d{8}_\\d{8})(?!\\d)', index_response.text)
    if START <= pair[:8] <= END and START <= pair[-8:] <= END
})
catalogue_images = sorted({date for pair in catalogue_pairs for date in pair.split('_')})
if len(catalogue_pairs) != EXPECTED_COMPLETE_PAIRS or len(catalogue_images) != EXPECTED_ACQUISITIONS:
    raise RuntimeError(f'Exact-window catalogue changed: {len(catalogue_pairs)} pairs/{len(catalogue_images)} dates; expected 349/76.')
if catalogue_images[0] != START or catalogue_images[-1] != END:
    raise RuntimeError(f'Catalogue endpoints changed: {catalogue_images[0]} to {catalogue_images[-1]}.')
expected_pair_set = set(catalogue_pairs)
all_ifgs_expected = catalogue_pairs
all_images_expected = catalogue_images

if not V11_CHECKPOINT.exists():
    raise FileNotFoundError(f'Missing verified regenerated checkpoint in Drive: {V11_CHECKPOINT}')
checkpoint_sha = sha256_file(V11_CHECKPOINT)
if checkpoint_sha != EXPECTED_V11_CHECKPOINT_SHA256:
    raise RuntimeError(f'V11 checkpoint SHA-256 mismatch: {checkpoint_sha}')
if V11_CHECKPOINT_SHA_FILE.exists():
    sidecar_sha = V11_CHECKPOINT_SHA_FILE.read_text(encoding='utf-8').strip().split()[0]
    if sidecar_sha != EXPECTED_V11_CHECKPOINT_SHA256:
        raise RuntimeError(f'V11 checkpoint sidecar disagrees with the preregistered SHA-256: {sidecar_sha}')

geocml_root = WORK / GEOCML_NAME
if geocml_root.exists():
    existing = regenerated_inventory(geocml_root)
    existing_is_complete = (
        existing['pair_folders'] == EXPECTED_COMPLETE_PAIRS
        and existing['complete_pairs'] == EXPECTED_COMPLETE_PAIRS
        and set(existing['pairs']) == expected_pair_set
    )
    if not existing_is_complete:
        if geocml_root.resolve().parent != WORK.resolve():
            raise RuntimeError(f'Refusing to replace an unexpected runtime path: {geocml_root.resolve()}')
        print('Removing an incomplete ephemeral checkpoint extraction before retrying.')
        shutil.rmtree(geocml_root)
if not geocml_root.exists():
    with tarfile.open(V11_CHECKPOINT, 'r:gz') as bundle:
        destination_root = WORK.resolve()
        for member in bundle.getmembers():
            if member.issym() or member.islnk():
                raise RuntimeError(f'Checkpoint contains a prohibited link: {member.name}')
            target = (WORK / member.name).resolve()
            try:
                target.relative_to(destination_root)
            except ValueError as exc:
                raise RuntimeError(f'Checkpoint member escapes the work directory: {member.name}') from exc
        bundle.extractall(WORK, filter='data')

restored = regenerated_inventory(geocml_root)
if (restored['pair_folders'] != EXPECTED_COMPLETE_PAIRS
        or restored['complete_pairs'] != EXPECTED_COMPLETE_PAIRS
        or set(restored['pairs']) != expected_pair_set):
    raise RuntimeError(f'Restored checkpoint does not match the exact 349-pair catalogue: {restored}')
provenance_path = geocml_root / 'reunwrap_provenance.json'
if not provenance_path.exists():
    raise RuntimeError('Restored checkpoint lacks reunwrap_provenance.json.')
reunwrap_provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
if reunwrap_provenance.get('configuration_fingerprint') != EXPECTED_V11_CONFIGURATION_FINGERPRINT:
    raise RuntimeError('Restored checkpoint configuration fingerprint mismatch.')
for key, expected in {'frame': FRAME, 'orbit': 'descending', 'pair_count': 349,
                      'acquisition_count': 76, 'multilook': 5,
                      'wrapped_product': WRAPPED_PRODUCT, 'historical_unwrapped_phase_used': False}.items():
    if reunwrap_provenance.get(key) != expected:
        raise RuntimeError(f'Restored provenance mismatch for {key}: {reunwrap_provenance.get(key)!r} != {expected!r}')
print(json.dumps({'checkpoint_sha256': checkpoint_sha, 'configuration_fingerprint': EXPECTED_V11_CONFIGURATION_FINGERPRINT,
                  'pair_count': len(catalogue_pairs), 'acquisition_count': len(catalogue_images),
                  'first_acquisition': catalogue_images[0], 'last_acquisition': catalogue_images[-1]}, indent=2))
"""
    ),
    code(network),
    code(
        """# 7 - Run the prospectively gated inversion and compute the strict North candidate
run_script('invert', ['-d', GEOCML_NAME, '-t', TS_NAME, '--mem_size', '4000'],
           required=[WORK / TS_NAME / 'cum.h5', WORK / TS_NAME / 'results' / 'vel',
                     WORK / TS_NAME / 'results' / 'n_gap'])
run_script('vstd', ['-t', TS_NAME], required=[WORK / TS_NAME / 'results' / 'vstd'])

results_dir = WORK / TS_NAME / 'results'
def result_grid(name):
    values = np.fromfile(results_dir / name, dtype='<f4')
    if values.size != width * length:
        raise RuntimeError(f'Unexpected {name} size: {values.size} != {width * length}')
    return values.reshape(length, width)

velocity = result_grid('vel')
velocity_std = result_grid('vstd')
n_gap = result_grid('n_gap')
final_n_loop_err = result_grid('n_loop_err')
finite_results = np.isfinite(velocity) & np.isfinite(velocity_std)
strict_north = qualifies & finite_results & (n_gap == 0) & (final_n_loop_err == 0)

strict_passing_area = sum(area for cell, area in cell_total_area.items() if strict_north[cell])
strict_north_fraction = strict_passing_area / total_area
strict_district_passing = {
    name: sum(areas.get(name, 0) for cell, areas in cell_district_areas.items() if strict_north[cell])
    for name in district_geometries
}
strict_district_fractions = {
    name: strict_district_passing[name] / district_total[name] for name in district_geometries
}
unseen = {cell for cell in north_cells if strict_north[cell]}
strict_patch_areas = []
while unseen:
    start = min(unseen); stack = [start]; component = set()
    while stack:
        cell = stack.pop()
        if cell in component or cell not in unseen:
            continue
        component.add(cell); unseen.discard(cell)
        row, col = cell
        stack.extend((row + dr, col + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                     if (dr or dc) and (row + dr, col + dc) in unseen)
    strict_patch_areas.append(sum(cell_total_area[cell] for cell in component))
strict_largest_patch_fraction = max(strict_patch_areas, default=0.0) / strict_passing_area if strict_passing_area else 0.0

vstd_sensitivity = []
strict_values = velocity_std[strict_north]
for threshold in (5.0, 10.0, 15.0, 20.0):
    count = int(np.count_nonzero(strict_values <= threshold))
    vstd_sensitivity.append({'threshold_mm_per_year': threshold, 'surviving_pixels': count,
                             'fraction_of_strict_candidate': count / strict_values.size if strict_values.size else 0.0})

post_failures = []
if strict_north_fraction < MIN_NORTH_AREA_FRACTION: post_failures.append('post-inversion North total area')
if any(value < MIN_EACH_NORTH_DISTRICT_AREA_FRACTION for value in strict_district_fractions.values()):
    post_failures.append('post-inversion North district minimum')
if strict_largest_patch_fraction < MIN_NORTH_LARGEST_PATCH_FRACTION:
    post_failures.append('post-inversion North connected patch')
post_inversion_gate = {
    'gate_basis': 'prospective_v13_strict_North_post_inversion_gate',
    'candidate_interval': [START, END], 'frame': FRAME, 'orbit': 'descending',
    'strict_pixel_criteria': ['passes unchanged v11 local network gate', 'finite velocity', 'finite vstd',
                              'n_gap=0', 'n_loop_err=0'],
    'north_candidate_cells': len(north_cells), 'strict_qualifying_cells': int(strict_north.sum()),
    'north_total_area_m2': total_area, 'strict_qualifying_area_m2': strict_passing_area,
    'strict_qualifying_area_fraction': strict_north_fraction,
    'district_area_fractions': strict_district_fractions,
    'largest_8_connected_patch_fraction_of_passing_area': strict_largest_patch_fraction,
    'thresholds': {'min_total_area_fraction': MIN_NORTH_AREA_FRACTION,
                   'min_each_district_area_fraction': MIN_EACH_NORTH_DISTRICT_AREA_FRACTION,
                   'min_largest_patch_fraction': MIN_NORTH_LARGEST_PATCH_FRACTION},
    'vstd_sensitivity_non_decisional': vstd_sensitivity,
    'passed': not post_failures, 'gate_failures': post_failures,
    'scientific_status_if_passed': 'shorter_period_validation_candidate_only',
    'promotion_still_requires': ['reference-area sensitivity', 'independent date-compatible GNSS or levelling validation',
                                  'uncertainty-aware rate interpretation', 'no extrapolation outside the strict mask'],
}
POST_INVERSION_GATE_PATH.write_text(json.dumps(post_inversion_gate, indent=2), encoding='utf-8')
(info_dir / f'{RUN_TAG}_post_inversion_gate.json').write_text(json.dumps(post_inversion_gate, indent=2), encoding='utf-8')
print(json.dumps(post_inversion_gate, indent=2))
"""
    ),
    code(
        """# 8 - Export matched diagnostic layers and the exact North strict candidate mask
layers = ('vel', 'vstd', 'coh_avg', 'n_unw')
exported = {}
for layer in layers:
    source = results_dir / layer
    if not source.exists():
        raise FileNotFoundError(f'Missing LiCSBAS result layer: {source}')
    destination = DRIVE_OUT / f'jakarta_{layer}_{DATE_TAG}_{RUN_TAG}.tif'
    run_script('geotiff', ['-i', source, '-p', geocml_root / 'EQA.dem_par', '-o', destination],
               required=[destination])
    exported[layer] = destination

with rasterio.open(exported['vel']) as template:
    velocity_profile = template.profile.copy()
    exported_velocity = template.read(1)
    if exported_velocity.shape != strict_north.shape:
        raise RuntimeError('Exported velocity grid does not match the strict candidate grid.')
    mask_profile = velocity_profile.copy()
    mask_profile.update(dtype='uint8', count=1, nodata=255, compress='deflate')
    north_domain = np.zeros(strict_north.shape, dtype=bool)
    for cell in north_cells:
        north_domain[cell] = True
    mask_data = np.full(strict_north.shape, 255, dtype='uint8')
    mask_data[north_domain] = 0
    mask_data[strict_north] = 1
    strict_mask_path = DRIVE_OUT / f'jakarta_north_strict_mask_{DATE_TAG}_{RUN_TAG}.tif'
    with rasterio.open(strict_mask_path, 'w', **mask_profile) as destination:
        destination.write(mask_data, 1)
        destination.update_tags(scientific_status='diagnostic_validation_candidate_only',
                                criteria='local network pass; finite vel/vstd; n_gap=0; n_loop_err=0')
    masked_profile = velocity_profile.copy()
    masked_profile.update(dtype='float32', count=1, nodata=np.nan, compress='deflate')
    masked_velocity_path = DRIVE_OUT / f'jakarta_north_velocity_strict_masked_{DATE_TAG}_{RUN_TAG}.tif'
    masked_velocity = np.where(strict_north, exported_velocity, np.nan).astype('float32')
    with rasterio.open(masked_velocity_path, 'w', **masked_profile) as destination:
        destination.write(masked_velocity, 1)
        destination.update_tags(scientific_status='diagnostic_validation_candidate_only', units='mm/year',
                                reference='relative LiCSBAS velocity; not independently validated')
exported['north_strict_mask'] = strict_mask_path
exported['north_velocity_strict_masked'] = masked_velocity_path
print(json.dumps({key: str(value) for key, value in exported.items()}, indent=2))
"""
    ),
    code(
        """# 9 - Validate exports and write complete diagnostic provenance
layer_meta, grid_key = {}, None
for role, path in exported.items():
    with rasterio.open(path) as source:
        data = source.read(1)
        current_grid = (source.width, source.height, str(source.crs), tuple(source.transform))
        if grid_key is None:
            grid_key = current_grid
        elif current_grid != grid_key:
            raise RuntimeError(f'Grid mismatch for {role}: {current_grid} != {grid_key}')
        if role == 'north_strict_mask':
            finite = data != source.nodata
            values = data[finite]
        else:
            finite = np.isfinite(data)
            values = data[finite]
        if role == 'vstd' and (not values.size or np.any(values < 0)):
            raise RuntimeError('vstd is empty or contains negative values.')
        layer_meta[role] = {
            'path': str(path), 'sha256': sha256_file(path), 'bytes': path.stat().st_size,
            'shape': [source.height, source.width], 'crs': str(source.crs),
            'transform': list(source.transform), 'resolution': list(source.res),
            'total_pixels': int(data.size), 'finite_or_domain_pixels': int(finite.sum()),
            'min': float(values.min()) if values.size else None,
            'median': float(np.median(values)) if values.size else None,
            'max': float(values.max()) if values.size else None,
        }

reference_path = info_dir / '12ref.txt'
reference_area = reference_path.read_text(encoding='utf-8', errors='replace').strip() if reference_path.exists() else None
qc = {
    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'scientific_status': 'diagnostic_shorter_period_candidate_pending_sensitivity_and_external_validation',
    'run_role': RUN_ROLE, 'frame': FRAME, 'orbit': 'descending', 'start': START, 'end': END,
    'multilook': NLOOK, 'run_tag': RUN_TAG, 'reference_area': reference_area,
    'source_checkpoint': {'path': str(V11_CHECKPOINT), 'sha256': checkpoint_sha,
                          'configuration_fingerprint': EXPECTED_V11_CONFIGURATION_FINGERPRINT},
    'network_gate': network_gate, 'post_inversion_gate': post_inversion_gate,
    'layer_statistics': layer_meta,
    'prohibited_claims': ['validated deformation rate', 'citywide hazard map', 'risk map',
                          'North Jakarta rate without independent validation'],
}
manifest = {
    'created_utc': qc['created_utc'], 'frame': FRAME, 'orbit': 'descending',
    'start': START, 'end': END, 'multilook': NLOOK, 'run_tag': RUN_TAG,
    'run_role': RUN_ROLE, 'licsbas_commit': actual_commit, 'licsar_extra_commit': LICSAR_EXTRA_COMMIT,
    'source_checkpoint': qc['source_checkpoint'],
    'steps': ['restore_verified_v11_regenerated_checkpoint', '11', '12_multi_prime_1.5rad', '13', '14',
              'strict_North_post_inversion_gate'],
    'network_gate': network_gate, 'post_inversion_gate': post_inversion_gate,
    'layers': layer_meta, 'qc_summary': str(QC_SUMMARY),
}
QC_SUMMARY.write_text(json.dumps(qc, indent=2, allow_nan=False), encoding='utf-8')
MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding='utf-8')
(info_dir / QC_SUMMARY.name).write_text(json.dumps(qc, indent=2, allow_nan=False), encoding='utf-8')
(info_dir / MANIFEST_PATH.name).write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding='utf-8')
print('QC summary:', QC_SUMMARY)
print('Manifest:', MANIFEST_PATH)
"""
    ),
    code(
        """# 10 - Archive all diagnostics, verify the archive, and enforce the final stop/pass decision
archive_items = [f'{TS_NAME}/results', f'{TS_NAME}/info', f'{TS_NAME}/network',
                 f'{GEOCML_NAME}/EQA.dem_par', f'{GEOCML_NAME}/reunwrap_provenance.json',
                 BOUNDARY_LOCAL.name]
results_sha = atomic_archive(WORK, archive_items, RESULTS_ARCHIVE)
RESULTS_ARCHIVE_SHA.write_text(f'{results_sha}  {RESULTS_ARCHIVE.name}\\n', encoding='utf-8')
print(f'VERIFIED v13 results archive: {RESULTS_ARCHIVE} ({RESULTS_ARCHIVE.stat().st_size / 1e6:.1f} MB)')
print('SHA-256:', results_sha)
if not post_inversion_gate['passed']:
    raise RuntimeError('PREREGISTERED V13 STOP: ' + '; '.join(post_inversion_gate['gate_failures'])
                       + '. Outputs are archived for audit; do not tune or promote them.')
print('V13 POST-INVERSION GATE PASSED — this is a shorter-period validation candidate only.')
print('Do not promote rates, hazard, or risk until reference sensitivity and independent GNSS/levelling validation are complete.')
"""
    ),
]

notebook = {
    "cells": cells,
    "metadata": v11["metadata"],
    "nbformat": v11["nbformat"],
    "nbformat_minor": v11["nbformat_minor"],
}
# Match the archived notebook's registered bytes on every OS.
OUTPUT.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\r\n")
print(OUTPUT)
