"""Build the preregistered descending-track Jakarta diagnostic notebook."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "notebooks" / "LiCSBAS_Jakarta_reunwrap_v9.ipynb"
OUTPUT = ROOT / "notebooks" / "LiCSBAS_Jakarta_descending_diagnostic_v11.ipynb"


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


template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
mount_cell = template["cells"][1]
install_cell = template["cells"][2]
install_text = "".join(install_cell["source"])
dependency_anchor = "'affine',"
if dependency_anchor not in install_text:
    raise RuntimeError("The v9 install template no longer contains the dependency anchor")
install_text = install_text.replace(
    dependency_anchor, "'affine', 'shapely', 'pyproj',", 1
)

cells = [
    markdown(
        """# LiCSBAS Jakarta v11 - preregistered descending-track diagnostic

This notebook tests a genuinely different Sentinel-1 viewing geometry: descending LiCSAR frame `047D_09652_111009` over the fixed Jakarta ROI for 2020-2023. It regenerates every interferogram consistently from the unfiltered wrapped phase and applies the same factor-5, Goldstein, single-cascade, 0.3 consistency, `--multi_prime`, and 1.5-radian controls used by v9.

The experiment has two prospective gates. First, the retained global network must meet the unchanged connected-cycle-redundancy requirements. Second, North Jakarta must have useful local observations rather than merely a globally connected network. The North denominator uses projected-area intersections in EPSG:32748 with the official Jakarta Utara boundary and its six districts. A pixel qualifies only when its finite local network retains at least 90% of acquisitions, spans at least 95% of 2020-2023, has at least two edges per image, has no bridges or triangle-less retained edges, and has `n_loop_err=0`. Continuation requires at least 50% qualifying North area, at least 25% in every district, and at least 75% of qualifying area in one eight-connected patch.

These are project-specific continuation thresholds, not universal literature constants. This notebook contains no inversion. It always archives diagnostics, and a pass means only: stop and return to Codex for the next checkpoint. It does not validate or promote a deformation, hazard, or risk map.
"""
    ),
    mount_cell,
    code(install_text),
    code(
        """# 3 - Frozen configuration and helpers
import datetime, hashlib, json, math, os, re, shutil, subprocess, sys, tarfile, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath

import numpy as np
import rasterio
import requests
from affine import Affine
from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform as shapely_transform, unary_union

FRAME = '047D_09652_111009'
TRACK = '47'
START, END = '20200101', '20231231'
DATE_TAG = f'{START}_{END}'
EXPECTED_COMPLETE_PAIRS = 349
EXPECTED_ACQUISITIONS = 76
NLOOK = 5
ROI_BOUNDS = (106.45, -6.54, 107.22, -6.01)
ROI_G_OPTION = f'{ROI_BOUNDS[0]}/{ROI_BOUNDS[2]}/{ROI_BOUNDS[1]}/{ROI_BOUNDS[3]}'
WRAPPED_PRODUCT = 'diff_unfiltered_pha'
UNWRAP_FILTER = 'gold'
UNWRAP_CONSISTENCY_THRESHOLD = 0.3
USE_GACOS = False
LOOP_MODE = 'multi_prime'
LOOP_THRESHOLD_RAD = 1.5

MIN_LCC_IMAGE_FRACTION = 0.90
MIN_LCC_TEMPORAL_SPAN_FRACTION = 0.95
MIN_LCC_EDGE_TO_IMAGE_RATIO = 2.0
MAX_LCC_BRIDGE_INTERFEROGRAMS = 0
MAX_LCC_INTERFEROGRAMS_WITHOUT_TRIANGLE = 0
HISTORICAL_MAX_REJECTION_FRACTION = 0.25

MIN_NORTH_AREA_FRACTION = 0.50
MIN_EACH_NORTH_DISTRICT_AREA_FRACTION = 0.25
MIN_NORTH_LARGEST_PATCH_FRACTION = 0.75
MIN_LOCAL_IMAGE_FRACTION = 0.90
MIN_LOCAL_TEMPORAL_SPAN_FRACTION = 0.95
MIN_LOCAL_EDGE_TO_IMAGE_RATIO = 2.0
MAX_LOCAL_BRIDGES = 0
MAX_LOCAL_EDGES_WITHOUT_TRIANGLE = 0
MIN_NORTH_GRID_COVERAGE_FRACTION = 0.999999
GRID_TOLERANCE_PIXELS = 0.01

BOUNDARY_SHA256 = '7bb4dd0589cec8bd64e8930c94b1835116701b6148f7b7de183e61196593c540'
BOUNDARY_URL = ('https://gis-dpmptsp.jakarta.go.id/arcgis/rest/services/Hosted/'
                'Batas_Administrasi_Kelurahan_DKI_Jakarta/FeatureServer/85/query'
                '?where=1%3D1&outFields=wadmkd%2Cwadmkc%2Cwadmkk&returnGeometry=true&outSR=4326&f=geojson')

WORK = Path('/content/insar_desc47_v11')
DRIVE_OUT = Path('/content/drive/MyDrive/InSAR_Risk_Zoning_Project')
ARCHIVE = DRIVE_OUT / 'LiCSBAS_archive_2020_2023'
GEOC_NAME = 'GEOC'
GEOCML_NAME = 'GEOCml5clip'  # Native hard-coded LiCSBAS02to05_unwrap.py output name.
TS_NAME = 'TS_GEOCml5clip_desc47_reunw_mp'
RUN_TAG = 'desc47_reunw_unfiltered_roi_ml5_mp'
BIN = LICSBAS_REPO / 'bin'
LIB = LICSBAS_REPO / 'LiCSBAS_lib'
CEDA_DATA = f'https://dap.ceda.ac.uk/neodc/comet/data/licsar_products/{TRACK}/{FRAME}'

