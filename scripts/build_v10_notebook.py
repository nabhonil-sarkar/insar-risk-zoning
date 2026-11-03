"""Build the self-contained, preregistered Jakarta v10 Colab notebook."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "notebooks" / "LiCSBAS_Jakarta_north_branch_recovery_v10.ipynb"


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


cells = [
    markdown(
        """# LiCSBAS Jakarta v10 — preregistered North Jakarta branch recovery

This notebook implements the frozen v10 experiment recorded in `PROJECT_CONTEXT.md`. It does **not** change the wrapped signal, coherence, masks, pair inventory, 0.3 unwrapping-consistency threshold, 1.5-radian loop threshold, or the LiCSBAS network gates. The only permitted intervention is a deterministic whole-SNAPHU-component offset of `2*pi*k`, where `k` is an integer inferred from redundant triangle closure.

The experiment uses five held-out loop folds. A corrected stack is not written unless every fold improves without creating a new closure error and the same component integer is recovered in all five fits. After writing, exact wrapped-phase and immutable-data checks run before LiCSBAS. All 113 measurable North Jakarta loop-failure pixels must reach `n_loop_err=0`, with no new error anywhere, before inversion is allowed. A failure or partial improvement is a hard stop—do not bypass it or tune parameters in this notebook.

Run cells in order. Fold ledgers and verified archives are saved to Drive, so a disconnected session can resume by rerunning from the top. Outputs remain diagnostic; even a pass cannot restore the separate 361 northern pixels with no finite v9 inversion output and cannot validate a citywide hazard or risk map.
"""
    ),
    code(
        """# 1 — Mount Drive
from google.colab import drive
drive.mount('/content/drive')
"""
    ),
    code(
        """# 2 — Install and pin LiCSBAS plus the MintPy reference implementation
import os, sys, subprocess
from pathlib import Path

LICSBAS_REPO = Path('/content/LiCSBAS')
MINTPY_REPO = Path('/content/MintPy')
LICSBAS_COMMIT = 'a145e6c4217b29eb7348ea95630454a099809098'
MINTPY_COMMIT = '297aa16018b93ba0d247413a56855cf012b8a7bb'

subprocess.run(['apt-get', 'update', '-qq'], check=True)
subprocess.run(['apt-get', 'install', '-y', '-qq', 'gdal-bin', 'libgdal-dev', 'python3-gdal'], check=True)
for repo, url, commit in (
    (LICSBAS_REPO, 'https://github.com/comet-licsar/LiCSBAS.git', LICSBAS_COMMIT),
    (MINTPY_REPO, 'https://github.com/insarlab/MintPy.git', MINTPY_COMMIT),
):
    if not repo.exists():
        subprocess.run(['git', 'clone', url, str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'fetch', '--all', '--tags'], check=True)
    subprocess.run(['git', '-C', str(repo), 'checkout', '--detach', commit], check=True)
    actual = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != commit:
        raise RuntimeError(f'Pinned commit mismatch for {repo.name}: {actual} != {commit}')

subprocess.run([
    sys.executable, '-m', 'pip', 'install', '-q',
    'h5py', 'statsmodels', 'astropy', 'cmcrameri', 'bottleneck', 'rasterio',
    'requests', 'beautifulsoup4', 'psutil', 'netCDF4', 'colorcet', 'xarray',
    'rioxarray', 'pandas', 'scipy', 'scikit-learn', 'affine', 'shapely',
], check=True)
try:
    from osgeo import gdal
except ImportError:
    gdal_version = subprocess.check_output(['gdal-config', '--version'], text=True).strip()
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', f'GDAL=={gdal_version}'], check=True)
    from osgeo import gdal

print('LiCSBAS commit:', LICSBAS_COMMIT)
print('MintPy reference commit:', MINTPY_COMMIT)
print('GDAL:', gdal.VersionInfo())
"""
    ),
    code(
        """# 3 — Frozen experiment configuration and common helpers
import csv, datetime, hashlib, json, math, re, shutil, tarfile, time, warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import requests
import rasterio
from rasterio.features import rasterize
from scipy import sparse
from shapely.geometry import shape
from shapely.ops import unary_union
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import Lasso

FRAME = '098A_09673_121312'
START, END = '20200101', '20231231'
DATE_TAG = f'{START}_{END}'
WIDTH, LENGTH = 154, 106
EXPECTED_PAIRS = 609
EXPECTED_STEP11_BAD = 8
EXPECTED_TRIANGLES = 1110
EXPECTED_RETAINED_TRIANGLES = 990
EXPECTED_NORTH_PIXELS = 477
EXPECTED_NORTH_MEASURABLE = 116
EXPECTED_NORTH_LOOP_FAILED = 113
EXPECTED_BASE_STRICT = 2477
EXPECTED_BASE_LOOP_EVENTS = 1398

CHECKPOINT_SHA256 = '3329cd9c75d5c96e604f0c9b3b950fe127018bfebc06d2c19f9426b3fb234efb'
INVENTORY_SHA256 = 'cf06e2235374b36aa8d5ca790adf8356ebd8b1d40daf0aa2e45e739a016e52af'
RESULTS_SHA256 = '99f38ec03233f900a6c28ee629e279df8aed427e18c70c8101a9e4f094bbd23d'
QC_SHA256 = 'c8293d4d33d208458a7677aa0e12ee935b9b74d753226c0022b78483dd68acc7'
BOUNDARY_SHA256 = '7bb4dd0589cec8bd64e8930c94b1835116701b6148f7b7de183e61196593c540'
ATTRIBUTION_SHA256 = '879a6626d7e65acf056663ce7e5aaca97ed73242071c29d0cbbee15383f6da3f'

LOOP_THRESHOLD_RAD = 1.5
PIXEL_LOOP_ERROR_RAD = float(np.pi)
UNWRAP_CONSISTENCY_THRESHOLD = 0.3
L1_ALPHA = 1e-2
N_FOLDS = 5
MIN_COMPONENT_PIXELS = 9
MAX_COMPONENT_SAMPLES = 100
WRAPPED_TOLERANCE_RAD = 1e-6
INTEGER_TOLERANCE = 1e-6

MIN_LCC_IMAGE_FRACTION = 0.90
MIN_LCC_TEMPORAL_SPAN_FRACTION = 0.95
MIN_LCC_EDGE_TO_IMAGE_RATIO = 2.0
MAX_LCC_BRIDGES = 0
MAX_LCC_WITHOUT_TRIANGLE = 0

DRIVE_ROOT = Path('/content/drive/MyDrive/InSAR_Risk_Zoning_Project')
ARCHIVE_DIR = DRIVE_ROOT / 'LiCSBAS_archive_2020_2023'
WORK = Path('/content/insar_v10')
BASE_GEOC_NAME = 'GEOCml5clip'
CAND_GEOC_NAME = 'GEOCml5clip_v10_ccint'
CAND_TS_NAME = 'TS_GEOCml5clip_v10_ccint_mp'
RUN_TAG = 'v10_ccint_roi_ml5_mp'
BIN = LICSBAS_REPO / 'bin'
LIB = LICSBAS_REPO / 'LiCSBAS_lib'

