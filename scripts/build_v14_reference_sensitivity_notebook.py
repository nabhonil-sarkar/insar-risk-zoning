"""Build the preregistered v13 reference-area sensitivity notebook."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V13_NOTEBOOK = ROOT / "notebooks" / "LiCSBAS_Jakarta_descending_short_window_v13.ipynb"
OUTPUT = ROOT / "notebooks" / "LiCSBAS_Jakarta_reference_sensitivity_v14.ipynb"


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


v13 = json.loads(V13_NOTEBOOK.read_text(encoding="utf-8"))
mount_cell = v13["cells"][1]
install_cell = v13["cells"][2]
config = "".join(v13["cells"][3]["source"])
config = replace_once(
    config,
    "WORK = Path('/content/insar_desc47_short_v13')",
    "WORK = Path('/content/insar_desc47_reference_v14_schema2')",
)
config += r'''

BASELINE_RESULTS_ARCHIVE = ARCHIVE / 'TS_GEOCml5clip_desc47_short_reunw_mp_results_20200110_20230611.tar.gz'
BASELINE_RESULTS_SHA_FILE = ARCHIVE / 'TS_GEOCml5clip_desc47_short_reunw_mp_results_20200110_20230611.sha256'
EXPECTED_BASELINE_RESULTS_SHA256 = '54afa2dc1255af1dc04727ea0e6730e6975f6edbcf897744ef0724975d468187'
EXPECTED_BASELINE_REFERENCE = '90:91/30:31'
EXPECTED_AUTO_REFERENCE = '78:79/72:73'
EXPECTED_STRICT_NORTH_CELLS = 380
SUPERSEDED_SCHEMA1_FINGERPRINT = '46af15bbda3298c77171d14978ebed10b72028c3a17c966392b90143007bb899'
SENSITIVITY_DIR = ARCHIVE / 'v14_reference_sensitivity_schema2'
PREREGISTRATION_PATH = SENSITIVITY_DIR / 'v14_reference_area_preregistration_schema2.json'
DECISION_PATH = SENSITIVITY_DIR / 'v14_reference_area_sensitivity_decision_schema2.json'
SUMMARY_MANIFEST_PATH = SENSITIVITY_DIR / 'v14_reference_area_sensitivity_manifest_schema2.json'
SUMMARY_ARCHIVE = SENSITIVITY_DIR / 'v14_reference_area_sensitivity_summary_schema2.tar.gz'
SUMMARY_ARCHIVE_SHA = SENSITIVITY_DIR / 'v14_reference_area_sensitivity_summary_schema2.sha256'

REFERENCE_MEDIAN_SPREAD_MAX_MMYR = 3.0
CENTERED_RMSE_MAX_MMYR = 0.5
CENTERED_P95_ABS_MAX_MMYR = 1.0
CENTERED_MAX_ABS_MAX_MMYR = 3.0
MIN_PATTERN_CORRELATION = 0.99
MAX_STRICT_VSTD_MMYR = 5.0
QUALITY_REQUIRED_N_UNW = 347

SENSITIVITY_DIR.mkdir(parents=True, exist_ok=True)
'''

cells = [
    markdown(
        """# LiCSBAS Jakarta v14 schema 2 — preregistered v13 reference-area sensitivity

V13 produced a technically valid shorter-window **relative descending-LOS** candidate over 380 strict North-Jakarta cells. V14 changes only LiCSBAS step 13's preliminary reference area and tests whether that candidate depends materially on the chosen zero level. It does not rerun or reinterpret the failed v11 experiment, alter any interferogram, rerun steps 11/12, change the 1.5-radian loop threshold, use partial GACOS, remove pairs, or change the strict North mask rules.

Schema 1 stopped before producing any alternative result because LiCSBAS's automatic post-inversion point had phase in only 344/347 retained interferograms. The pinned step-13 code cannot reuse such a point as preliminary `12ref` without adding pairs to `120bad_ifg.txt`, which would change the network. Schema 2 preserves schema 1 and its fingerprint as a superseded design record, prohibits `120bad_ifg.txt`, and directly checks every retained UNW value before freezing a runnable reference.

Four one-pixel references are frozen before alternative inversion: the original step-12 control (`90:91/30:31`) and western, eastern and southern quality-only points. Every runnable point must have finite non-zero unwrapped phase in all 347 retained interferograms, `n_gap=0`, `n_loop_err=0`, and is selected without velocity. The automatic `13ref` is recorded as an excluded diagnostic point, not silently replaced or used to remove interferograms.