SOURCE_INVENTORY = ARCHIVE / f'CEDA_{FRAME}_{DATE_TAG}_{WRAPPED_PRODUCT}_inventory.json'
SOURCE_ARCHIVE = ARCHIVE / f'GEOC_{FRAME}_{RUN_TAG}_{DATE_TAG}_source_checkpoint.tar.gz'
SOURCE_ARCHIVE_SHA = ARCHIVE / f'GEOC_{FRAME}_{RUN_TAG}_{DATE_TAG}_source_checkpoint.sha256'
GRID_PREFLIGHT = ARCHIVE / f'GEOC_{FRAME}_{RUN_TAG}_{DATE_TAG}_grid_preflight.json'
GEOCML_ARCHIVE = ARCHIVE / f'{GEOCML_NAME}_{RUN_TAG}_{DATE_TAG}_checkpoint.tar.gz'
GEOCML_ARCHIVE_SHA = ARCHIVE / f'{GEOCML_NAME}_{RUN_TAG}_{DATE_TAG}_checkpoint.sha256'
GEOCML_INVENTORY = ARCHIVE / f'{GEOCML_NAME}_{RUN_TAG}_{DATE_TAG}_inventory.json'
NETWORK_GATE_PATH = DRIVE_OUT / f'jakarta_licsbas_{DATE_TAG}_{RUN_TAG}_network_and_north_gate.json'
DIAGNOSTIC_ARCHIVE = ARCHIVE / f'{TS_NAME}_step12_diagnostics_{DATE_TAG}.tar.gz'
DIAGNOSTIC_ARCHIVE_SHA = ARCHIVE / f'{TS_NAME}_step12_diagnostics_{DATE_TAG}.sha256'
BOUNDARY_LOCAL = WORK / 'dki_kelurahan_official.geojson'
BOUNDARY_CACHE = ARCHIVE / f'dki_kelurahan_official_{BOUNDARY_SHA256[:12]}.geojson'

WORK.mkdir(parents=True, exist_ok=True)
ARCHIVE.mkdir(parents=True, exist_ok=True)
run_env = os.environ.copy()
run_env['PYTHONPATH'] = os.pathsep.join([str(LIB), run_env.get('PYTHONPATH', '')]).rstrip(os.pathsep)

def resolve_script(role, preferred, fragments):
    exact = BIN / preferred
    if exact.exists():
        return exact
    candidates = sorted(p for p in BIN.glob('LiCSBAS*.py') if all(x.lower() in p.name.lower() for x in fragments))
    if len(candidates) != 1:
        raise RuntimeError(f'Cannot resolve {role}: {candidates}')
    return candidates[0]