CHECKPOINT = ARCHIVE_DIR / 'GEOCml5clip_reunw_unfiltered_roi_ml5_mp_20200101_20231231_checkpoint.tar.gz'
CHECKPOINT_SHA_FILE = ARCHIVE_DIR / 'GEOCml5clip_reunw_unfiltered_roi_ml5_mp_20200101_20231231_checkpoint.sha256'
INVENTORY = ARCHIVE_DIR / 'GEOCml5clip_reunw_unfiltered_roi_ml5_mp_20200101_20231231_inventory.json'
BASE_RESULTS = ARCHIVE_DIR / 'TS_GEOCml5clip_reunw_mp_results_20200101_20231231.tar.gz'
BASE_RESULTS_SHA_FILE = ARCHIVE_DIR / 'TS_GEOCml5clip_reunw_mp_results_20200101_20231231.sha256'
QC_SUMMARY = DRIVE_ROOT / 'jakarta_licsbas_20200101_20231231_reunw_unfiltered_roi_ml5_mp_qc_summary.json'
BOUNDARY_URL = ('https://gis-dpmptsp.jakarta.go.id/arcgis/rest/services/Hosted/'
                'Batas_Administrasi_Kelurahan_DKI_Jakarta/FeatureServer/85/query'
                '?where=1%3D1&outFields=wadmkd%2Cwadmkc%2Cwadmkk&returnGeometry=true&outSR=4326&f=geojson')
BOUNDARY_LOCAL = WORK / 'dki_kelurahan_official.geojson'

FOLD_DIR = ARCHIVE_DIR / f'{RUN_TAG}_fold_ledgers'
STABLE_LEDGER_PATH = ARCHIVE_DIR / f'{RUN_TAG}_stable_component_ledger.json'
CV_REPORT_PATH = ARCHIVE_DIR / f'{RUN_TAG}_heldout_validation.json'
CAND_ARCHIVE = ARCHIVE_DIR / f'{CAND_GEOC_NAME}_{DATE_TAG}_checkpoint.tar.gz'
CAND_ARCHIVE_SHA = ARCHIVE_DIR / f'{CAND_GEOC_NAME}_{DATE_TAG}_checkpoint.sha256'
NETWORK_GATE_PATH = DRIVE_ROOT / f'jakarta_licsbas_{DATE_TAG}_{RUN_TAG}_network_gate.json'
QC_OUT = DRIVE_ROOT / f'jakarta_licsbas_{DATE_TAG}_{RUN_TAG}_qc_summary.json'
MANIFEST_OUT = DRIVE_ROOT / f'jakarta_licsbas_{DATE_TAG}_{RUN_TAG}_manifest.json'

PAIR_RE = re.compile(r'^\\d{8}_\\d{8}$')
WORK.mkdir(parents=True, exist_ok=True)
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
FOLD_DIR.mkdir(parents=True, exist_ok=True)

def sha256_file(path, chunk_size=8 * 1024 * 1024):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()

def verified_hash(path, expected):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f'SHA-256 mismatch for {path.name}: {actual} != {expected}')
    return actual

def data_lines(text):
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]

def pair_dirs(root):
    root = Path(root)
    return sorted(p for p in root.iterdir() if p.is_dir() and PAIR_RE.fullmatch(p.name)) if root.exists() else []

def atomic_json(path, payload):
    path = Path(path)
    partial = path.with_suffix(path.suffix + '.partial')
    partial.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(partial, path)

def safe_remove_tree(path):
    path = Path(path).resolve()
    work = WORK.resolve()
    if path == work or work not in path.parents:
        raise RuntimeError(f'Refusing to remove path outside the v10 workspace: {path}')
    if path.exists():
        shutil.rmtree(path)

def archive_atomic(source_root, relative_items, destination):
    destination = Path(destination)
    partial = destination.with_suffix(destination.suffix + '.partial')
    if partial.exists():
        partial.unlink()
    subprocess.run(['tar', '-czf', str(partial), '-C', str(source_root), *relative_items], check=True)
    subprocess.run(['tar', '-tzf', str(partial)], check=True, stdout=subprocess.DEVNULL)
    if partial.stat().st_size == 0:
        raise RuntimeError(f'Empty archive: {partial}')
    os.replace(partial, destination)
    return sha256_file(destination)

run_env = os.environ.copy()
run_env['PYTHONPATH'] = os.pathsep.join([str(LIB), run_env.get('PYTHONPATH', '')]).rstrip(os.pathsep)

def resolve_script(preferred, fragments):
    exact = BIN / preferred
    if exact.exists():
        return exact
    candidates = sorted(p for p in BIN.glob('LiCSBAS*.py') if all(x.lower() in p.name.lower() for x in fragments))
    if len(candidates) != 1:
        raise RuntimeError(f'Cannot resolve {preferred}: {candidates}')
    return candidates[0]

SCRIPTS = {
    'check': resolve_script('LiCSBAS11_check_unw.py', ('11', 'check_unw')),
    'loop': resolve_script('LiCSBAS12_loop_closure.py', ('12', 'loop')),
    'invert': resolve_script('LiCSBAS13_sb_inv.py', ('13', 'sb_inv')),
    'vstd': resolve_script('LiCSBAS14_vel_std.py', ('14', 'vel_std')),
    'geotiff': resolve_script('LiCSBAS_flt2geotiff.py', ('flt2geotiff',)),
}

def run_script(role, args, required=()):
    cmd = [sys.executable, str(SCRIPTS[role]), *map(str, args)]
    print('RUN:', ' '.join(cmd), flush=True)
    completed = subprocess.run(cmd, cwd=WORK, env=run_env)
    if completed.returncode != 0:
        raise RuntimeError(f'{role} failed with return code {completed.returncode}')
    missing = [str(p) for p in required if not Path(p).exists()]
    if missing:
        raise RuntimeError(f'{role} completed but required output is missing: {missing}')
    return completed

print(json.dumps({
    'run_tag': RUN_TAG, 'pairs': EXPECTED_PAIRS, 'folds': N_FOLDS,
    'l1_alpha': L1_ALPHA, 'min_component_pixels': MIN_COMPONENT_PIXELS,
    'max_component_samples': MAX_COMPONENT_SAMPLES,
    'loop_threshold_rad': LOOP_THRESHOLD_RAD,
}, indent=2))
"""
    ),
    markdown(
        """## Restore and reproduce the frozen v9 baseline

The next two cells verify every supplied artifact, restore the 609-pair numerical checkpoint, and reproduce the saved LiCSBAS loop-error raster exactly. If the equality check fails at even one pixel, the experiment stops before fitting.
"""
    ),
    code(
        """# 4 — Verify and restore all frozen inputs
verified_hash(CHECKPOINT, CHECKPOINT_SHA256)
verified_hash(INVENTORY, INVENTORY_SHA256)
verified_hash(BASE_RESULTS, RESULTS_SHA256)
verified_hash(QC_SUMMARY, QC_SHA256)

if CHECKPOINT_SHA_FILE.is_file():
    supplied = CHECKPOINT_SHA_FILE.read_text(encoding='utf-8').strip().split()[0].lower()
    if supplied != CHECKPOINT_SHA256:
        raise RuntimeError('Checkpoint .sha256 file does not contain the frozen checksum.')