The sensitivity has two distinct gates. First, every reference must retain the exact 380-cell strict mask, `vstd <= 5 mm/year`, and a nearly invariant spatial pattern after subtracting the median reference offset (correlations >=0.99, centred RMSE <=0.5, centred 95th-percentile absolute difference <=1.0, and centred maximum absolute difference <=3.0 mm/year). Second, the median strict-cell rate spread across all four references must be <=3.0 mm/year, reusing the project's pre-existing calibration-candidate tolerance. Pattern pass plus zero-level failure is reported as **relative pattern only**, not an absolute-rate pass.

**Run through cell 6, then stop and return to Codex before running cells 7–11.** Even a full reference-sensitivity pass remains a validation candidate until independent date-compatible GNSS or levelling comparison succeeds.
"""
    ),
    mount_cell,
    install_cell,
    code(config),
    code(
        r'''# 4 - Verify the pinned inversion tools and immutable method
for role in ('invert', 'vstd'):
    help_run = subprocess.run([sys.executable, str(SCRIPTS[role]), '-h'], cwd=WORK, env=run_env,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if help_run.returncode not in (0, 1):
        raise RuntimeError(f'{role} help check failed ({help_run.returncode})')
    print(f'--- {role}: {SCRIPTS[role].name} ---')
    print('\n'.join(help_run.stdout.splitlines()[:18]))

invert_source = SCRIPTS['invert'].read_text(encoding='utf-8', errors='replace')
required_source_tokens = ("reffile = os.path.join(infodir, '12ref.txt')", 'Set preliminaly reference',
                          '13ref.txt', 'minimum RMS and minimum n_gap')
missing_tokens = [token for token in required_source_tokens if token not in invert_source]
if missing_tokens:
    raise RuntimeError(f'Pinned step-13 reference behavior changed: {missing_tokens}')
if any((USE_GACOS, LOOP_THRESHOLD_RAD != 1.5, LOOP_MODE != 'multi_prime', NLOOK != 5)):
    raise RuntimeError('A frozen v13 processing control changed.')
print('Frozen v14 method verified: change only info/12ref.txt in isolated step-13/14 reruns.')
'''
    ),
    code(
        r'''# 5 - Restore and authenticate the exact v13 baseline and regenerated interferograms
def safe_extract(archive_path, destination):
    destination = Path(destination).resolve()
    with tarfile.open(archive_path, 'r:gz') as bundle:
        for member in bundle.getmembers():
            if member.issym() or member.islnk():
                raise RuntimeError(f'Archive contains a prohibited link: {member.name}')
            target = (destination / member.name).resolve()
            try:
                target.relative_to(destination)
            except ValueError as exc:
                raise RuntimeError(f'Archive member escapes the work directory: {member.name}') from exc
        bundle.extractall(destination, filter='data')

def verify_sidecar(sidecar, expected_sha, expected_name):
    fields = Path(sidecar).read_text(encoding='utf-8').strip().split()
    if len(fields) < 2 or fields[0] != expected_sha or Path(fields[1]).name != expected_name:
        raise RuntimeError(f'Checksum sidecar mismatch: {sidecar}')

for path in (BASELINE_RESULTS_ARCHIVE, BASELINE_RESULTS_SHA_FILE, V11_CHECKPOINT):
    if not path.exists():
        raise FileNotFoundError(f'Missing required verified Drive input: {path}')
baseline_sha = sha256_file(BASELINE_RESULTS_ARCHIVE)
if baseline_sha != EXPECTED_BASELINE_RESULTS_SHA256:
    raise RuntimeError(f'V13 results archive SHA-256 mismatch: {baseline_sha}')
verify_sidecar(BASELINE_RESULTS_SHA_FILE, baseline_sha, BASELINE_RESULTS_ARCHIVE.name)
checkpoint_sha = sha256_file(V11_CHECKPOINT)
if checkpoint_sha != EXPECTED_V11_CHECKPOINT_SHA256:
    raise RuntimeError(f'Regenerated checkpoint SHA-256 mismatch: {checkpoint_sha}')

baseline_ts = WORK / TS_NAME
geocml_root = WORK / GEOCML_NAME
if not baseline_ts.exists():
    safe_extract(BASELINE_RESULTS_ARCHIVE, WORK)
if not geocml_root.exists() or regenerated_inventory(geocml_root)['complete_pairs'] != EXPECTED_COMPLETE_PAIRS:
    if geocml_root.exists():
        if geocml_root.resolve().parent != WORK.resolve():
            raise RuntimeError(f'Refusing to replace unexpected path: {geocml_root}')
        shutil.rmtree(geocml_root)
    safe_extract(V11_CHECKPOINT, WORK)
inventory = regenerated_inventory(geocml_root)
if inventory['pair_folders'] != 349 or inventory['complete_pairs'] != 349:
    raise RuntimeError(f'Restored regenerated stack is incomplete: {inventory}')

baseline_info = baseline_ts / 'info'
baseline_results = baseline_ts / 'results'
baseline_qc_path = baseline_info / 'jakarta_licsbas_20200110_20230611_desc47_short_reunw_unfiltered_roi_ml5_mp_qc_summary.json'
baseline_qc = json.loads(baseline_qc_path.read_text(encoding='utf-8'))
if baseline_qc.get('reference_area') != EXPECTED_BASELINE_REFERENCE:
    raise RuntimeError('The restored baseline does not use the audited v13 preliminary reference.')
if (baseline_info / '12ref.txt').read_text(encoding='utf-8').strip() != EXPECTED_BASELINE_REFERENCE:
    raise RuntimeError('Restored 12ref.txt differs from the audited v13 control.')
if (baseline_info / '13ref.txt').read_text(encoding='utf-8').strip() != EXPECTED_AUTO_REFERENCE:
    raise RuntimeError('Restored automatic LiCSBAS stable point differs from the audited v13 result.')
if not baseline_qc['network_gate']['passed'] or not baseline_qc['post_inversion_gate']['passed']:
    raise RuntimeError('The restored v13 baseline did not pass its frozen gates.')
provenance = json.loads((geocml_root / 'reunwrap_provenance.json').read_text(encoding='utf-8'))
if provenance.get('configuration_fingerprint') != EXPECTED_V11_CONFIGURATION_FINGERPRINT:
    raise RuntimeError('Regenerated checkpoint configuration fingerprint mismatch.')
print(json.dumps({'baseline_results_sha256': baseline_sha, 'checkpoint_sha256': checkpoint_sha,
                  'baseline_reference': EXPECTED_BASELINE_REFERENCE,
                  'automatic_reference': EXPECTED_AUTO_REFERENCE,
                  'complete_pairs': inventory['complete_pairs']}, indent=2))
'''
    ),
    code(
        r'''# 6 - Freeze full-support quality-only references and all decision rules before alternative inversion
from shapely.geometry import Point

def parse_dem(path):
    values = {}
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        if ':' in line and line.split(':', 1)[1].strip():
            values[line.split(':', 1)[0].strip()] = line.split(':', 1)[1].strip().split()[0]
    return values

dem = parse_dem(geocml_root / 'EQA.dem_par')
width, length = int(dem['width']), int(dem['nlines'])
lon0, lat0 = float(dem['corner_lon']), float(dem['corner_lat'])
dlon, dlat = float(dem['post_lon']), float(dem['post_lat'])

def baseline_grid(name):
    values = np.fromfile(baseline_results / name, dtype='<f4')
    if values.size != width * length:
        raise RuntimeError(f'Unexpected baseline {name} size: {values.size}')
    return values.reshape(length, width)

quality = {name: baseline_grid(name) for name in ('coh_avg', 'n_unw', 'n_gap', 'n_loop_err')}
boundary = json.loads((WORK / 'dki_kelurahan_official.geojson').read_text(encoding='utf-8'))
if hashlib.sha256((WORK / 'dki_kelurahan_official.geojson').read_bytes()).hexdigest() != BOUNDARY_SHA256:
    raise RuntimeError('Archived official DKI boundary checksum mismatch.')

def property_upper(feature, key):
    return next((str(value).upper() for name, value in feature.get('properties', {}).items()
                 if name.lower() == key.lower()), '')

mainland = unary_union([shape(feature['geometry']) for feature in boundary['features']
                        if 'KEPULAUAN' not in property_upper(feature, 'wadmkk')])
north = unary_union([shape(feature['geometry']) for feature in boundary['features']
                     if 'JAKARTA UTARA' in property_upper(feature, 'wadmkk')])

quality_candidates_all_roi = []
quality_candidates_mainland = []
for row in range(length):
    lat = lat0 + row * dlat
    for col in range(width):
        lon = lon0 + col * dlon
        if (np.isfinite(quality['coh_avg'][row, col]) and quality['n_unw'][row, col] == QUALITY_REQUIRED_N_UNW
                and quality['n_gap'][row, col] == 0 and quality['n_loop_err'][row, col] == 0):
            item = {'row': row, 'col': col, 'lon': lon, 'lat': lat,
                    'coh_avg': float(quality['coh_avg'][row, col]),
                    'n_unw': int(quality['n_unw'][row, col])}
            quality_candidates_all_roi.append(item)
            point = Point(lon, lat)
            if mainland.covers(point) and not north.covers(point):
                quality_candidates_mainland.append(item)

def highest_coherence(population, predicate):
    candidates = [item for item in population if predicate(item)]
    if not candidates:
        raise RuntimeError('A preregistered quality-only reference stratum is empty.')
    return max(candidates, key=lambda item: (item['coh_avg'], item['n_unw'], -item['row'], -item['col']))

west = highest_coherence(quality_candidates_mainland, lambda item: item['lon'] < 106.82)
east = highest_coherence(quality_candidates_mainland, lambda item: item['lon'] >= 106.90)
south = highest_coherence(quality_candidates_all_roi, lambda item: item['lat'] <= -6.25)
if ((west['col'], west['row']) != (63, 36) or (east['col'], east['row']) != (92, 37)
        or (south['col'], south['row']) != (56, 66)):
    raise RuntimeError(f'Full-support quality-only reference selection changed: west={west}, east={east}, south={south}')

bad_ifgs = set()
for bad_name in ('11bad_ifg.txt', '12bad_ifg.txt'):
    bad_ifgs.update(line.strip() for line in (baseline_info / bad_name).read_text(encoding='utf-8').splitlines()
                    if re.fullmatch(r'\d{8}_\d{8}', line.strip()))
retained_ifgs = sorted(set(inventory['pairs']) - bad_ifgs)
if len(retained_ifgs) != QUALITY_REQUIRED_N_UNW:
    raise RuntimeError(f'Expected 347 retained interferograms, found {len(retained_ifgs)}.')

def direct_reference_support(area):
    x1, x2, y1, y2 = map(int, re.split('[:/]', area))
    if x2 - x1 != 1 or y2 - y1 != 1:
        raise RuntimeError(f'Only one-pixel reference areas are admissible: {area}')
    missing = []
    pixel_offset = (y1 * width + x1) * 4
    for pair in retained_ifgs:
        unw_path = geocml_root / pair / f'{pair}.unw'
        with unw_path.open('rb') as stream:
            stream.seek(pixel_offset)
            value = np.fromfile(stream, dtype='<f4', count=1)
        if value.size != 1 or not np.isfinite(value[0]) or value[0] == 0:
            missing.append(pair)
    return {'retained_ifgs': len(retained_ifgs), 'supported_ifgs': len(retained_ifgs) - len(missing),
            'missing_ifgs': missing}

references = [
    {'id': 'control_12ref', 'area': EXPECTED_BASELINE_REFERENCE,
     'selection': 'audited v13 step-12 preliminary reference', 'run_required': False},
    {'id': 'quality_west', 'area': '63:64/36:37',
     'selection': 'highest coherence west of 106.82E among mainland non-North cells with n_unw=347, n_gap=0, n_loop_err=0',
     'run_required': True, **west},
    {'id': 'quality_east', 'area': '92:93/37:38',
     'selection': 'highest coherence east of or at 106.90E among mainland non-North cells with n_unw=347, n_gap=0, n_loop_err=0',
     'run_required': True, **east},
    {'id': 'quality_south', 'area': '56:57/66:67',
     'selection': 'highest coherence south of or at 6.25S in the fixed ROI with n_unw=347, n_gap=0, n_loop_err=0',
     'run_required': True, **south},
]
for reference in references:
    reference['direct_unw_support'] = direct_reference_support(reference['area'])
    if reference['direct_unw_support']['supported_ifgs'] != QUALITY_REQUIRED_N_UNW:
        raise RuntimeError(f'Reference lacks full retained-IFG support: {reference}')

excluded_auto_reference = {
    'id': 'auto_13ref', 'area': EXPECTED_AUTO_REFERENCE,
    'selection': 'LiCSBAS minimum cumulative-RMS/minimum-gap post-inversion point',
    'n_unw': int(quality['n_unw'][72, 78]), 'admissible_as_preliminary_12ref': False,
    'reason': '344/347 support would make pinned step 13 append 120bad_ifg.txt and return 1; pair removal is prohibited',
}
if excluded_auto_reference['n_unw'] != 344:
    raise RuntimeError('The archived automatic-reference support count changed.')
decision_rules = {
    'exact_strict_mask_cells_each_reference': EXPECTED_STRICT_NORTH_CELLS,
    'strict_mask_must_equal_baseline': True,
    'max_strict_vstd_mm_per_year': MAX_STRICT_VSTD_MMYR,
    'min_pearson_and_spearman_pattern_correlation': MIN_PATTERN_CORRELATION,
    'max_centered_rmse_mm_per_year': CENTERED_RMSE_MAX_MMYR,
    'max_centered_p95_absolute_difference_mm_per_year': CENTERED_P95_ABS_MAX_MMYR,
    'max_centered_absolute_difference_mm_per_year': CENTERED_MAX_ABS_MAX_MMYR,
    'max_reference_median_rate_spread_mm_per_year': REFERENCE_MEDIAN_SPREAD_MAX_MMYR,
    'outcomes': {
        'full_pass': 'all coverage, uncertainty, centred-pattern and median-spread gates pass',
        'relative_pattern_only': 'coverage/uncertainty/centred-pattern gates pass but median spread exceeds 3 mm/year',
        'failed': 'any coverage, uncertainty or centred-pattern gate fails',
    },
}
preregistration = {
    'experiment': 'v14_schema2_preregistered_v13_reference_area_sensitivity',
    'schema': 2,
    'supersedes_schema1_fingerprint': SUPERSEDED_SCHEMA1_FINGERPRINT,
    'schema1_stop_reason': 'no alternative result; automatic 13ref lacked phase in 3/347 retained interferograms',
    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'frozen_before_alternative_inversion': True,
    'velocity_used_for_reference_selection': False,
    'baseline_archive_sha256': baseline_sha,
    'regenerated_checkpoint_sha256': checkpoint_sha,
    'frame': FRAME, 'orbit': 'descending', 'interval': [START, END],
    'unchanged_processing': {'multilook': 5, 'inversion': 'LS', 'gamma': 0.0001,
                             'interferograms': 349, 'retained_interferograms': 347,
                             'step11_step12_rerun': False},
    'references': references, 'excluded_diagnostic_reference': excluded_auto_reference,
    'decision_rules': decision_rules,
    'interpretation': 'A full pass does not replace independent GNSS or levelling validation.',
}
fingerprint_payload = json.dumps({key: value for key, value in preregistration.items() if key != 'created_utc'},
                                 sort_keys=True, separators=(',', ':')).encode()
preregistration['configuration_fingerprint'] = hashlib.sha256(fingerprint_payload).hexdigest()
preregistered_bytes = (json.dumps(preregistration, indent=2, allow_nan=False) + '\n').encode()
if PREREGISTRATION_PATH.exists() and PREREGISTRATION_PATH.read_bytes() != preregistered_bytes:
    existing = json.loads(PREREGISTRATION_PATH.read_text(encoding='utf-8'))
    if existing.get('configuration_fingerprint') != preregistration['configuration_fingerprint']:
        raise RuntimeError('A different v14 preregistration already exists in Drive; do not overwrite it after seeing results.')
    preregistration['created_utc'] = existing['created_utc']
    preregistered_bytes = (json.dumps(preregistration, indent=2, allow_nan=False) + '\n').encode()
temporary = PREREGISTRATION_PATH.with_suffix('.json.partial')
temporary.write_bytes(preregistered_bytes)
os.replace(temporary, PREREGISTRATION_PATH)
print(json.dumps(preregistration, indent=2))
print('SCHEMA-2 PREREGISTRATION FROZEN. STOP HERE and return to Codex before running cell 7.')
'''
    ),
    code(
        r'''# 7 - Define the restart-safe isolated rerun and execute the full-support western reference
DERIVED_RESULT_PREFIXES = ('vel', 'vintercept', 'resid_rms', 'n_gap', 'n_ifg_noloop',
                           'maxTlen', 'bootvel', 'vstd', 'stc')

def candidate_paths(reference_id):
    ts_name = f'{TS_NAME}_ref_{reference_id}'
    archive = SENSITIVITY_DIR / f'{ts_name}.tar.gz'
    sidecar = SENSITIVITY_DIR / f'{ts_name}.sha256'
    return ts_name, WORK / ts_name, archive, sidecar

def candidate_complete(target, reference):
    provenance_path = target / 'info' / 'v14_reference_run_provenance.json'
    if not provenance_path.exists():
        return False
    saved = json.loads(provenance_path.read_text(encoding='utf-8'))
    required = [target / 'results' / name for name in ('vel', 'vstd', 'n_gap', 'n_loop_err')]
    return (saved.get('configuration_fingerprint') == preregistration['configuration_fingerprint']
            and saved.get('reference') == reference['area'] and all(path.exists() for path in required))

def run_reference_candidate(reference_id):
    reference = next(item for item in references if item['id'] == reference_id)
    if not reference['run_required']:
        raise RuntimeError('The baseline control is not an alternative rerun.')
    ts_name, target, archive, sidecar = candidate_paths(reference_id)
    if archive.exists() and sidecar.exists():
        fields = sidecar.read_text(encoding='utf-8').strip().split()
        if len(fields) >= 2 and fields[0] == sha256_file(archive) and Path(fields[1]).name == archive.name:
            if target.exists() and not candidate_complete(target, reference):
                shutil.rmtree(target)
            if not target.exists():
                safe_extract(archive, WORK)
            if candidate_complete(target, reference):
                print(f'RESTORED verified v14 candidate: {reference_id}')
                return target, archive, fields[0]
    if target.exists():
        if target.resolve().parent != WORK.resolve():
            raise RuntimeError(f'Refusing to replace unexpected path: {target}')
        shutil.rmtree(target)
    shutil.copytree(baseline_ts, target)
    for folder_name in ('13increment', '13resid'):
        shutil.rmtree(target / folder_name, ignore_errors=True)
    for path in (target / 'info').glob('13*'):
        if path.is_file(): path.unlink()
    for path in (target / 'network').glob('network13*'):
        if path.is_file(): path.unlink()
    for path in (target / 'results').iterdir():
        if any(path.name == prefix or path.name.startswith((prefix + '.', prefix + '_'))
               for prefix in DERIVED_RESULT_PREFIXES):
            if path.is_file(): path.unlink()
    (target / 'info' / '12ref.txt').write_text(reference['area'] + '\n', encoding='utf-8')
    run_script('invert', ['-d', GEOCML_NAME, '-t', ts_name, '--mem_size', '4000'],
               required=[target / 'cum.h5', target / 'results' / 'vel', target / 'results' / 'n_gap'])
    run_script('vstd', ['-t', ts_name], required=[target / 'results' / 'vstd'])
    if (target / 'info' / '12ref.txt').read_text(encoding='utf-8').strip() != reference['area']:
        raise RuntimeError('Alternative inversion changed its frozen preliminary reference.')
    run_provenance = {
        'reference_id': reference_id, 'reference': reference['area'],
        'selection': reference['selection'],
        'configuration_fingerprint': preregistration['configuration_fingerprint'],
        'baseline_archive_sha256': baseline_sha, 'checkpoint_sha256': checkpoint_sha,
        'only_changed_input': 'info/12ref.txt', 'steps': ['13_LS_gamma_0.0001', '14'],
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    (target / 'info' / 'v14_reference_run_provenance.json').write_text(
        json.dumps(run_provenance, indent=2) + '\n', encoding='utf-8')
    candidate_sha = atomic_archive(WORK, [ts_name], archive)
    sidecar.write_text(f'{candidate_sha}  {archive.name}\n', encoding='utf-8')
    print(f'VERIFIED v14 candidate {reference_id}: {archive} ({archive.stat().st_size / 1e6:.1f} MB)')
    print('SHA-256:', candidate_sha)
    return target, archive, candidate_sha

west_target, west_archive, west_sha = run_reference_candidate('quality_west')
'''
    ),
    code(
        r'''# 8 - Execute or restore the full-support eastern reference
east_target, east_archive, east_sha = run_reference_candidate('quality_east')
'''
    ),
    code(
        r'''# 9 - Execute or restore the full-support southern reference
south_target, south_archive, south_sha = run_reference_candidate('quality_south')
'''
    ),
    code(
        r'''# 10 - Apply the preregistered coverage, uncertainty, pattern and zero-level gates
from scipy.stats import spearmanr

ledger_path = baseline_info / f'{RUN_TAG}_north_pixel_ledger.json'
ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
eligible = np.zeros((length, width), dtype=bool)
for item in ledger:
    eligible[int(item['row']), int(item['col'])] = bool(item['qualifies'])

def result_grid(ts_dir, name):
    values = np.fromfile(Path(ts_dir) / 'results' / name, dtype='<f4')
    if values.size != width * length:
        raise RuntimeError(f'Unexpected {name} size in {ts_dir}: {values.size}')
    return values.reshape(length, width)

def strict_arrays(ts_dir):
    arrays = {name: result_grid(ts_dir, name) for name in ('vel', 'vstd', 'n_gap', 'n_loop_err')}
    strict = (eligible & np.isfinite(arrays['vel']) & np.isfinite(arrays['vstd'])
              & (arrays['n_gap'] == 0) & (arrays['n_loop_err'] == 0))
    return arrays, strict

baseline_arrays, baseline_strict = strict_arrays(baseline_ts)
if int(baseline_strict.sum()) != EXPECTED_STRICT_NORTH_CELLS:
    raise RuntimeError('The audited baseline no longer has exactly 380 strict North cells.')

runs = {'control_12ref': baseline_ts, 'quality_west': west_target,
        'quality_east': east_target, 'quality_south': south_target}
comparison = {}
median_rates = {}
coverage_uncertainty_pass = True
pattern_pass = True
base_values = baseline_arrays['vel'][baseline_strict].astype('float64')

for reference_id, ts_dir in runs.items():
    arrays, strict = strict_arrays(ts_dir)
    exact_mask = bool(np.array_equal(strict, baseline_strict))
    values = arrays['vel'][baseline_strict].astype('float64')
    vstd_values = arrays['vstd'][baseline_strict].astype('float64')
    median_rates[reference_id] = float(np.median(values))
    coverage_ok = int(strict.sum()) == EXPECTED_STRICT_NORTH_CELLS and exact_mask
    uncertainty_ok = bool(np.isfinite(vstd_values).all() and vstd_values.max() <= MAX_STRICT_VSTD_MMYR)
    record = {
        'reference': next(item['area'] for item in references if item['id'] == reference_id),
        'strict_cells': int(strict.sum()), 'strict_mask_equals_baseline': exact_mask,
        'strict_vstd_max_mm_per_year': float(vstd_values.max()),
        'median_strict_velocity_mm_per_year': median_rates[reference_id],
        'coverage_passed': coverage_ok, 'uncertainty_passed': uncertainty_ok,
    }
    coverage_uncertainty_pass &= coverage_ok and uncertainty_ok
    if reference_id != 'control_12ref':
        difference = values - base_values
        offset = float(np.median(difference))
        centred = difference - offset
        pearson = float(np.corrcoef(base_values, values)[0, 1])
        spearman = float(spearmanr(base_values, values).statistic)
        rmse = float(np.sqrt(np.mean(centred ** 2)))
        p95 = float(np.percentile(np.abs(centred), 95))
        maximum = float(np.max(np.abs(centred)))
        this_pattern_pass = (pearson >= MIN_PATTERN_CORRELATION and spearman >= MIN_PATTERN_CORRELATION
                             and rmse <= CENTERED_RMSE_MAX_MMYR
                             and p95 <= CENTERED_P95_ABS_MAX_MMYR
                             and maximum <= CENTERED_MAX_ABS_MAX_MMYR)
        record.update({'median_offset_from_control_mm_per_year': offset,
                       'centered_rmse_mm_per_year': rmse,
                       'centered_p95_abs_mm_per_year': p95,
                       'centered_max_abs_mm_per_year': maximum,
                       'pearson_pattern_correlation': pearson,
                       'spearman_pattern_correlation': spearman,
                       'centered_pattern_passed': this_pattern_pass})
        pattern_pass &= this_pattern_pass
    comparison[reference_id] = record

median_spread = float(max(median_rates.values()) - min(median_rates.values()))
zero_level_pass = median_spread <= REFERENCE_MEDIAN_SPREAD_MAX_MMYR
if coverage_uncertainty_pass and pattern_pass and zero_level_pass:
    outcome = 'full_pass'
elif coverage_uncertainty_pass and pattern_pass:
    outcome = 'relative_pattern_only'
else:
    outcome = 'failed'

decision = {
    'experiment': 'v14_schema2_preregistered_v13_reference_area_sensitivity',
    'configuration_fingerprint': preregistration['configuration_fingerprint'],
    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'comparison': comparison, 'median_rates_mm_per_year': median_rates,
    'reference_median_rate_spread_mm_per_year': median_spread,
    'gates': {'coverage_and_uncertainty_passed': coverage_uncertainty_pass,
              'centered_spatial_pattern_passed': pattern_pass,
              'absolute_zero_level_passed': zero_level_pass},
    'outcome': outcome,
    'reference_sensitivity_passed_for_absolute_relative_los_rates': outcome == 'full_pass',
    'external_validation_still_required': True,
    'scientific_status': 'validation_candidate_only',
    'prohibited_claims': ['validated vertical subsidence', 'validated hazard', 'validated risk',
                          'coverage outside the exact 380-cell strict mask'],
}
temporary = DECISION_PATH.with_suffix('.json.partial')
temporary.write_text(json.dumps(decision, indent=2, allow_nan=False) + '\n', encoding='utf-8')
os.replace(temporary, DECISION_PATH)
print(json.dumps(decision, indent=2))
'''
    ),
    code(
        r'''# 11 - Verify every artifact and archive the compact sensitivity decision
candidate_artifacts = {}
for reference_id in ('quality_west', 'quality_east', 'quality_south'):
    _, target, archive, sidecar = candidate_paths(reference_id)
    fields = sidecar.read_text(encoding='utf-8').strip().split()
    observed = sha256_file(archive)
    if len(fields) < 2 or fields[0] != observed or Path(fields[1]).name != archive.name:
        raise RuntimeError(f'Candidate archive verification failed: {reference_id}')
    if not candidate_complete(target, next(item for item in references if item['id'] == reference_id)):
        raise RuntimeError(f'Candidate provenance verification failed: {reference_id}')
    candidate_artifacts[reference_id] = {'archive': str(archive), 'bytes': archive.stat().st_size,
                                         'sha256': observed, 'sidecar': str(sidecar)}

manifest = {
    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'configuration_fingerprint': preregistration['configuration_fingerprint'],
    'preregistration': {'path': str(PREREGISTRATION_PATH), 'sha256': sha256_file(PREREGISTRATION_PATH)},
    'decision': {'path': str(DECISION_PATH), 'sha256': sha256_file(DECISION_PATH),
                 'outcome': decision['outcome']},
    'baseline_results': {'path': str(BASELINE_RESULTS_ARCHIVE), 'sha256': baseline_sha},
    'candidate_artifacts': candidate_artifacts,
    'next_required_stage': 'independent date-compatible GNSS or levelling validation',
}
SUMMARY_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, allow_nan=False) + '\n', encoding='utf-8')
summary_sha = atomic_archive(SENSITIVITY_DIR,
                             [PREREGISTRATION_PATH.name, DECISION_PATH.name, SUMMARY_MANIFEST_PATH.name],
                             SUMMARY_ARCHIVE)
SUMMARY_ARCHIVE_SHA.write_text(f'{summary_sha}  {SUMMARY_ARCHIVE.name}\n', encoding='utf-8')
print(f'VERIFIED v14 summary archive: {SUMMARY_ARCHIVE} ({SUMMARY_ARCHIVE.stat().st_size / 1e6:.2f} MB)')
print('SHA-256:', summary_sha)
print('PREREGISTERED V14 OUTCOME:', decision['outcome'])
print('STOP and return to Codex. No rate is validated until independent GNSS/levelling validation succeeds.')
'''
    ),
]

notebook = {
    "cells": cells,
    "metadata": v13["metadata"],
    "nbformat": v13["nbformat"],
    "nbformat_minor": v13["nbformat_minor"],
}
# Match the archived notebook's registered bytes on every OS.
OUTPUT.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\r\n")
print(OUTPUT)