SCRIPTS = {
    'download': resolve_script('download', 'LiCSBAS01_get_geotiff.py', ('01', 'get_geo')),
    'reunwrap': resolve_script('reunwrap', 'LiCSBAS02to05_unwrap.py', ('02to05', 'unwrap')),
    'check': resolve_script('check', 'LiCSBAS11_check_unw.py', ('11', 'check_unw')),
    'loop': resolve_script('loop', 'LiCSBAS12_loop_closure.py', ('12', 'loop')),
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

PAIR_RE = re.compile(r'^\\d{8}_\\d{8}$')

def sha256_file(path, chunk_size=8 * 1024 * 1024):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()

def pair_dirs(root):
    root = Path(root)
    return sorted(p for p in root.iterdir() if p.is_dir() and PAIR_RE.fullmatch(p.name)) if root.exists() else []

def geotiff_path(folder, kind):
    matches = sorted(folder.glob(f'*.geo.{kind}.tif'))
    return matches[0] if len(matches) == 1 else None

def source_inventory_on_disk(root):
    pairs = pair_dirs(root)
    missing_cc = [p.name for p in pairs if geotiff_path(p, 'cc') is None]
    missing_phase = [p.name for p in pairs if geotiff_path(p, WRAPPED_PRODUCT) is None]
    return {'pairs': [p.name for p in pairs], 'pair_folders': len(pairs),
            'missing_cc': missing_cc, 'missing_phase': missing_phase}

def regenerated_inventory(root):
    pairs = pair_dirs(root)
    missing = [p.name for p in pairs if not all((p / f'{p.name}.{suffix}').exists() for suffix in ('unw', 'cc', 'conncomp'))]
    return {'pairs': [p.name for p in pairs], 'pair_folders': len(pairs),
            'complete_pairs': len(pairs) - len(missing), 'incomplete_pairs': missing}

def atomic_archive(source_root, items, destination):
    partial = destination.with_suffix(destination.suffix + '.partial')
    if partial.exists():
        partial.unlink()
    subprocess.run(['tar', '-czf', str(partial), '-C', str(source_root), *items], check=True)
    subprocess.run(['tar', '-tzf', str(partial)], check=True, stdout=subprocess.DEVNULL)
    if partial.stat().st_size == 0:
        raise RuntimeError(f'Empty archive: {partial}')
    os.replace(partial, destination)
    return sha256_file(destination)

print(json.dumps({k: str(v) for k, v in SCRIPTS.items()}, indent=2))
"""
    ),
    code(
        """# 4 - Validate the fixed method; there is deliberately no inversion command
for role, script in SCRIPTS.items():
    help_run = subprocess.run([sys.executable, str(script), '-h'], cwd=WORK, env=run_env,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if help_run.returncode not in (0, 1):
        raise RuntimeError(f'{role} help check failed ({help_run.returncode})')
    print(f'--- {role}: {script.name} ---')
    print('\\n'.join(help_run.stdout.splitlines()[:14]))
unwrap_help = subprocess.run([sys.executable, str(SCRIPTS['reunwrap']), '-h'], cwd=WORK, env=run_env,
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout
for required in ('--filter', '--cascade', '--thres', '--n_para'):
    if required not in unwrap_help:
        raise RuntimeError(f'Official re-unwrapper does not advertise {required}.')
if USE_GACOS:
    raise RuntimeError('Partial GACOS is prohibited in this experiment.')
print('Frozen method verified: descending frame 47, all-pair unfiltered phase, ROI factor 5, 0.3 consistency, 1.5-rad multi-prime loops.')
"""
    ),
    markdown("""## Source census and restart-safe preparation

The catalogue and file sizes are measured before downloading. Exactly 349 pairs and 76 dates are required. A verified source checkpoint is restored when available; incomplete downloads otherwise resume safely.
"""),
    code(
        """# 5 - Freeze the CEDA catalogue, restore or download CC metadata, and verify it
session = requests.Session()
session.headers.update({'User-Agent': 'Jakarta-InSAR-v11-desc47-preflight'})

# Acquire the checksum-frozen boundary before any expensive processing.  A
# verified Drive copy makes later diagnostic archiving independent of a
# transient ArcGIS endpoint failure.
if BOUNDARY_CACHE.exists():
    boundary_bytes = BOUNDARY_CACHE.read_bytes()
    if hashlib.sha256(boundary_bytes).hexdigest() != BOUNDARY_SHA256:
        raise RuntimeError('Cached official DKI boundary checksum mismatch; stop and inspect the cache.')
else:
    boundary_response = session.get(BOUNDARY_URL, timeout=120)
    boundary_response.raise_for_status()
    boundary_bytes = boundary_response.content
    if hashlib.sha256(boundary_bytes).hexdigest() != BOUNDARY_SHA256:
        raise RuntimeError('Official DKI boundary checksum changed; review it before continuing.')
    boundary_partial = BOUNDARY_CACHE.with_suffix(BOUNDARY_CACHE.suffix + '.partial')
    boundary_partial.write_bytes(boundary_bytes)
    os.replace(boundary_partial, BOUNDARY_CACHE)
BOUNDARY_LOCAL.write_bytes(boundary_bytes)
print(f'Verified official DKI boundary preflight: {BOUNDARY_CACHE}')

index_response = session.get(CEDA_DATA + '/', timeout=90)
index_response.raise_for_status()
catalogue_pairs = sorted({
    pair for pair in re.findall(r'(?<!\\d)(\\d{8}_\\d{8})(?!\\d)', index_response.text)
    if START <= pair[:8] <= END and START <= pair[-8:] <= END
})
catalogue_images = sorted({d for pair in catalogue_pairs for d in pair.split('_')})
if len(catalogue_pairs) != EXPECTED_COMPLETE_PAIRS or len(catalogue_images) != EXPECTED_ACQUISITIONS:
    raise RuntimeError(f'Catalogue changed: {len(catalogue_pairs)} pairs/{len(catalogue_images)} dates; expected {EXPECTED_COMPLETE_PAIRS}/{EXPECTED_ACQUISITIONS}.')

def probe_product(item):
    pair, kind = item
    name = f'{pair}.geo.{kind}.tif'
    url = f'{CEDA_DATA}/{pair}/{name}'
    try:
        response = session.head(url, allow_redirects=True, timeout=60)
        size = int(response.headers.get('Content-Length') or 0)
        if response.status_code == 200 and size > 0:
            return pair, kind, url, size, response.headers.get('Last-Modified')
        with session.get(url, headers={'Range': 'bytes=0-0'}, stream=True, timeout=(45, 90)) as fallback:
            fallback.raise_for_status()
            content_range = fallback.headers.get('Content-Range', '')
            match = re.search(r'/(\\d+)$', content_range)
            size = int(match.group(1)) if match else int(fallback.headers.get('Content-Length') or 0)
            return pair, kind, url, size, fallback.headers.get('Last-Modified')
    except Exception as exc:
        return pair, kind, url, 0, f'{type(exc).__name__}: {exc}'

requests_to_probe = [(pair, kind) for pair in catalogue_pairs for kind in ('cc', WRAPPED_PRODUCT)]
probe_rows = []
with ThreadPoolExecutor(max_workers=16) as pool:
    futures = [pool.submit(probe_product, item) for item in requests_to_probe]
    for future in as_completed(futures):
        probe_rows.append(future.result())
missing = [row for row in probe_rows if row[3] <= 0]
if missing:
    raise RuntimeError(f'CEDA product census failed for {len(missing)} files: {missing[:10]}')

source_inventory = {
    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'frame': FRAME, 'track': TRACK, 'start': START, 'end': END,
    'pairs': catalogue_pairs, 'acquisitions': catalogue_images,
    'pair_count': len(catalogue_pairs), 'acquisition_count': len(catalogue_images),
    'wrapped_product': WRAPPED_PRODUCT,
    'files': [dict(pair=p, kind=k, url=u, bytes=s, last_modified=m) for p, k, u, s, m in sorted(probe_rows)],
}
SOURCE_INVENTORY.write_text(json.dumps(source_inventory, indent=2), encoding='utf-8')
all_ifgs_expected = catalogue_pairs
all_images_expected = catalogue_images
expected_pair_set = set(catalogue_pairs)
cc_sizes = {row['pair']: row['bytes'] for row in source_inventory['files'] if row['kind'] == 'cc'}
phase_inventory = {
    'gacos_epochs_available': 0,
    'phase_files': [row for row in source_inventory['files'] if row['kind'] == WRAPPED_PRODUCT],
}

geoc_root = WORK / GEOC_NAME
RESTORED_SOURCE = False
if not geoc_root.exists() and SOURCE_ARCHIVE.exists() and SOURCE_ARCHIVE_SHA.exists():
    expected_sha = SOURCE_ARCHIVE_SHA.read_text(encoding='utf-8').strip().split()[0]
    if sha256_file(SOURCE_ARCHIVE) != expected_sha:
        raise RuntimeError('Descending source checkpoint checksum mismatch.')
    subprocess.run(['tar', '-xzf', str(SOURCE_ARCHIVE), '-C', str(WORK)], check=True)
    RESTORED_SOURCE = True
    embedded_inventory_path = geoc_root / 'v11_source_inventory.json'
    embedded_grid_path = geoc_root / 'v11_grid_preflight.json'
    if not embedded_inventory_path.exists() or not embedded_grid_path.exists():
        raise RuntimeError('Restored source checkpoint lacks embedded v11 provenance.')
    embedded_inventory = json.loads(embedded_inventory_path.read_text(encoding='utf-8'))
    if (embedded_inventory.get('frame') != FRAME
            or embedded_inventory.get('pairs') != catalogue_pairs
            or embedded_inventory.get('wrapped_product') != WRAPPED_PRODUCT):
        raise RuntimeError('Restored source checkpoint provenance does not match the frozen catalogue.')
    archived_records = sorted(
        (row['pair'], row['kind'], int(row['bytes']), row.get('last_modified'))
        for row in embedded_inventory.get('files', [])
    )
    current_records = sorted(
        (row['pair'], row['kind'], int(row['bytes']), row.get('last_modified'))
        for row in source_inventory['files']
    )
    if archived_records != current_records:
        raise RuntimeError('Restored source checkpoint file census differs from the current CEDA census; stop and review upstream replacement.')
    print('Restored verified descending source checkpoint.')

disk_inventory = source_inventory_on_disk(geoc_root)
if set(disk_inventory['pairs']) != expected_pair_set or disk_inventory['missing_cc']:
    run_script('download', ['-f', FRAME, '-s', START, '-e', END, '--n_para', '4'], required=[geoc_root])
disk_inventory = source_inventory_on_disk(geoc_root)
if (disk_inventory['pair_folders'] != EXPECTED_COMPLETE_PAIRS
        or set(disk_inventory['pairs']) != expected_pair_set
        or disk_inventory['missing_cc']):
    raise RuntimeError(f'GEOC download is incomplete: {disk_inventory}')
bad_cc_sizes = []
for pair in catalogue_pairs:
    cc_path = geotiff_path(geoc_root / pair, 'cc')
    if cc_path is None or cc_path.stat().st_size != cc_sizes[pair]:
        bad_cc_sizes.append(pair)
if bad_cc_sizes:
    raise RuntimeError(f'Local CC files do not match the frozen CEDA sizes: {bad_cc_sizes[:10]}')
print(f'CEDA census verified: {len(catalogue_pairs)} pairs, {len(catalogue_images)} acquisitions; all CC products present.')
"""
    ),
    code(
        """# 6 - Download identical unfiltered phases, audit every grid, and checkpoint the source
phase_sizes = {row['pair']: row['bytes'] for row in source_inventory['files'] if row['kind'] == WRAPPED_PRODUCT}

def download_phase(pair):
    destination = geoc_root / pair / f'{pair}.geo.{WRAPPED_PRODUCT}.tif'
    expected_size = phase_sizes[pair]
    if destination.exists() and destination.stat().st_size == expected_size:
        return pair, 'existing'
    partial = destination.with_suffix(destination.suffix + '.partial')
    url = f'{CEDA_DATA}/{pair}/{destination.name}'
    last_error = None
    for attempt in range(1, 7):
        if partial.exists():
            partial.unlink()
        try:
            with session.get(url, stream=True, timeout=(45, 300)) as response:
                response.raise_for_status()
                with open(partial, 'wb') as stream:
                    for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                        if chunk:
                            stream.write(chunk)
            if partial.stat().st_size != expected_size:
                raise RuntimeError(f'Incomplete phase: {partial.stat().st_size} != {expected_size}')
            os.replace(partial, destination)
            return pair, 'downloaded'
        except (requests.RequestException, OSError, RuntimeError) as exc:
            last_error = exc
            if partial.exists():
                partial.unlink()
            if attempt < 6:
                time.sleep(min(60, 5 * (2 ** (attempt - 1))))
    raise RuntimeError(f'Wrapped-phase download failed for {pair}') from last_error

phase_results = []
with ThreadPoolExecutor(max_workers=8) as pool:
    futures = [pool.submit(download_phase, pair) for pair in all_ifgs_expected]
    for index, future in enumerate(as_completed(futures), 1):
        phase_results.append(future.result())
        if index % 25 == 0 or index == EXPECTED_COMPLETE_PAIRS:
            print(f'Wrapped phase ready: {index}/{EXPECTED_COMPLETE_PAIRS}', flush=True)
if RESTORED_SOURCE and any(status != 'existing' for _, status in phase_results):
    raise RuntimeError('The restored source checkpoint no longer matches the frozen CEDA file sizes; stop and review the changed upstream products.')
post_phase_inventory = source_inventory_on_disk(geoc_root)
if (post_phase_inventory['pair_folders'] != EXPECTED_COMPLETE_PAIRS
        or set(post_phase_inventory['pairs']) != expected_pair_set
        or post_phase_inventory['missing_cc']
        or post_phase_inventory['missing_phase']):
    raise RuntimeError(f'Prepared source has the wrong exact pair/product set: {post_phase_inventory}')

def corner_error_pixels(reference, candidate):
    if reference.crs != candidate.crs or reference.shape != candidate.shape:
        return math.inf
    if abs(candidate.transform.b) > 1e-9 or abs(candidate.transform.d) > 1e-9:
        return math.inf
    errors = []
    for col, row in ((0, 0), (reference.width, 0), (0, reference.height), (reference.width, reference.height)):
        rx, ry = reference.transform * (col, row)
        cx, cy = candidate.transform * (col, row)
        errors.extend((abs(cx - rx) / abs(reference.transform.a), abs(cy - ry) / abs(reference.transform.e)))
    return max(errors)

reference_cc_path = geotiff_path(geoc_root / all_ifgs_expected[0], 'cc')
grid_rows = []
with rasterio.open(reference_cc_path) as reference:
    if reference.crs is None or reference.crs.to_epsg() != 4326:
        raise RuntimeError(f'Expected EPSG:4326, found {reference.crs}.')
    for pair in all_ifgs_expected:
        cc_path = geotiff_path(geoc_root / pair, 'cc')
        phase_path = geotiff_path(geoc_root / pair, WRAPPED_PRODUCT)
        if cc_path is None or phase_path is None:
            raise RuntimeError(f'Missing CC or wrapped phase for {pair}.')
        with rasterio.open(cc_path) as cc, rasterio.open(phase_path) as phase:
            cc_reference_error = corner_error_pixels(reference, cc)
            phase_reference_error = corner_error_pixels(reference, phase)
            pair_error = corner_error_pixels(cc, phase)
            maximum = max(cc_reference_error, phase_reference_error, pair_error)
            grid_rows.append({'pair': pair, 'cc_reference_error_pixels': cc_reference_error,
                              'phase_reference_error_pixels': phase_reference_error,
                              'pair_cc_phase_error_pixels': pair_error, 'maximum_error_pixels': maximum})

worst = max(grid_rows, key=lambda row: row['maximum_error_pixels'])
grid_report = {
    'frame': FRAME, 'pair_count': len(grid_rows),
    'maximum_allowed_error_pixels': GRID_TOLERANCE_PIXELS,
    'worst': worst, 'all_pairs': grid_rows,
}
GRID_PREFLIGHT.write_text(json.dumps(grid_report, indent=2), encoding='utf-8')
if not math.isfinite(worst['maximum_error_pixels']) or worst['maximum_error_pixels'] > GRID_TOLERANCE_PIXELS:
    raise RuntimeError(f'PREREGISTERED STOP: source grids differ by {worst["maximum_error_pixels"]:.6g} pixels; see {GRID_PREFLIGHT}.')
(geoc_root / ('v11_source_inventory_current_census.json' if RESTORED_SOURCE else 'v11_source_inventory.json')).write_text(
    json.dumps(source_inventory, indent=2), encoding='utf-8'
)
(geoc_root / 'v11_grid_preflight.json').write_text(json.dumps(grid_report, indent=2), encoding='utf-8')

if not RESTORED_SOURCE:
    source_sha = atomic_archive(WORK, [GEOC_NAME], SOURCE_ARCHIVE)
    SOURCE_ARCHIVE_SHA.write_text(f'{source_sha}  {SOURCE_ARCHIVE.name}\\n', encoding='utf-8')
else:
    source_sha = sha256_file(SOURCE_ARCHIVE)
print(f'VERIFIED source checkpoint: {SOURCE_ARCHIVE} ({SOURCE_ARCHIVE.stat().st_size / 1e9:.2f} GB)')
print('SHA-256:', source_sha)
"""
    ),
    code(
        """# 7 - Regenerate every ROI interferogram consistently and checkpoint it
geocml_root = WORK / GEOCML_NAME
catalogue_pairs_sha256 = hashlib.sha256('\\n'.join(catalogue_pairs).encode('ascii')).hexdigest()
method_identity = {
    'frame': FRAME, 'orbit': 'descending', 'start': START, 'end': END,
    'source_archive_sha256': source_sha, 'catalogue_pairs_sha256': catalogue_pairs_sha256,
    'pair_count': EXPECTED_COMPLETE_PAIRS, 'acquisition_count': EXPECTED_ACQUISITIONS,
    'wrapped_product': WRAPPED_PRODUCT, 'historical_unwrapped_phase_used': False,
    'filter': UNWRAP_FILTER, 'cascade': 'single_10x_layer',
    'consistency_threshold': UNWRAP_CONSISTENCY_THRESHOLD, 'gacos_used': USE_GACOS,
    'roi_bounds_wsen': list(ROI_BOUNDS), 'multilook': NLOOK,
    'loop_mode': LOOP_MODE, 'loop_threshold_rad': LOOP_THRESHOLD_RAD,
    'licsbas_commit': actual_commit, 'licsar_extra_commit': LICSAR_EXTRA_COMMIT,
}
configuration_fingerprint = hashlib.sha256(
    json.dumps(method_identity, sort_keys=True, separators=(',', ':')).encode('utf-8')
).hexdigest()
expected_provenance = {**method_identity, 'configuration_fingerprint': configuration_fingerprint}
pending_provenance = WORK / f'{GEOCML_NAME}_{RUN_TAG}_pending_provenance.json'

def require_matching_provenance(path):
    path = Path(path)
    if not path.exists():
        raise RuntimeError(f'Missing regenerated provenance: {path}')
    observed = json.loads(path.read_text(encoding='utf-8'))
    mismatches = {key: [observed.get(key), value] for key, value in expected_provenance.items()
                  if observed.get(key) != value}
    if mismatches:
        raise RuntimeError(f'Regenerated provenance/configuration mismatch: {mismatches}')
    return observed

GEOCML_RESTORED = False
if not geocml_root.exists() and GEOCML_ARCHIVE.exists() and GEOCML_ARCHIVE_SHA.exists():
    expected_sha = GEOCML_ARCHIVE_SHA.read_text(encoding='utf-8').strip().split()[0]
    if sha256_file(GEOCML_ARCHIVE) != expected_sha:
        raise RuntimeError('Regenerated checkpoint checksum mismatch.')
    subprocess.run(['tar', '-xzf', str(GEOCML_ARCHIVE), '-C', str(WORK)], check=True)
    restored = regenerated_inventory(geocml_root)
    if (restored['pair_folders'] != EXPECTED_COMPLETE_PAIRS
            or restored['complete_pairs'] != EXPECTED_COMPLETE_PAIRS
            or set(restored['pairs']) != expected_pair_set):
        raise RuntimeError(f'Restored regenerated checkpoint has the wrong pair set: {restored}')
    reunwrap_provenance = require_matching_provenance(geocml_root / 'reunwrap_provenance.json')
    GEOCML_RESTORED = True

existing = regenerated_inventory(geocml_root)
needs_reunwrap = (
    not geocml_root.exists()
    or existing['complete_pairs'] != EXPECTED_COMPLETE_PAIRS
    or set(existing['pairs']) != expected_pair_set
)
if needs_reunwrap:
    if existing['pair_folders']:
        require_matching_provenance(pending_provenance)
    else:
        pending_provenance.write_text(json.dumps(expected_provenance, indent=2), encoding='utf-8')
    run_script('reunwrap', ['-i', WORK, '-M', NLOOK, '-g', ROI_G_OPTION,
                            '--filter', UNWRAP_FILTER, '--cascade',
                            '--thres', UNWRAP_CONSISTENCY_THRESHOLD, '--n_para', '2'],
               required=[geocml_root])

regenerated = regenerated_inventory(geocml_root)
if (regenerated['pair_folders'] != EXPECTED_COMPLETE_PAIRS
        or regenerated['complete_pairs'] != EXPECTED_COMPLETE_PAIRS
        or set(regenerated['pairs']) != expected_pair_set):
    raise RuntimeError(f'Regenerated stack has the wrong exact pair set: {regenerated}')

final_provenance_path = geocml_root / 'reunwrap_provenance.json'
if GEOCML_RESTORED:
    reunwrap_provenance = require_matching_provenance(final_provenance_path)
elif needs_reunwrap:
    reunwrap_provenance = {
        **expected_provenance,
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    final_provenance_path.write_text(
        json.dumps(reunwrap_provenance, indent=2), encoding='utf-8'
    )
    if pending_provenance.exists():
        pending_provenance.unlink()
elif final_provenance_path.exists():
    reunwrap_provenance = require_matching_provenance(final_provenance_path)
elif pending_provenance.exists():
    require_matching_provenance(pending_provenance)
    reunwrap_provenance = {
        **expected_provenance,
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'resume_note': 'Unwrapper completed before final provenance was written; pending fingerprint matched exactly.',
    }
    final_provenance_path.write_text(
        json.dumps(reunwrap_provenance, indent=2), encoding='utf-8'
    )
    pending_provenance.unlink()
else:
    raise RuntimeError('A complete runtime stack has neither final nor pending matching provenance.')

GEOCML_INVENTORY.write_text(
    json.dumps({'inventory': regenerated, 'provenance': reunwrap_provenance}, indent=2),
    encoding='utf-8',
)
if not GEOCML_RESTORED:
    checkpoint_sha = atomic_archive(WORK, [GEOCML_NAME], GEOCML_ARCHIVE)
    GEOCML_ARCHIVE_SHA.write_text(f'{checkpoint_sha}  {GEOCML_ARCHIVE.name}\\n', encoding='utf-8')
else:
    checkpoint_sha = sha256_file(GEOCML_ARCHIVE)
print(f'VERIFIED regenerated checkpoint: {GEOCML_ARCHIVE} ({GEOCML_ARCHIVE.stat().st_size / 1e9:.2f} GB)')
print('Configuration fingerprint:', configuration_fingerprint)
print('SHA-256:', checkpoint_sha)
"""
    ),
    code(
        """# 8 - Run steps 11/12, then enforce global and North-Jakarta gates
run_script('check', ['-d', GEOCML_NAME, '-t', TS_NAME], required=[WORK / TS_NAME])
run_script('loop', ['-d', GEOCML_NAME, '-t', TS_NAME, '-l', str(LOOP_THRESHOLD_RAD), '--multi_prime'],
           required=[WORK / TS_NAME / 'info' / '12bad_ifg.txt', WORK / TS_NAME / 'results' / 'n_loop_err'])

def data_lines(path):
    return [line.strip() for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines()
            if line.strip() and not line.lstrip().startswith('#')] if Path(path).exists() else []

def ifg_ids(path):
    result = set()
    for line in data_lines(path):
        match = re.search(r'(?<!\\d)(\\d{8}_\\d{8})(?!\\d)', line)
        if not match:
            raise RuntimeError(f'Cannot parse interferogram from {path}: {line}')
        result.add(match.group(1))
    return result

def graph_summary(nodes, edges):
    nodes = sorted(nodes)
    adjacency = {node: set() for node in nodes}
    edge_names = {}
    for pair in edges:
        a, b = pair.split('_')
        adjacency[a].add(b); adjacency[b].add(a)
        edge_names[frozenset((a, b))] = pair
    components, unseen = [], set(nodes)
    while unseen:
        start = min(unseen); stack = [start]; component = set()
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node); unseen.discard(node); stack.extend(adjacency[node] - component)
        components.append(sorted(component))
    components.sort(key=lambda item: (-len(item), item[0]))
    lcc = components[0] if components else []
    lcc_set = set(lcc)
    lcc_edges = sorted(pair for pair in edges if set(pair.split('_')).issubset(lcc_set))
    disc, low, parent, bridges, clock = {}, {}, {}, [], [0]
    def visit(node):
        disc[node] = low[node] = clock[0]; clock[0] += 1
        for neighbour in sorted(adjacency[node] & lcc_set):
            if neighbour not in disc:
                parent[neighbour] = node; visit(neighbour); low[node] = min(low[node], low[neighbour])
                if low[neighbour] > disc[node]:
                    bridges.append(edge_names[frozenset((node, neighbour))])
            elif parent.get(node) != neighbour:
                low[node] = min(low[node], disc[neighbour])
    if lcc:
        visit(lcc[0])
    without_triangle = []
    for pair in lcc_edges:
        a, b = pair.split('_')
        if not (adjacency[a] & adjacency[b] & lcc_set):
            without_triangle.append(pair)
    return lcc, lcc_edges, sorted(bridges), sorted(without_triangle), components

def all_edge_redundancy(nodes, edges):
    adjacency = {node: set() for node in nodes}
    edge_names = {}
    for pair in edges:
        a, b = pair.split('_')
        adjacency[a].add(b); adjacency[b].add(a)
        edge_names[frozenset((a, b))] = pair
    disc, low, parent, bridges, clock = {}, {}, {}, [], [0]
    def visit(node):
        disc[node] = low[node] = clock[0]; clock[0] += 1
        for neighbour in sorted(adjacency[node]):
            if neighbour not in disc:
                parent[neighbour] = node; visit(neighbour); low[node] = min(low[node], low[neighbour])
                if low[neighbour] > disc[node]:
                    bridges.append(edge_names[frozenset((node, neighbour))])
            elif parent.get(node) != neighbour:
                low[node] = min(low[node], disc[neighbour])
    for node in sorted(nodes):
        if node not in disc:
            visit(node)
    without_triangle = []
    for pair in edges:
        a, b = pair.split('_')
        if not (adjacency[a] & adjacency[b]):
            without_triangle.append(pair)
    return sorted(bridges), sorted(without_triangle)

info_dir = WORK / TS_NAME / 'info'
bad11, bad12 = ifg_ids(info_dir / '11bad_ifg.txt'), ifg_ids(info_dir / '12bad_ifg.txt')
all_ifgs = sorted(p.name for p in pair_dirs(geocml_root))
all_images = sorted({d for pair in all_ifgs for d in pair.split('_')})
if (len(all_ifgs) != EXPECTED_COMPLETE_PAIRS
        or set(all_ifgs) != expected_pair_set
        or len(all_images) != EXPECTED_ACQUISITIONS
        or all_images != catalogue_images):
    raise RuntimeError('Step-12 input identity differs from the frozen 349-pair/76-date catalogue.')
rejected = bad11 | bad12
if rejected - expected_pair_set:
    raise RuntimeError(f'LiCSBAS rejection files contain unknown pairs: {sorted(rejected - expected_pair_set)}')
retained = sorted(set(all_ifgs) - rejected)
lcc, lcc_ifgs, bridges, without_triangle, components = graph_summary(all_images, retained)
requested_days = (datetime.datetime.strptime(END, '%Y%m%d') - datetime.datetime.strptime(START, '%Y%m%d')).days
lcc_days = ((datetime.datetime.strptime(lcc[-1], '%Y%m%d') - datetime.datetime.strptime(lcc[0], '%Y%m%d')).days if len(lcc) > 1 else 0)
global_metrics = {
    'image_fraction': len(lcc) / len(all_images),
    'temporal_span_fraction': lcc_days / requested_days,
    'edge_to_image_ratio': len(lcc_ifgs) / len(lcc),
    'bridges': bridges, 'interferograms_without_triangle': without_triangle,
}
global_failures = []
if global_metrics['image_fraction'] < MIN_LCC_IMAGE_FRACTION: global_failures.append('global image fraction')
if global_metrics['temporal_span_fraction'] < MIN_LCC_TEMPORAL_SPAN_FRACTION: global_failures.append('global temporal span')
if global_metrics['edge_to_image_ratio'] < MIN_LCC_EDGE_TO_IMAGE_RATIO: global_failures.append('global edge/image ratio')
if len(bridges) > MAX_LCC_BRIDGE_INTERFEROGRAMS: global_failures.append('global bridges')
if len(without_triangle) > MAX_LCC_INTERFEROGRAMS_WITHOUT_TRIANGLE: global_failures.append('global triangle coverage')

if not BOUNDARY_LOCAL.exists() or hashlib.sha256(BOUNDARY_LOCAL.read_bytes()).hexdigest() != BOUNDARY_SHA256:
    raise RuntimeError('Checksum-verified boundary preflight is unavailable; rerun cell 5 before diagnostics.')
boundary = json.loads(BOUNDARY_LOCAL.read_bytes())
north_features = [feature for feature in boundary['features'] if 'UTARA' in str(feature['properties'].get('wadmkk', '')).upper()]
district_geometries = defaultdict(list)
for feature in north_features:
    district = str(feature['properties']['wadmkc']).strip()
    district_geometries[district].append(shape(feature['geometry']))
district_geometries = {name: unary_union(parts) for name, parts in district_geometries.items()}
if len(district_geometries) != 6:
    raise RuntimeError(f'Expected six North Jakarta districts, found {sorted(district_geometries)}.')

par = {}
for line in (geocml_root / 'EQA.dem_par').read_text(encoding='utf-8', errors='replace').splitlines():
    fields = line.replace(':', ' ').split()
    if len(fields) >= 2:
        par[fields[0]] = fields[1]
width, length = int(par['width']), int(par['nlines'])
post_lon, post_lat = float(par['post_lon']), float(par['post_lat'])
corner_lon, corner_lat = float(par['corner_lon']), float(par['corner_lat'])
if not all(math.isfinite(value) for value in (post_lon, post_lat, corner_lon, corner_lat)):
    raise RuntimeError('Factor-5 grid contains non-finite georeferencing values.')
if post_lon <= 0 or post_lat >= 0 or width <= 0 or length <= 0:
    raise RuntimeError('Factor-5 grid is not a positive-width north-up longitude/latitude grid.')
grid_transform = Affine(post_lon, 0, corner_lon - post_lon / 2, 0, post_lat, corner_lat - post_lat / 2)
to_utm = Transformer.from_crs(4326, 32748, always_xy=True).transform
district_utm = {name: shapely_transform(to_utm, geom) for name, geom in district_geometries.items()}
grid_left, grid_top = grid_transform * (0, 0)
grid_right, grid_bottom = grid_transform * (width, length)
grid_wgs84 = box(min(grid_left, grid_right), min(grid_bottom, grid_top),
                 max(grid_left, grid_right), max(grid_bottom, grid_top))
grid_utm = shapely_transform(to_utm, grid_wgs84)
district_grid_coverage = {
    name: grid_utm.intersection(geometry).area / geometry.area
    for name, geometry in district_utm.items()
}
grid_coverage_failures = [
    name for name, value in district_grid_coverage.items()
    if value < MIN_NORTH_GRID_COVERAGE_FRACTION
]

cell_district_areas = {}
cell_total_area = {}
for row in range(length):
    for col in range(width):
        left, top = grid_transform * (col, row)
        right, bottom = grid_transform * (col + 1, row + 1)
        cell_utm = shapely_transform(to_utm, box(min(left, right), min(bottom, top), max(left, right), max(bottom, top)))
        areas = {name: cell_utm.intersection(geom).area for name, geom in district_utm.items()}
        areas = {name: area for name, area in areas.items() if area > 0}
        if areas:
            cell_district_areas[(row, col)] = areas
            cell_total_area[(row, col)] = sum(areas.values())
if not cell_total_area:
    raise RuntimeError('North Jakarta has no intersection with the factor-5 grid.')

north_cells = sorted(cell_total_area)
flat_indices = np.array([row * width + col for row, col in north_cells])
valid_edges = np.zeros((len(retained), len(north_cells)), dtype=bool)
for edge_index, pair in enumerate(retained):
    unw = np.fromfile(geocml_root / pair / f'{pair}.unw', dtype='<f4')
    if unw.size != width * length:
        raise RuntimeError(f'Unexpected UNW size for {pair}: {unw.size}.')
    values = unw[flat_indices]
    valid_edges[edge_index] = np.isfinite(values) & (values != 0)
n_loop_err = np.fromfile(WORK / TS_NAME / 'results' / 'n_loop_err', dtype='<f4').reshape(length, width)
n_ifg_noloop_path = WORK / TS_NAME / 'results' / 'n_ifg_noloop'

qualifies = np.zeros((length, width), dtype=bool)
local_summaries = []
for pixel_index, (row, col) in enumerate(north_cells):
    pixel_edges = [pair for pair, valid in zip(retained, valid_edges[:, pixel_index]) if valid]
    local_lcc, local_lcc_edges, local_bridges, local_without_triangle, _ = graph_summary(all_images, pixel_edges)
    all_local_bridges, all_local_without_triangle = all_edge_redundancy(all_images, pixel_edges)
    local_days = ((datetime.datetime.strptime(local_lcc[-1], '%Y%m%d') - datetime.datetime.strptime(local_lcc[0], '%Y%m%d')).days if len(local_lcc) > 1 else 0)
    image_fraction = len(local_lcc) / len(all_images)
    span_fraction = local_days / requested_days
    edge_ratio = len(local_lcc_edges) / len(local_lcc) if local_lcc else 0.0
    passed = (
        image_fraction >= MIN_LOCAL_IMAGE_FRACTION
        and span_fraction >= MIN_LOCAL_TEMPORAL_SPAN_FRACTION
        and edge_ratio >= MIN_LOCAL_EDGE_TO_IMAGE_RATIO
        and len(all_local_bridges) <= MAX_LOCAL_BRIDGES
        and len(all_local_without_triangle) <= MAX_LOCAL_EDGES_WITHOUT_TRIANGLE
        and n_loop_err[row, col] == 0
    )
    qualifies[row, col] = passed
    local_summaries.append({'row': row, 'col': col, 'image_fraction': image_fraction,
                            'temporal_span_fraction': span_fraction, 'edge_to_image_ratio': edge_ratio,
                            'lcc_bridge_count': len(local_bridges),
                            'lcc_edges_without_triangle_count': len(local_without_triangle),
                            'all_finite_retained_bridge_count': len(all_local_bridges),
                            'all_finite_retained_edges_without_triangle_count': len(all_local_without_triangle),
                            'n_loop_err': float(n_loop_err[row, col]), 'qualifies': bool(passed)})

total_area = sum(cell_total_area.values())
passing_area = sum(area for cell, area in cell_total_area.items() if qualifies[cell])
north_fraction = passing_area / total_area
district_total = {name: sum(areas.get(name, 0) for areas in cell_district_areas.values()) for name in district_geometries}
district_passing = {name: sum(areas.get(name, 0) for cell, areas in cell_district_areas.items() if qualifies[cell]) for name in district_geometries}
district_fractions = {name: district_passing[name] / district_total[name] for name in district_geometries}

unseen = {cell for cell in north_cells if qualifies[cell]}
patch_areas = []
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
    patch_areas.append(sum(cell_total_area[cell] for cell in component))
largest_patch_fraction = max(patch_areas, default=0.0) / passing_area if passing_area else 0.0

north_failures = []
if grid_coverage_failures: north_failures.append('North district grid coverage')
if north_fraction < MIN_NORTH_AREA_FRACTION: north_failures.append('North total area')
if any(value < MIN_EACH_NORTH_DISTRICT_AREA_FRACTION for value in district_fractions.values()): north_failures.append('North district minimum')
if largest_patch_fraction < MIN_NORTH_LARGEST_PATCH_FRACTION: north_failures.append('North connected patch')
sensitivity = []
for total_threshold in (0.40, 0.50, 0.60):
    for district_threshold in (0.15, 0.25, 0.35):
        sensitivity.append({'total_threshold': total_threshold, 'district_threshold': district_threshold,
                            'would_pass': north_fraction >= total_threshold
                            and all(value >= district_threshold for value in district_fractions.values())
                            and largest_patch_fraction >= MIN_NORTH_LARGEST_PATCH_FRACTION})

gate_failures = global_failures + north_failures
network_gate = {
    'gate_basis': 'preregistered_descending_global_plus_north_local_network',
    'frame': FRAME, 'orbit': 'descending', 'loop_mode': LOOP_MODE, 'loop_threshold_rad': LOOP_THRESHOLD_RAD,
    'total_interferograms': len(all_ifgs), 'total_images': len(all_images),
    'step11_bad_interferograms': len(bad11), 'step12_bad_interferograms': len(bad12),
    'unique_rejected_interferograms': len(rejected),
    'rejection_fraction': len(rejected) / len(all_ifgs),
    'historical_25pct_ceiling_exceeded': len(rejected) / len(all_ifgs) > HISTORICAL_MAX_REJECTION_FRACTION,
    'rejection_fraction_role': 'reported_comparison_not_universal_hard_gate',
    'audit_files': {
        'n_loop_err_present': True,
        'n_ifg_noloop_present': n_ifg_noloop_path.exists(),
        'n_ifg_noloop_role': 'optional LiCSBAS output; custom graph audit independently checks every retained edge for triangle coverage',
    },
    'global_network': {**global_metrics, 'lcc_images': lcc, 'lcc_interferograms': len(lcc_ifgs),
                       'component_count': len(components), 'failures': global_failures},
    'north_jakarta_gate': {
        'denominator': 'projected-area EPSG:32748 intersection with official Jakarta Utara and six wadmkc districts',
        'factor5_grid_bounds_wsen': [grid_left, grid_bottom, grid_right, grid_top],
        'district_grid_coverage_fractions': district_grid_coverage,
        'candidate_cell_count': len(north_cells), 'qualifying_cell_count': int(qualifies.sum()),
        'total_area_m2': total_area, 'qualifying_area_m2': passing_area,
        'qualifying_area_fraction': north_fraction, 'district_area_fractions': district_fractions,
        'largest_8_connected_patch_fraction_of_passing_area': largest_patch_fraction,
        'thresholds': {'min_total_area_fraction': MIN_NORTH_AREA_FRACTION,
                       'min_each_district_area_fraction': MIN_EACH_NORTH_DISTRICT_AREA_FRACTION,
                       'min_largest_patch_fraction': MIN_NORTH_LARGEST_PATCH_FRACTION,
                       'local_image_fraction': MIN_LOCAL_IMAGE_FRACTION,
                       'local_temporal_span_fraction': MIN_LOCAL_TEMPORAL_SPAN_FRACTION,
                       'local_edge_to_image_ratio': MIN_LOCAL_EDGE_TO_IMAGE_RATIO,
                       'max_local_bridges': MAX_LOCAL_BRIDGES,
                       'max_local_edges_without_triangle': MAX_LOCAL_EDGES_WITHOUT_TRIANGLE,
                       'min_north_grid_coverage_fraction': MIN_NORTH_GRID_COVERAGE_FRACTION,
                       'required_n_loop_err': 0},
        'sensitivity_non_decisional': sensitivity, 'failures': north_failures,
    },
    'passed': not gate_failures, 'gate_failures': gate_failures,
    'pass_action': 'Stop and return to Codex; a separate preregistered inversion notebook is required.',
    'promotion_prohibited_without': ['post_inversion_n_gap=0_and_n_loop_err=0', 'uncertainty_sensitivity',
                                     'independent_GNSS_or_levelling_validation', 'explicit_exposure_validation'],
}
NETWORK_GATE_PATH.write_text(json.dumps(network_gate, indent=2), encoding='utf-8')
(info_dir / f'{RUN_TAG}_network_and_north_gate.json').write_text(json.dumps(network_gate, indent=2), encoding='utf-8')
(info_dir / f'{RUN_TAG}_north_pixel_ledger.json').write_text(json.dumps(local_summaries, indent=2), encoding='utf-8')
print(json.dumps(network_gate, indent=2))

diagnostic_items = [f'{TS_NAME}/info', f'{TS_NAME}/network', f'{TS_NAME}/12loop',
                    f'{TS_NAME}/results/n_unw', f'{TS_NAME}/results/n_loop_err',
                    f'{GEOCML_NAME}/reunwrap_provenance.json', BOUNDARY_LOCAL.name]
if n_ifg_noloop_path.exists():
    diagnostic_items.append(f'{TS_NAME}/results/n_ifg_noloop')
else:
    print('INFO: optional LiCSBAS results/n_ifg_noloop was not produced; custom all-edge triangle audit is archived instead.')
diagnostic_sha = atomic_archive(WORK, diagnostic_items, DIAGNOSTIC_ARCHIVE)
DIAGNOSTIC_ARCHIVE_SHA.write_text(f'{diagnostic_sha}  {DIAGNOSTIC_ARCHIVE.name}\\n', encoding='utf-8')
print(f'VERIFIED diagnostic archive: {DIAGNOSTIC_ARCHIVE} ({DIAGNOSTIC_ARCHIVE.stat().st_size / 1e6:.1f} MB)')
print('SHA-256:', diagnostic_sha)
if gate_failures:
    raise RuntimeError('PREREGISTERED STOP: ' + '; '.join(gate_failures) + '. Diagnostics are archived; do not invert.')
print('DESCENDING GLOBAL + NORTH GATES PASSED. STOP HERE and return to Codex; this notebook has no inversion.')
"""
    ),
]

notebook = {
    "cells": cells,
    "metadata": template["metadata"],
    "nbformat": 4,
    "nbformat_minor": 5,
}
# Match the archived notebook's registered bytes on every OS.
OUTPUT.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\r\n")
print(OUTPUT)