if BASE_RESULTS_SHA_FILE.is_file():
    supplied = BASE_RESULTS_SHA_FILE.read_text(encoding='utf-8').strip().split()[0].lower()
    if supplied != RESULTS_SHA256:
        raise RuntimeError('Results .sha256 file does not contain the frozen checksum.')

base_geoc = WORK / BASE_GEOC_NAME
if not base_geoc.exists():
    subprocess.run(['tar', '-xzf', str(CHECKPOINT), '-C', str(WORK)], check=True)
if len(pair_dirs(base_geoc)) != EXPECTED_PAIRS:
    raise RuntimeError(f'Restored checkpoint does not contain {EXPECTED_PAIRS} pair folders.')

inventory = json.loads(INVENTORY.read_text(encoding='utf-8'))
if inventory['complete_pairs'] != EXPECTED_PAIRS or inventory['missing_unw'] or inventory['missing_cc'] or inventory['missing_conncomp']:
    raise RuntimeError('Frozen checkpoint inventory is incomplete.')
for pair_dir in pair_dirs(base_geoc):
    pair = pair_dir.name
    expected_sizes = {f'{pair}.unw': WIDTH * LENGTH * 4, f'{pair}.cc': WIDTH * LENGTH, f'{pair}.conncomp': WIDTH * LENGTH}
    for name, expected_size in expected_sizes.items():
        path = pair_dir / name
        if not path.is_file() or path.stat().st_size != expected_size:
            raise RuntimeError(f'Unexpected checkpoint member size: {path} ({path.stat().st_size if path.exists() else None} != {expected_size})')

qc_base = json.loads(QC_SUMMARY.read_text(encoding='utf-8'))
vel_meta = qc_base['layer_statistics']['vel']
if list(map(int, vel_meta['shape'])) != [LENGTH, WIDTH] or vel_meta['crs'] != 'EPSG:4326':
    raise RuntimeError('Frozen QC grid metadata does not match the v10 preregistration.')
GRID_TRANSFORM = rasterio.Affine(*map(float, vel_meta['transform'][:6]))

response = requests.get(BOUNDARY_URL, timeout=120)
response.raise_for_status()
BOUNDARY_LOCAL.write_bytes(response.content)
verified_hash(BOUNDARY_LOCAL, BOUNDARY_SHA256)

print('Verified checkpoint:', CHECKPOINT_SHA256)
print('Restored complete pairs:', len(pair_dirs(base_geoc)))
print('Official boundary:', BOUNDARY_SHA256)
"""
    ),
    code(
        """# 5 — Reconstruct all loops and exactly reproduce the saved n_loop_err raster
RESULTS_ROOT = 'TS_GEOCml5clip_reunw_mp/'

def tar_text(bundle, relative):
    stream = bundle.extractfile(RESULTS_ROOT + relative)
    if stream is None:
        raise RuntimeError(f'Baseline results archive is missing {relative}')
    return stream.read().decode('utf-8', errors='replace')

def tar_grid(bundle, relative):
    stream = bundle.extractfile(RESULTS_ROOT + relative)
    if stream is None:
        raise RuntimeError(f'Baseline results archive is missing {relative}')
    values = np.frombuffer(stream.read(), dtype='<f4')
    if values.size != LENGTH * WIDTH:
        raise RuntimeError(f'Unexpected baseline grid size for {relative}: {values.size}')
    return values.reshape(LENGTH, WIDTH).copy()

with tarfile.open(BASE_RESULTS, 'r:gz') as bundle:
    bad11 = set(data_lines(tar_text(bundle, 'info/11bad_ifg.txt')))
    bad12 = set(data_lines(tar_text(bundle, 'info/12bad_ifg.txt')))
    ref_text = tar_text(bundle, 'info/12ref.txt').strip()
    base_n_loop_err = tar_grid(bundle, 'results/n_loop_err')
    base_n_gap = tar_grid(bundle, 'results/n_gap')
    base_vel = tar_grid(bundle, 'results/vel')
    base_vstd = tar_grid(bundle, 'results/vstd')

ref_match = re.fullmatch(r'(\\d+):(\\d+)/(\\d+):(\\d+)', ref_text)
if not ref_match:
    raise RuntimeError(f'Cannot parse frozen reference area: {ref_text!r}')
REF_X1, REF_X2, REF_Y1, REF_Y2 = map(int, ref_match.groups())

all_pairs = sorted(p.name for p in pair_dirs(base_geoc))
ifgdates = sorted(set(all_pairs) - bad11)
if len(bad11) != EXPECTED_STEP11_BAD or len(ifgdates) != EXPECTED_PAIRS - EXPECTED_STEP11_BAD:
    raise RuntimeError('Frozen step-11 network does not match the preregistration.')

def make_loops(pairs):
    ordered = sorted(pairs)
    pair_set = set(ordered)
    by_first = defaultdict(list)
    for pair in ordered:
        by_first[pair[:8]].append(pair)
    loops = []
    for pair12 in ordered:
        first, second = pair12.split('_')
        for pair23 in by_first.get(second, []):
            third = pair23[-8:]
            pair13 = f'{first}_{third}'
            if pair13 in pair_set:
                loops.append((pair12, pair23, pair13))
    return loops

all_loops = make_loops(ifgdates)
if len(all_loops) != EXPECTED_TRIANGLES:
    raise RuntimeError(f'Expected {EXPECTED_TRIANGLES} triangles, found {len(all_loops)}')
retained_loops = [loop for loop in all_loops if not any(pair in bad12 for pair in loop)]
if len(retained_loops) != EXPECTED_RETAINED_TRIANGLES:
    raise RuntimeError(f'Expected {EXPECTED_RETAINED_TRIANGLES} retained triangles, found {len(retained_loops)}')

unwrapped, components = {}, {}
for pair in all_pairs:
    pair_dir = base_geoc / pair
    unw = np.fromfile(pair_dir / f'{pair}.unw', dtype='<f4').reshape(LENGTH, WIDTH)
    unw = unw.copy(); unw[unw == 0] = np.nan
    unwrapped[pair] = unw
    components[pair] = np.fromfile(pair_dir / f'{pair}.conncomp', dtype='uint8').reshape(LENGTH, WIDTH)

def referenced_loop_phase(loop, arrays):
    pair12, pair23, pair13 = loop
    unw12, unw23, unw13 = arrays[pair12], arrays[pair23], arrays[pair13]
    with np.errstate(invalid='ignore'):
        ref12 = np.nanmean(unw12[REF_Y1:REF_Y2, REF_X1:REF_X2])
        ref23 = np.nanmean(unw23[REF_Y1:REF_Y2, REF_X1:REF_X2])
        ref13 = np.nanmean(unw13[REF_Y1:REF_Y2, REF_X1:REF_X2])
        return unw12 + unw23 - unw13 - (ref12 + ref23 - ref13)

def loop_error(phase):
    valid = ~np.isnan(phase)
    gate_phase = phase.copy(); gate_phase[~valid] = 0
    return ~(np.abs(gate_phase) < PIXEL_LOOP_ERROR_RAD)

reconstructed = np.zeros((LENGTH, WIDTH), dtype='uint16')
for loop in retained_loops:
    reconstructed += loop_error(referenced_loop_phase(loop, unwrapped)).astype('uint16')
expected_counts = base_n_loop_err.astype('uint16')
if not np.array_equal(reconstructed, expected_counts):
    difference = reconstructed.astype('int32') - expected_counts.astype('int32')
    raise RuntimeError(f'BASELINE REPRODUCTION FAILED: {(difference != 0).sum()} pixels differ; max abs={np.abs(difference).max()}')

boundary = json.loads(BOUNDARY_LOCAL.read_text(encoding='utf-8'))
north_geometries = [shape(feature['geometry']) for feature in boundary['features'] if str(feature['properties'].get('wadmkk', '')).strip() == 'JAKARTA UTARA']
if not north_geometries:
    raise RuntimeError('Official boundary contains no North Jakarta features.')
north_mask = rasterize([(unary_union(north_geometries), 1)], out_shape=(LENGTH, WIDTH), transform=GRID_TRANSFORM, fill=0, all_touched=False, dtype='uint8').astype(bool)
measurable_north = north_mask & np.isfinite(base_vel) & np.isfinite(base_vstd)
target_north = measurable_north & (base_n_loop_err > 0)
base_strict = np.isfinite(base_vel) & np.isfinite(base_vstd) & (base_n_gap == 0) & (base_n_loop_err == 0)
if (int(north_mask.sum()), int(measurable_north.sum()), int(target_north.sum()), int(base_strict.sum())) != (EXPECTED_NORTH_PIXELS, EXPECTED_NORTH_MEASURABLE, EXPECTED_NORTH_LOOP_FAILED, EXPECTED_BASE_STRICT):
    raise RuntimeError('Frozen North/strict pixel counts do not match the preregistration.')
if int(reconstructed[target_north].sum()) != EXPECTED_BASE_LOOP_EVENTS:
    raise RuntimeError('Frozen North loop-event total does not match the preregistration.')

loop_ids = ['_'.join((loop[0][:8], loop[0][-8:], loop[1][-8:])) for loop in all_loops]
loop_folds = np.array([int(hashlib.sha256(loop_id.encode()).hexdigest(), 16) % N_FOLDS for loop_id in loop_ids], dtype='uint8')
print(json.dumps({
    'baseline_reproduction': 'exact', 'whole_grid_pixels': LENGTH * WIDTH,
    'triangles': len(all_loops), 'retained_triangles': len(retained_loops),
    'north_pixels': int(north_mask.sum()), 'north_target_pixels': int(target_north.sum()),
    'north_loop_events': int(reconstructed[target_north].sum()),
    'baseline_strict_pixels': int(base_strict.sum()), 'reference_area': ref_text,
    'fold_counts': {str(f): int((loop_folds == f).sum()) for f in range(N_FOLDS)},
}, indent=2))
"""
    ),
    markdown(
        """## Deterministic five-fold integer solution

This cell fits the preregistered L1 objective at North Jakarta pixels and aggregates the rounded edge ambiguity by original SNAPHU component. The `sklearn` coefficient scales `alpha` by the number of equations so its objective is algebraically equivalent to `||A*x-y||² + 0.01||x||₁`. Completed folds are saved individually to Drive and reused only when their configuration fingerprint matches exactly.
"""
    ),
    code(
        """# 6 — Fit deterministic integer ambiguity on four folds and checkpoint each result
pair_index = {pair: index for index, pair in enumerate(ifgdates)}
rows, cols, values = [], [], []
for row, (pair12, pair23, pair13) in enumerate(all_loops):
    for pair, value in ((pair12, 1), (pair23, 1), (pair13, -1)):
        rows.append(row); cols.append(pair_index[pair]); values.append(value)
C = sparse.csr_matrix((values, (rows, cols)), shape=(len(all_loops), len(ifgdates)), dtype='float64')

north_coords = np.column_stack(np.where(north_mask))
coord_to_index = {tuple(coord): index for index, coord in enumerate(north_coords)}

component_samples = {}
for pair in ifgdates:
    labels = components[pair]
    reference_label = int(labels[REF_Y1, REF_X1])
    for label in sorted(int(value) for value in np.unique(labels[north_mask]) if value != 0):
        if label == reference_label:
            continue
        coords = np.column_stack(np.where(north_mask & (labels == label)))
        if len(coords) < MIN_COMPONENT_PIXELS:
            continue
        order = np.lexsort((coords[:, 1], coords[:, 0])); coords = coords[order]
        if len(coords) > MAX_COMPONENT_SAMPLES:
            selection = np.linspace(0, len(coords) - 1, MAX_COMPONENT_SAMPLES, dtype=int)
            coords = coords[selection]
        component_samples[f'{pair}|{label}'] = [coord_to_index[tuple(coord)] for coord in coords]

SOLVER_SCHEMA = 'v10_north_component_l1_schema1'
CONFIG_FINGERPRINT = hashlib.sha256(json.dumps({
    'solver_schema': SOLVER_SCHEMA,
    'checkpoint': CHECKPOINT_SHA256, 'results': RESULTS_SHA256, 'boundary': BOUNDARY_SHA256,
    'alpha': L1_ALPHA, 'folds': N_FOLDS, 'min_pixels': MIN_COMPONENT_PIXELS,
    'max_samples': MAX_COMPONENT_SAMPLES, 'loop_ids': loop_ids,
}, sort_keys=True).encode()).hexdigest()

def pixel_closure_integer(y, x):
    closure = np.full(len(all_loops), np.nan, dtype='float64')
    for index, (pair12, pair23, pair13) in enumerate(all_loops):
        values_here = (unwrapped[pair12][y, x], unwrapped[pair23][y, x], unwrapped[pair13][y, x])
        if all(np.isfinite(value) for value in values_here):
            phase = float(values_here[0] + values_here[1] - values_here[2])
            wrapped = float(np.angle(np.exp(1j * phase)))
            closure[index] = np.rint((phase - wrapped) / (2 * np.pi))
    return closure

closure_by_north_pixel = np.stack([pixel_closure_integer(int(y), int(x)) for y, x in north_coords])

def fit_fold(fold):
    estimates = np.full((len(north_coords), len(ifgdates)), np.nan, dtype='float32')
    train_fold_mask = loop_folds != fold
    for pixel_index in range(len(north_coords)):
        closure = closure_by_north_pixel[pixel_index]
        selected = train_fold_mask & np.isfinite(closure)
        selected_rows = np.where(selected)[0]
        if selected_rows.size == 0:
            continue
        X_all = -C[selected_rows]
        active = np.unique(X_all.indices)
        if active.size == 0:
            continue
        X = X_all[:, active]
        y = closure[selected_rows]
        # sklearn minimizes (1/(2*n))*||y-Xb||^2 + alpha*||b||_1.
        # This scaling exactly represents ||y-Xb||^2 + L1_ALPHA*||b||_1.
        model = Lasso(
            alpha=L1_ALPHA / (2 * len(y)), fit_intercept=False,
            max_iter=20000, tol=1e-8, selection='cyclic',
        )
        with warnings.catch_warnings():
            warnings.simplefilter('error', ConvergenceWarning)
            model.fit(X, y)
        estimates[pixel_index, active] = np.rint(model.coef_).astype('float32')
        if (pixel_index + 1) % 50 == 0:
            print(f'fold {fold}: fitted {pixel_index + 1}/{len(north_coords)} North pixels', flush=True)

    records = {}
    for key, sample_indices in component_samples.items():
        pair, label_text = key.split('|')
        values_here = estimates[sample_indices, pair_index[pair]]
        values_here = values_here[np.isfinite(values_here)]
        if values_here.size < MIN_COMPONENT_PIXELS:
            continue
        median = float(np.median(values_here))
        if not math.isclose(median, round(median), rel_tol=0, abs_tol=INTEGER_TOLERANCE):
            continue
        unique, counts = np.unique(values_here.astype('int16'), return_counts=True)
        records[key] = {
            'pair': pair, 'label': int(label_text), 'k': int(round(median)),
            'sample_count': int(values_here.size),
            'sample_integer_counts': {str(int(value)): int(count) for value, count in zip(unique, counts)},
        }
    return records

fold_ledgers = []
for fold in range(N_FOLDS):
    fold_path = FOLD_DIR / f'fold_{fold}.json'
    fold_sha_path = fold_path.with_suffix('.json.sha256')
    if fold_path.is_file() and fold_sha_path.is_file():
        supplied_fold_sha = fold_sha_path.read_text(encoding='utf-8').strip().split()[0]
        if sha256_file(fold_path) != supplied_fold_sha:
            raise RuntimeError(f'Existing fold ledger checksum mismatch: {fold_path}')
        payload = json.loads(fold_path.read_text(encoding='utf-8'))
        if payload.get('configuration_fingerprint') == CONFIG_FINGERPRINT:
            print(f'Restored verified-configuration fold ledger: {fold_path}')
            fold_ledgers.append(payload['components'])
            continue
    started = time.time()
    components_fold = fit_fold(fold)
    payload = {
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'configuration_fingerprint': CONFIG_FINGERPRINT, 'fold': fold,
        'training_triangles': int((loop_folds != fold).sum()),
        'heldout_triangles': int((loop_folds == fold).sum()),
        'components': components_fold, 'runtime_seconds': time.time() - started,
    }
    atomic_json(fold_path, payload)
    fold_sha_path.write_text(f'{sha256_file(fold_path)}  {fold_path.name}\\n', encoding='utf-8')
    fold_ledgers.append(components_fold)
    print(f'Verified fold ledger {fold}: {len(components_fold)} eligible components')

common_keys = set.intersection(*(set(ledger) for ledger in fold_ledgers))
stable_records = []
for key in sorted(common_keys):
    ks = [int(ledger[key]['k']) for ledger in fold_ledgers]
    if len(set(ks)) == 1 and ks[0] != 0:
        record = dict(fold_ledgers[0][key])
        record['k_by_fold'] = ks
        record['fold_sample_integer_counts'] = [ledger[key]['sample_integer_counts'] for ledger in fold_ledgers]
        stable_records.append(record)

stable_payload = {
    'scientific_status': 'candidate_integer_ledger_pending_heldout_gate',
    'configuration_fingerprint': CONFIG_FINGERPRINT,
    'method': {
        'triangle_folds': 'SHA256(loop_id) mod 5', 'l1_alpha': L1_ALPHA,
        'min_component_pixels': MIN_COMPONENT_PIXELS,
        'max_deterministic_samples': MAX_COMPONENT_SAMPLES,
        'whole_original_snaphu_components_only': True,
    },
    'stable_nonzero_components': stable_records,
}
atomic_json(STABLE_LEDGER_PATH, stable_payload)
(STABLE_LEDGER_PATH.with_suffix('.json.sha256')).write_text(f'{sha256_file(STABLE_LEDGER_PATH)}  {STABLE_LEDGER_PATH.name}\\n', encoding='utf-8')
if not stable_records:
    raise RuntimeError('PREREGISTERED STOP: no non-zero component integer is identical across all five fits; do not write a corrected stack.')

stable_corrections = defaultdict(dict)
for record in stable_records:
    stable_corrections[record['pair']][int(record['label'])] = int(record['k'])
print('Stable non-zero whole-component corrections:', len(stable_records))
print('Stable ledger:', STABLE_LEDGER_PATH)
"""
    ),
    code(
        """# 7 — Score the stable correction on every held-out fold; hard stop on any regression
def apply_correction(pair):
    original = unwrapped[pair]
    corrected = original.copy()
    for label, k in stable_corrections.get(pair, {}).items():
        corrected[components[pair] == label] += np.float32(2 * np.pi * k)
    return corrected

corrected_in_memory = {pair: apply_correction(pair) for pair in all_pairs}
fold_reports = []
for fold in range(N_FOLDS):
    whole_before = whole_after = north_before = north_after = new_events = 0
    for loop_index in np.where(loop_folds == fold)[0]:
        loop = all_loops[int(loop_index)]
        phase_before = referenced_loop_phase(loop, unwrapped)
        phase_after = referenced_loop_phase(loop, corrected_in_memory)
        before = loop_error(phase_before)
        after = loop_error(phase_after)
        whole_before += int(before.sum()); whole_after += int(after.sum())
        north_before += int((before & north_mask).sum()); north_after += int((after & north_mask).sum())
        new_events += int((~before & after).sum())
    fold_report = {
        'fold': fold, 'heldout_triangles': int((loop_folds == fold).sum()),
        'whole_grid_events_before': whole_before, 'whole_grid_events_after': whole_after,
        'north_events_before': north_before, 'north_events_after': north_after,
        'new_error_events': new_events,
        'whole_grid_strict_decrease': whole_after < whole_before,
        'north_strict_decrease': north_after < north_before,
        'no_new_error_event': new_events == 0,
    }
    fold_report['passed'] = all((fold_report['whole_grid_strict_decrease'], fold_report['north_strict_decrease'], fold_report['no_new_error_event']))
    fold_reports.append(fold_report)

cv_report = {
    'scientific_status': 'heldout_gate_evaluated',
    'configuration_fingerprint': CONFIG_FINGERPRINT,
    'stable_ledger_sha256': sha256_file(STABLE_LEDGER_PATH),
    'folds': fold_reports, 'passed': all(report['passed'] for report in fold_reports),
}
atomic_json(CV_REPORT_PATH, cv_report)
(CV_REPORT_PATH.with_suffix('.json.sha256')).write_text(f'{sha256_file(CV_REPORT_PATH)}  {CV_REPORT_PATH.name}\\n', encoding='utf-8')
print(json.dumps(cv_report, indent=2))
if not cv_report['passed']:
    raise RuntimeError('PREREGISTERED STOP: held-out loop improvement/no-new-error gate failed. Do not tune or materialize a corrected stack.')
print('HELD-OUT GATE PASSED — a candidate stack may now be materialized and checked for exact invariants.')
"""
    ),
    markdown(
        """## Materialize only after held-out success

This cell applies the stable ledger to whole original component labels, then proves that filenames, masks, CC values, component labels and wrapped phase are unchanged. It saves an atomic, checksummed candidate checkpoint only after every invariant passes.
"""
    ),
    code(
        """# 8 — Write the candidate stack, enforce immutable-data gates, and checkpoint it
cand_geoc = WORK / CAND_GEOC_NAME
restored_candidate = False
if CAND_ARCHIVE.is_file() and CAND_ARCHIVE_SHA.is_file():
    supplied = CAND_ARCHIVE_SHA.read_text(encoding='utf-8').strip().split()[0]
    if sha256_file(CAND_ARCHIVE) != supplied:
        raise RuntimeError('Existing v10 candidate checkpoint fails its checksum.')
    safe_remove_tree(cand_geoc)
    subprocess.run(['tar', '-xzf', str(CAND_ARCHIVE), '-C', str(WORK)], check=True)
    restored_candidate = True
    print('Restored existing verified candidate checkpoint:', CAND_ARCHIVE)
else:
    safe_remove_tree(cand_geoc)
    shutil.copytree(base_geoc, cand_geoc)
    for pair, label_map in stable_corrections.items():
        corrected = np.fromfile(cand_geoc / pair / f'{pair}.unw', dtype='<f4').reshape(LENGTH, WIDTH).copy()
        labels = components[pair]
        for label, k in label_map.items():
            selected = (labels == label) & (corrected != 0)
            corrected[selected] += np.float32(2 * np.pi * k)
        corrected.astype('<f4').tofile(cand_geoc / pair / f'{pair}.unw')


# Re-run the complete immutable-data audit even after restoring a verified archive.
invariant_failures, changed_pairs = [], []
for pair in all_pairs:
    base_dir, cand_dir = base_geoc / pair, cand_geoc / pair
    for suffix in ('cc', 'conncomp'):
        if sha256_file(base_dir / f'{pair}.{suffix}') != sha256_file(cand_dir / f'{pair}.{suffix}'):
            invariant_failures.append(f'{pair}.{suffix} changed')
    original_raw = np.fromfile(base_dir / f'{pair}.unw', dtype='<f4').reshape(LENGTH, WIDTH)
    candidate_raw = np.fromfile(cand_dir / f'{pair}.unw', dtype='<f4').reshape(LENGTH, WIDTH)
    if not np.array_equal(original_raw == 0, candidate_raw == 0):
        invariant_failures.append(f'{pair} zero/nodata mask changed')
        continue
    finite = (original_raw != 0) & np.isfinite(original_raw) & np.isfinite(candidate_raw)
    delta_cycles = (candidate_raw[finite] - original_raw[finite]) / (2 * np.pi)
    if delta_cycles.size and np.max(np.abs(delta_cycles - np.rint(delta_cycles))) > INTEGER_TOLERANCE:
        invariant_failures.append(f'{pair} contains a non-integer-cycle phase change')
    wrapped_difference = np.angle(np.exp(1j * candidate_raw[finite]) * np.exp(-1j * original_raw[finite]))
    if wrapped_difference.size and np.max(np.abs(wrapped_difference)) > WRAPPED_TOLERANCE_RAD:
        invariant_failures.append(f'{pair} wrapped phase changed by more than tolerance')
    eligible = np.zeros((LENGTH, WIDTH), dtype=bool)
    for label in stable_corrections.get(pair, {}):
        eligible |= components[pair] == label
    outside = ~eligible
    if not np.array_equal(original_raw[outside], candidate_raw[outside], equal_nan=True):
        invariant_failures.append(f'{pair} changed outside eligible components')
    if not np.array_equal(original_raw, candidate_raw, equal_nan=True):
        changed_pairs.append(pair)
if invariant_failures:
    safe_remove_tree(cand_geoc)
    raise RuntimeError('PREREGISTERED STOP: immutable-data gate failed: ' + '; '.join(invariant_failures[:10]))

provenance_path = cand_geoc / 'v10_component_correction_provenance.json'
if restored_candidate:
    if not provenance_path.is_file():
        raise RuntimeError('Restored candidate checkpoint has no correction provenance.')
    provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
    if provenance.get('source_checkpoint_sha256') != CHECKPOINT_SHA256:
        raise RuntimeError('Restored candidate was built from a different source checkpoint.')
    if provenance.get('stable_ledger_sha256') != sha256_file(STABLE_LEDGER_PATH):
        raise RuntimeError('Restored candidate stable-ledger hash differs from the current deterministic ledger.')
    if provenance.get('heldout_report_sha256') != sha256_file(CV_REPORT_PATH):
        raise RuntimeError('Restored candidate held-out report differs from the current report.')
    if not provenance.get('immutable_data_gate_passed'):
        raise RuntimeError('Restored candidate provenance does not record an immutable-data pass.')
else:
    provenance = {
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'run_tag': RUN_TAG, 'source_checkpoint_sha256': CHECKPOINT_SHA256,
        'stable_ledger': str(STABLE_LEDGER_PATH), 'stable_ledger_sha256': sha256_file(STABLE_LEDGER_PATH),
        'heldout_report': str(CV_REPORT_PATH), 'heldout_report_sha256': sha256_file(CV_REPORT_PATH),
        'changed_pairs': changed_pairs, 'changed_pair_count': len(changed_pairs),
        'permitted_change': 'whole original SNAPHU component plus 2*pi*k only',
        'wrapped_tolerance_rad': WRAPPED_TOLERANCE_RAD, 'integer_tolerance': INTEGER_TOLERANCE,
        'immutable_data_gate_passed': True,
    }
    provenance_path.write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    candidate_sha = archive_atomic(WORK, [CAND_GEOC_NAME], CAND_ARCHIVE)
    CAND_ARCHIVE_SHA.write_text(f'{candidate_sha}  {CAND_ARCHIVE.name}\\n', encoding='utf-8')
    print('VERIFIED candidate checkpoint:', CAND_ARCHIVE)
    print('Candidate SHA-256:', candidate_sha)

if len(pair_dirs(cand_geoc)) != EXPECTED_PAIRS:
    raise RuntimeError('Candidate checkpoint does not preserve all 609 pair folders.')
print('IMMUTABLE-DATA GATE PASSED — clean LiCSBAS steps 11 and 12 may run.')
"""
    ),
    code(
        """# 9 — Clean LiCSBAS steps 11/12, unchanged structural gate, and complete North recovery gate
ts_root = WORK / CAND_TS_NAME
safe_remove_tree(ts_root)
run_script('check', ['-d', CAND_GEOC_NAME, '-t', CAND_TS_NAME], required=[ts_root / 'info' / '11bad_ifg.txt'])
run_script('loop', ['-d', CAND_GEOC_NAME, '-t', CAND_TS_NAME, '-l', str(LOOP_THRESHOLD_RAD), '--multi_prime'], required=[ts_root / 'info' / '12bad_ifg.txt', ts_root / 'results' / 'n_loop_err'])

bad11_new = set(data_lines((ts_root / 'info' / '11bad_ifg.txt').read_text(encoding='utf-8', errors='replace')))
bad12_new = set(data_lines((ts_root / 'info' / '12bad_ifg.txt').read_text(encoding='utf-8', errors='replace')))
rejected_new = bad11_new | bad12_new
retained_new = sorted(set(all_pairs) - rejected_new)
all_images = sorted({date for pair in all_pairs for date in pair.split('_')})
adjacency = {date: set() for date in all_images}
for pair in retained_new:
    first, second = pair.split('_'); adjacency[first].add(second); adjacency[second].add(first)
components_network, unseen = [], set(all_images)
while unseen:
    start = min(unseen); stack = [start]; connected = set()
    while stack:
        node = stack.pop()
        if node in connected:
            continue
        connected.add(node); unseen.discard(node); stack.extend(adjacency[node] - connected)
    components_network.append(sorted(connected))
components_network.sort(key=lambda value: (-len(value), value[0]))
lcc = components_network[0]; lcc_set = set(lcc)
lcc_ifgs = sorted(pair for pair in retained_new if set(pair.split('_')).issubset(lcc_set))

edge_name = {frozenset(pair.split('_')): pair for pair in lcc_ifgs}
disc, low, parent, bridges, clock = {}, {}, {}, [], [0]
def visit(node):
    disc[node] = low[node] = clock[0]; clock[0] += 1
    for neighbour in sorted(adjacency[node] & lcc_set):
        if neighbour not in disc:
            parent[neighbour] = node; visit(neighbour); low[node] = min(low[node], low[neighbour])
            if low[neighbour] > disc[node]:
                bridges.append(edge_name[frozenset((node, neighbour))])
        elif parent.get(node) != neighbour:
            low[node] = min(low[node], disc[neighbour])
visit(lcc[0])
lcc_without_triangle = []
for pair in lcc_ifgs:
    first, second = pair.split('_')
    if not (adjacency[first] & adjacency[second] & lcc_set):
        lcc_without_triangle.append(pair)

requested_days = (datetime.datetime.strptime(END, '%Y%m%d') - datetime.datetime.strptime(START, '%Y%m%d')).days
lcc_days = (datetime.datetime.strptime(lcc[-1], '%Y%m%d') - datetime.datetime.strptime(lcc[0], '%Y%m%d')).days
network_gate = {
    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'total_interferograms': len(all_pairs), 'step11_bad': len(bad11_new), 'step12_bad': len(bad12_new),
    'unique_rejected': len(rejected_new), 'retained': len(retained_new),
    'rejection_fraction_descriptive': len(rejected_new) / len(all_pairs),
    'largest_component': {
        'image_count': len(lcc), 'image_fraction': len(lcc) / len(all_images),
        'first_image': lcc[0], 'last_image': lcc[-1],
        'temporal_span_fraction': lcc_days / requested_days,
        'interferogram_count': len(lcc_ifgs), 'edge_to_image_ratio': len(lcc_ifgs) / len(lcc),
        'bridges': sorted(bridges), 'without_triangle': sorted(lcc_without_triangle),
    },
    'thresholds_unchanged': True, 'loop_mode': 'multi_prime', 'loop_threshold_rad': LOOP_THRESHOLD_RAD,
}
network_failures = []
lcc_data = network_gate['largest_component']
if lcc_data['image_fraction'] < MIN_LCC_IMAGE_FRACTION: network_failures.append('LCC image fraction')
if lcc_data['temporal_span_fraction'] < MIN_LCC_TEMPORAL_SPAN_FRACTION: network_failures.append('LCC temporal span')
if lcc_data['edge_to_image_ratio'] < MIN_LCC_EDGE_TO_IMAGE_RATIO: network_failures.append('LCC edge/image ratio')
if len(bridges) > MAX_LCC_BRIDGES: network_failures.append('LCC bridges')
if len(lcc_without_triangle) > MAX_LCC_WITHOUT_TRIANGLE: network_failures.append('LCC pairs without triangles')
network_gate['failures'] = network_failures
network_gate['passed'] = not network_failures

candidate_n_loop_err = np.fromfile(ts_root / 'results' / 'n_loop_err', dtype='<f4').reshape(LENGTH, WIDTH)
new_error_pixels = (base_n_loop_err == 0) & (candidate_n_loop_err > 0)
north_unrecovered = target_north & (candidate_n_loop_err > 0)
recovery_gate = {
    'baseline_target_pixels': int(target_north.sum()),
    'target_pixels_reaching_zero': int((target_north & (candidate_n_loop_err == 0)).sum()),
    'target_pixels_still_failing': int(north_unrecovered.sum()),
    'new_error_pixels_anywhere': int(new_error_pixels.sum()),
    'passed': int(north_unrecovered.sum()) == 0 and int(new_error_pixels.sum()) == 0,
}
network_gate['north_recovery_gate'] = recovery_gate
atomic_json(NETWORK_GATE_PATH, network_gate)
(NETWORK_GATE_PATH.with_suffix('.json.sha256')).write_text(f'{sha256_file(NETWORK_GATE_PATH)}  {NETWORK_GATE_PATH.name}\\n', encoding='utf-8')
print(json.dumps(network_gate, indent=2))

DIAGNOSTIC_ARCHIVE = ARCHIVE_DIR / f'{CAND_TS_NAME}_step12_diagnostics_{DATE_TAG}.tar.gz'
DIAGNOSTIC_SHA = archive_atomic(WORK, [f'{CAND_TS_NAME}/info', f'{CAND_TS_NAME}/network', f'{CAND_TS_NAME}/12loop', f'{CAND_TS_NAME}/results/n_loop_err', f'{CAND_GEOC_NAME}/v10_component_correction_provenance.json'], DIAGNOSTIC_ARCHIVE)
DIAGNOSTIC_SHA_PATH = Path(str(DIAGNOSTIC_ARCHIVE) + '.sha256')
DIAGNOSTIC_SHA_PATH.write_text(f'{DIAGNOSTIC_SHA}  {DIAGNOSTIC_ARCHIVE.name}\\n', encoding='utf-8')

if not network_gate['passed']:
    raise RuntimeError('PREREGISTERED STOP: unchanged structural network gate failed: ' + ', '.join(network_failures))
if not recovery_gate['passed']:
    raise RuntimeError('PREREGISTERED STOP: complete 113-pixel recovery/no-new-error gate failed. Partial improvement is evidence only; do not invert or tune.')
print('NETWORK AND COMPLETE LOOP-RECOVERY GATES PASSED — diagnostic inversion may run.')
"""
    ),
    code(
        """# 10 — Diagnostic inversion, uncertainty, and baseline-strict preservation gate
run_script('invert', ['-d', CAND_GEOC_NAME, '-t', CAND_TS_NAME, '--mem_size', '4000'], required=[ts_root / 'cum.h5', ts_root / 'results' / 'vel'])
run_script('vstd', ['-t', CAND_TS_NAME], required=[ts_root / 'results' / 'vstd'])

def result_grid(name):
    path = ts_root / 'results' / name
    values = np.fromfile(path, dtype='<f4')
    if values.size != LENGTH * WIDTH:
        raise RuntimeError(f'Unexpected result size for {name}: {values.size}')
    return values.reshape(LENGTH, WIDTH)

cand_vel = result_grid('vel')
cand_vstd = result_grid('vstd')
cand_n_gap = result_grid('n_gap')
cand_n_loop = result_grid('n_loop_err')
cand_strict = np.isfinite(cand_vel) & np.isfinite(cand_vstd) & (cand_n_gap == 0) & (cand_n_loop == 0)
lost_base_strict = base_strict & ~cand_strict
post_inversion_gate = {
    'baseline_strict_pixels': int(base_strict.sum()),
    'candidate_strict_pixels': int(cand_strict.sum()),
    'baseline_strict_pixels_lost': int(lost_base_strict.sum()),
    'all_baseline_strict_preserved': int(lost_base_strict.sum()) == 0,
}
if not post_inversion_gate['all_baseline_strict_preserved']:
    raise RuntimeError('PREREGISTERED STOP: one or more of the 2,477 baseline strict pixels was lost after inversion.')
print(json.dumps(post_inversion_gate, indent=2))
print('POST-INVERSION STRICT-PRESERVATION GATE PASSED. Outputs remain diagnostic pending external validation.')
"""
    ),
    code(
        """# 11 — Export diagnostic GeoTIFFs and write complete provenance
results_dir = ts_root / 'results'
dem_par = WORK / CAND_GEOC_NAME / 'EQA.dem_par'
exported = {}
for layer in ('vel', 'vstd', 'coh_avg', 'n_unw', 'n_gap', 'n_loop_err'):
    destination = DRIVE_ROOT / f'jakarta_{layer}_{DATE_TAG}_{RUN_TAG}.tif'
    run_script('geotiff', ['-i', results_dir / layer, '-p', dem_par, '-o', destination], required=[destination])
    exported[layer] = destination

layer_statistics, grid_key = {}, None
for layer, path in exported.items():
    with rasterio.open(path) as source:
        data = source.read(1)
        key = (source.width, source.height, str(source.crs), tuple(source.transform))
        if grid_key is None: grid_key = key
        elif key != grid_key: raise RuntimeError(f'Export grid mismatch for {layer}')
        finite = np.isfinite(data); values = data[finite]
        layer_statistics[layer] = {
            'path': str(path), 'sha256': sha256_file(path), 'bytes': path.stat().st_size,
            'shape': [source.height, source.width], 'crs': str(source.crs), 'transform': list(source.transform),
            'finite_pixels': int(finite.sum()), 'finite_fraction': float(finite.mean()),
            'min': float(values.min()) if values.size else None,
            'median': float(np.median(values)) if values.size else None,
            'max': float(values.max()) if values.size else None,
        }

qc_v10 = {
    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'scientific_status': 'diagnostic_v10_component_integer_correction_pending_external_validation_and_missing_north_coverage_resolution',
    'frame': FRAME, 'start': START, 'end': END, 'run_tag': RUN_TAG,
    'source_checkpoint_sha256': CHECKPOINT_SHA256,
    'stable_ledger_sha256': sha256_file(STABLE_LEDGER_PATH),
    'heldout_report_sha256': sha256_file(CV_REPORT_PATH),
    'candidate_checkpoint_sha256': sha256_file(CAND_ARCHIVE),
    'network_gate': network_gate, 'post_inversion_gate': post_inversion_gate,
    'strict_criteria_unchanged': 'finite vel/vstd; n_gap=0; n_loop_err=0',
    'candidate_strict_pixels': int(cand_strict.sum()),
    'north_boundary_pixels': int(north_mask.sum()),
    'north_pixels_without_finite_v9_output_remain_separate': 361,
    'layers': layer_statistics,
    'promotion_prohibited_without': ['independent GNSS_or_levelling_validation', 'resolution of missing North Jakarta coverage', 'explicit exposure validation'],
}
atomic_json(QC_OUT, qc_v10)
manifest = {
    'created_utc': qc_v10['created_utc'], 'frame': FRAME, 'run_tag': RUN_TAG,
    'licsbas_commit': LICSBAS_COMMIT, 'mintpy_reference_commit': MINTPY_COMMIT,
    'frozen_inputs': {
        'checkpoint_sha256': CHECKPOINT_SHA256, 'inventory_sha256': INVENTORY_SHA256,
        'results_sha256': RESULTS_SHA256, 'qc_sha256': QC_SHA256,
        'boundary_sha256': BOUNDARY_SHA256, 'attribution_sha256': ATTRIBUTION_SHA256,
    },
    'fold_ledgers': [str(FOLD_DIR / f'fold_{fold}.json') for fold in range(N_FOLDS)],
    'stable_ledger': str(STABLE_LEDGER_PATH), 'heldout_report': str(CV_REPORT_PATH),
    'candidate_checkpoint': str(CAND_ARCHIVE), 'network_gate': str(NETWORK_GATE_PATH),
    'layers': layer_statistics, 'qc_summary': str(QC_OUT),
}
atomic_json(MANIFEST_OUT, manifest)
print('QC summary:', QC_OUT)
print('Manifest:', MANIFEST_OUT)
print('No hazard or risk map is validated or promoted.')
"""
    ),
    code(
        """# 12 — Archive final diagnostic results and verify all deliverables
FINAL_RESULTS_ARCHIVE = ARCHIVE_DIR / f'{CAND_TS_NAME}_results_{DATE_TAG}.tar.gz'
FINAL_RESULTS_SHA = archive_atomic(WORK, [f'{CAND_TS_NAME}/results', f'{CAND_TS_NAME}/info', f'{CAND_TS_NAME}/network', f'{CAND_GEOC_NAME}/EQA.dem_par', f'{CAND_GEOC_NAME}/v10_component_correction_provenance.json'], FINAL_RESULTS_ARCHIVE)
FINAL_RESULTS_SHA_PATH = Path(str(FINAL_RESULTS_ARCHIVE) + '.sha256')
FINAL_RESULTS_SHA_PATH.write_text(f'{FINAL_RESULTS_SHA}  {FINAL_RESULTS_ARCHIVE.name}\\n', encoding='utf-8')

deliverables = {
    'candidate_checkpoint': {'path': str(CAND_ARCHIVE), 'sha256': sha256_file(CAND_ARCHIVE)},
    'stable_ledger': {'path': str(STABLE_LEDGER_PATH), 'sha256': sha256_file(STABLE_LEDGER_PATH)},
    'heldout_report': {'path': str(CV_REPORT_PATH), 'sha256': sha256_file(CV_REPORT_PATH)},
    'network_gate': {'path': str(NETWORK_GATE_PATH), 'sha256': sha256_file(NETWORK_GATE_PATH)},
    'qc_summary': {'path': str(QC_OUT), 'sha256': sha256_file(QC_OUT)},
    'manifest': {'path': str(MANIFEST_OUT), 'sha256': sha256_file(MANIFEST_OUT)},
    'final_results': {'path': str(FINAL_RESULTS_ARCHIVE), 'sha256': FINAL_RESULTS_SHA},
}
DELIVERABLES_PATH = DRIVE_ROOT / f'jakarta_licsbas_{DATE_TAG}_{RUN_TAG}_deliverables.json'
atomic_json(DELIVERABLES_PATH, deliverables)
print(json.dumps(deliverables, indent=2))
print('DONE: preregistered v10 gates passed and diagnostic deliverables are verified in Drive.')
print('Scientific status remains diagnostic; the 361-pixel North coverage gap and independent validation remain unresolved.')
"""
    ),
]


notebook = {
    "cells": cells,
    "metadata": {
        "colab": {"name": OUTPUT.name, "provenance": []},
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

# Match the archived notebook's registered bytes on every OS.
OUTPUT.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\r\n")
print(OUTPUT)
