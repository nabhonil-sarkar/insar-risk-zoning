"""Build the preregistered North-Jakarta NISAR GUNW feasibility notebook."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "notebooks" / "NISAR_Jakarta_north_feasibility_v12.ipynb"


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
        """# NISAR Jakarta v12 — preregistered North-Jakarta L-band feasibility

This notebook tests whether four currently available **provisional** NISAR L2 GUNW products provide repeatable, spatially usable 80 m L-band interferometric coverage over mainland Jakarta Utara. It uses two sequential 12-day interferograms from ascending track 10/frame 174 and two from descending track 18/frame 92.

This is a data-usability experiment only. It cannot estimate velocity, perform loop closure, validate the 2020–2023 Sentinel-1 result, or prove that radar wavelength caused any difference. The coherence threshold is frozen at 0.30. Sensitivity at 0.20 and 0.40 is descriptive and cannot change the decision.

Run cells in order. Cell 4 checks the official ASF inventory and QA summaries before any large download. Stop after cell 4 and review the census if any product or QA field is unexpected. Cell 5 downloads approximately 9.48 GB to Drive using atomic partial files, exact size checks and persistent SHA-256 sidecars. Cells 6–8 extract only the named HDF5 variables, calculate exact projected-area North-Jakarta metrics, render diagnostics and archive the result.
"""
    ),
    code(
        """# 1 — Mount Drive
from google.colab import drive
drive.mount('/content/drive')
"""
    ),
    code(
        """# 2 — Install the small analysis environment
import subprocess, sys
subprocess.run([
    sys.executable, '-m', 'pip', 'install', '-q',
    'earthaccess>=0.14,<1', 'h5py>=3.11,<4', 'numpy>=1.26,<3',
    'requests>=2.31,<3', 'shapely>=2.0,<3', 'pyproj>=3.6,<4',
    'matplotlib>=3.8,<4'
], check=True)
"""
    ),
    code(
        """# 3 — Frozen products, gates and reusable helpers
import csv, datetime, hashlib, io, json, math, os, re, shutil, tarfile, time
from collections import Counter
from pathlib import Path

import earthaccess
import h5py
import matplotlib.pyplot as plt
import numpy as np
import requests
from pyproj import CRS, Transformer
from shapely.geometry import box, shape
from shapely.ops import transform as shapely_transform, unary_union

PRIMARY_COHERENCE_THRESHOLD = 0.30
SENSITIVITY_THRESHOLDS = (0.20, 0.40)
MIN_FOOTPRINT_COVERAGE = 0.95
MIN_EACH_IFG_USABLE_FRACTION = 0.50
MIN_TWO_IFG_COMMON_USABLE_FRACTION = 0.40
MIN_LARGEST_COMPONENT_SHARE = 0.80
EXPECTED_TOTAL_BYTES = 9_483_321_344

PRODUCTS = [
    {
        'id': 'NISAR_L2_PR_GUNW_024_010_A_174_025_4000_SH_20260626T223921_20260626T223956_20260708T223920_20260708T223955_P05023_N_F_J_001',
        'bytes': 2_315_255_808, 'track': 10, 'frame': 174, 'direction': 'ASCENDING',
        'pair': '20260626_20260708',
    },
    {
        'id': 'NISAR_L2_PR_GUNW_025_010_A_174_026_4000_SH_20260708T223920_20260708T223955_20260720T223920_20260720T223954_P05023_N_F_J_001',
        'bytes': 2_290_089_984, 'track': 10, 'frame': 174, 'direction': 'ASCENDING',
        'pair': '20260708_20260720',
    },
    {
        'id': 'NISAR_L2_PR_GUNW_024_018_D_092_025_4000_SH_20260627T111145_20260627T111223_20260709T111145_20260709T111222_P05023_N_F_J_001',
        'bytes': 2_441_084_928, 'track': 18, 'frame': 92, 'direction': 'DESCENDING',
        'pair': '20260627_20260709',
    },
    {
        'id': 'NISAR_L2_PR_GUNW_025_018_D_092_026_4000_SH_20260709T111145_20260709T111222_20260721T111144_20260721T111222_P05023_N_F_J_001',
        'bytes': 2_436_890_624, 'track': 18, 'frame': 92, 'direction': 'DESCENDING',
        'pair': '20260709_20260721',
    },
]
if sum(item['bytes'] for item in PRODUCTS) != EXPECTED_TOTAL_BYTES:
    raise RuntimeError('Frozen NISAR byte census is internally inconsistent.')

ASF_SEARCH_API = 'https://api.daac.asf.alaska.edu/services/search/param'
BOUNDARY_URL = ('https://gis-dpmptsp.jakarta.go.id/arcgis/rest/services/Hosted/'
                'Batas_Administrasi_Kelurahan_DKI_Jakarta/FeatureServer/85/query'
                '?where=1%3D1&outFields=wadmkd%2Cwadmkc%2Cwadmkk&returnGeometry=true&outSR=4326&f=geojson')
BOUNDARY_SHA256 = '7bb4dd0589cec8bd64e8930c94b1835116701b6148f7b7de183e61196593c540'

DRIVE_ROOT = Path('/content/drive/MyDrive/InSAR_Risk_Zoning_Project')
DATA_DIR = DRIVE_ROOT / 'NISAR_GUNW_Jakarta_v12'
OUT_DIR = DRIVE_ROOT / 'NISAR_GUNW_Jakarta_v12_results'
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)
INVENTORY_PATH = OUT_DIR / 'v12_nisar_asf_inventory_and_qa.json'
SUMMARY_PATH = OUT_DIR / 'v12_nisar_north_feasibility_summary.json'
ARCHIVE_PATH = OUT_DIR / 'v12_nisar_north_feasibility_outputs.tar.gz'
ARCHIVE_SHA_PATH = OUT_DIR / 'v12_nisar_north_feasibility_outputs.tar.gz.sha256'
BOUNDARY_PATH = OUT_DIR / 'dki_kelurahan_official.geojson'

UNWRAPPED_GROUP = '/science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram'
VARIABLE_PATHS = {
    'unwrapped_phase': UNWRAPPED_GROUP + '/HH/unwrappedPhase',
    'coherence': UNWRAPPED_GROUP + '/HH/coherenceMagnitude',
    'connected_components': UNWRAPPED_GROUP + '/HH/connectedComponents',
    'mask': UNWRAPPED_GROUP + '/mask',
    'ionosphere_phase': UNWRAPPED_GROUP + '/HH/ionospherePhaseScreen',
    'ionosphere_uncertainty': UNWRAPPED_GROUP + '/HH/ionospherePhaseScreenUncertainty',
}
GRID_PATH_CANDIDATES = {
    # Rev-E documents both group-level and polarization-level coordinate/grid
    # mapping datasets.  Resolve either official layout before reading data.
    'x': (UNWRAPPED_GROUP + '/xCoordinates', UNWRAPPED_GROUP + '/HH/xCoordinates'),
    'y': (UNWRAPPED_GROUP + '/yCoordinates', UNWRAPPED_GROUP + '/HH/yCoordinates'),
    'projection': (UNWRAPPED_GROUP + '/projection', UNWRAPPED_GROUP + '/HH/projection'),
}

def sha256_file(path, chunk_size=8 * 1024 * 1024):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()

def scalar(value):
    value = np.asarray(value).reshape(-1)[0]
    return value.decode('utf-8') if isinstance(value, (bytes, np.bytes_)) else value.item() if hasattr(value, 'item') else value

def supplied_mask_flags(mask, attrs):
    # Current production GUNW mask is the documented WRS integer: water flag,
    # reference subswath and secondary subswath. Zero in either subswath digit
    # and the dataset fill value are invalid; water is excluded from this
    # mainland administrative-area test.
    fill = attrs.get('_FillValue', 255)
    fill = int(np.asarray(fill).reshape(-1)[0])
    values = mask.astype(np.int64, copy=False)
    water_flag = values // 100
    reference_subswath = (values // 10) % 10
    secondary_subswath = values % 10
    covered = ((values != fill)
               & (reference_subswath > 0) & (secondary_subswath > 0))
    permitted = covered & (water_flag == 0)
    return covered, permitted

def atomic_json(path, payload):
    partial = path.with_suffix(path.suffix + '.partial')
    partial.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    os.replace(partial, path)

print(json.dumps({'products': len(PRODUCTS), 'total_bytes': EXPECTED_TOTAL_BYTES,
                  'total_GiB': EXPECTED_TOTAL_BYTES / 2**30,
                  'primary_coherence_threshold': PRIMARY_COHERENCE_THRESHOLD}, indent=2))
"""
    ),
    markdown(
        """## Official inventory and QA checkpoint

This cell performs no large download. It requires exact agreement with the frozen ASF product identifiers, byte sizes, tracks, frames and directions, authenticates with Earthdata, retrieves each official QA summary CSV, and stops on an explicit QA failure status. Review the printed census before continuing.
"""
    ),
    code(
        """# 4 — Verify the official ASF inventory and QA summaries before HDF5 download
features = []
for expected in PRODUCTS:
    response = requests.get(ASF_SEARCH_API, params={
        'product_list': expected['id'], 'output': 'geojson',
    }, timeout=120)
    response.raise_for_status()
    matches = response.json().get('features', [])
    if len(matches) != 1:
        raise RuntimeError(f'ASF returned {len(matches)} records for {expected["id"]}.')
    features.append(matches[0])

auth = earthaccess.login(persist=True)
if not auth.authenticated:
    raise RuntimeError('Earthdata authentication did not complete.')
session = earthaccess.get_requests_https_session()
inventory_rows = []
for expected, feature in zip(PRODUCTS, features):
    properties = feature['properties']
    if properties.get('fileID') != expected['id']:
        raise RuntimeError('ASF product identity changed.')
    if int(properties.get('pathNumber')) != expected['track'] or int(properties.get('frameNumber')) != expected['frame']:
        raise RuntimeError(f'ASF track/frame changed for {expected["id"]}.')
    if properties.get('flightDirection', '').upper() != expected['direction']:
        raise RuntimeError(f'ASF direction changed for {expected["id"]}.')
    if properties.get('productionConfiguration') != 'PR' or '_P05023_' not in expected['id']:
        raise RuntimeError(f'Expected provisional P05023 product: {expected["id"]}.')

    filenames = properties.get('bytes', {})
    h5_name = expected['id'] + '.h5'
    if h5_name not in filenames or int(filenames[h5_name]['bytes']) != expected['bytes']:
        raise RuntimeError(f'ASF HDF5 byte size changed for {expected["id"]}.')
    base_url = properties['url'].rsplit('/', 1)[0]
    qa_name = expected['id'] + '_QA_SUMMARY.csv'
    if qa_name not in filenames or int(filenames[qa_name]['bytes']) <= 0:
        raise RuntimeError(f'ASF QA summary is absent for {expected["id"]}.')
    qa_url = base_url + '/' + qa_name
    qa_response = session.get(qa_url, timeout=120)
    qa_response.raise_for_status()
    if len(qa_response.content) != int(filenames[qa_name]['bytes']):
        raise RuntimeError(f'QA summary byte mismatch for {expected["id"]}.')
    qa_path = OUT_DIR / qa_name
    qa_path.write_bytes(qa_response.content)
    rows = list(csv.DictReader(io.StringIO(qa_response.text)))
    explicit_failures = []
    for row_number, row in enumerate(rows, 2):
        for key, value in row.items():
            key_norm, value_norm = str(key).strip().lower(), str(value).strip().upper()
            generic_failure = value_norm in {'FAIL', 'FAILED', 'ERROR', 'INVALID'}
            boolean_failure = (any(token in key_norm for token in ('status', 'result', 'passed', 'valid'))
                               and value_norm in {'FALSE', 'NO', '0'})
            if generic_failure or boolean_failure:
                explicit_failures.append({'row': row_number, 'field': key, 'value': value})
    if not rows:
        raise RuntimeError(f'ASF QA summary contains no data rows for {expected["id"]}.')
    if explicit_failures:
        raise RuntimeError(f'PREREGISTERED STOP: explicit ASF QA failure for {expected["id"]}: {explicit_failures}')
    inventory_rows.append({
        **expected, 'h5_url': properties['url'], 'qa_url': qa_url,
        'qa_bytes': len(qa_response.content), 'qa_sha256': sha256_file(qa_path),
        'qa_rows': len(rows), 'explicit_qa_failures': explicit_failures,
        'processing_date': properties.get('processingDate'),
        'start_time': properties.get('startTime'), 'stop_time': properties.get('stopTime'),
        'footprint_geojson': feature['geometry'],
    })

inventory = {
    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'source': ASF_SEARCH_API, 'collection': 'NISAR_L2_GUNW_PROVISIONAL_V1',
    'expected_total_bytes': EXPECTED_TOTAL_BYTES, 'products': inventory_rows,
    'qa_rule': 'Stop only on an explicit failure token in a QA status/result/passed/valid field.',
}
atomic_json(INVENTORY_PATH, inventory)
print(json.dumps(inventory, indent=2))
print('ASF INVENTORY + QA CHECK PASSED. Review this census before running the ~9.48 GB download cell.')
"""
    ),
    code(
        """# 5 — Restart-safe, exact-size and SHA-256-gated Drive downloads
def download_one(product):
    destination = DATA_DIR / (product['id'] + '.h5')
    checksum_path = destination.with_suffix(destination.suffix + '.sha256')
    if destination.exists() and destination.stat().st_size == product['bytes'] and checksum_path.exists():
        expected_sha = checksum_path.read_text(encoding='utf-8').strip().split()[0]
        actual_sha = sha256_file(destination)
        if actual_sha == expected_sha:
            return {'id': product['id'], 'path': str(destination), 'sha256': actual_sha, 'status': 'verified_existing'}
        raise RuntimeError(f'Existing HDF5 checksum mismatch: {destination}')
    if destination.exists() or checksum_path.exists():
        raise RuntimeError(f'Unverified stale download exists; remove only this product after inspection: {destination}')

    partial = destination.with_suffix(destination.suffix + '.partial')
    if partial.exists() and partial.stat().st_size == product['bytes']:
        digest = sha256_file(partial)
        os.replace(partial, destination)
        checksum_path.write_text(f'{digest}  {destination.name}\\n', encoding='utf-8')
        return {'id': product['id'], 'path': str(destination), 'sha256': digest, 'status': 'finalized_complete_partial'}
    last_error = None
    for attempt in range(1, 7):
        start = partial.stat().st_size if partial.exists() else 0
        if start > product['bytes']:
            partial.unlink(); start = 0
        headers = {'Range': f'bytes={start}-'} if start else {}
        try:
            with session.get(product['h5_url'], headers=headers, stream=True, timeout=(60, 600)) as response:
                if start and response.status_code != 206:
                    partial.unlink(missing_ok=True)
                    raise RuntimeError('Server did not honour the restart Range request.')
                response.raise_for_status()
                if start:
                    content_range = response.headers.get('Content-Range', '')
                    match = re.fullmatch(r'bytes (\\d+)-(\\d+)/(\\d+)', content_range)
                    if (not match or int(match.group(1)) != start
                            or int(match.group(3)) != product['bytes']):
                        partial.unlink(missing_ok=True)
                        raise RuntimeError(f'Invalid restart Content-Range: {content_range!r}')
                with open(partial, 'ab' if start else 'wb') as stream:
                    for chunk in response.iter_content(chunk_size=16 * 1024 * 1024):
                        if chunk:
                            stream.write(chunk)
            if partial.stat().st_size != product['bytes']:
                raise RuntimeError(f'Incomplete HDF5: {partial.stat().st_size} != {product["bytes"]}')
            digest = sha256_file(partial)
            os.replace(partial, destination)
            checksum_path.write_text(f'{digest}  {destination.name}\\n', encoding='utf-8')
            return {'id': product['id'], 'path': str(destination), 'sha256': digest, 'status': 'downloaded'}
        except Exception as exc:
            last_error = exc
            if attempt < 6:
                wait_seconds = min(120, 10 * 2 ** (attempt - 1))
                print(f'{product["id"]}: attempt {attempt} failed at {partial.stat().st_size if partial.exists() else 0} bytes; retrying in {wait_seconds}s')
                time.sleep(wait_seconds)
    raise RuntimeError(f'Download failed after six attempts: {product["id"]}') from last_error

downloads = []
for index, product in enumerate(inventory_rows, 1):
    result = download_one(product)
    downloads.append(result)
    print(f'Verified {index}/4: {result["id"]} ({result["status"]})')
inventory['downloads'] = downloads
atomic_json(INVENTORY_PATH, inventory)
print('All four GUNWs are size- and SHA-256-verified in Drive.')
"""
    ),
    markdown(
        """## Exact North-Jakarta analysis

The denominator is the exact projected area in EPSG:32748 of official Jakarta Utara kelurahan polygons. For each native NISAR 80 m cell, its polygon is intersected with that boundary; no point-count or raster-resampling approximation is used. A usable cell is permitted by the supplied WRS mask, has finite unwrapped phase, a non-zero connected-component label, and coherence at or above the frozen threshold.
"""
    ),
    code(
        """# 6 — Verify HDF5 structure, read only the North-Jakarta window and compute weighted pixel metrics
boundary_response = requests.get(BOUNDARY_URL, timeout=120)
boundary_response.raise_for_status()
if hashlib.sha256(boundary_response.content).hexdigest() != BOUNDARY_SHA256:
    raise RuntimeError('Official DKI boundary checksum changed; stop for review.')
BOUNDARY_PATH.write_bytes(boundary_response.content)
boundary = boundary_response.json()
north_features = [f for f in boundary['features'] if 'UTARA' in str(f['properties'].get('wadmkk', '')).upper()]
if not north_features:
    raise RuntimeError('Official Jakarta Utara polygons were not found.')
north_wgs84 = unary_union([shape(f['geometry']) for f in north_features])
to_projected_area = Transformer.from_crs(4326, 32748, always_xy=True).transform
north_projected_area = shapely_transform(to_projected_area, north_wgs84)
north_total_area_m2 = north_projected_area.area

def resolve_grid_paths(h5):
    resolved = {}
    for key, candidates in GRID_PATH_CANDIDATES.items():
        present = [path for path in candidates if path in h5]
        if not present:
            raise RuntimeError(f'Missing every documented {key} path: {candidates}')
        resolved[key] = present[0]
    return resolved

def find_epsg(h5, projection_path):
    projection = h5[projection_path]
    for key in ('epsg_code', 'EPSG', 'epsg'):
        if key in projection.attrs:
            value = scalar(projection.attrs[key])
            digits = re.findall(r'\\d+', str(value))
            if digits:
                return int(digits[-1])
    value = scalar(projection[()])
    digits = re.findall(r'\\d+', str(value))
    if digits:
        return int(digits[-1])
    raise RuntimeError('Could not resolve the GUNW projection EPSG code.')

def analyse_product(product, threshold):
    path = Path(next(item['path'] for item in downloads if item['id'] == product['id']))
    with h5py.File(path, 'r') as h5:
        missing = [dataset for dataset in VARIABLE_PATHS.values() if dataset not in h5]
        if missing:
            raise RuntimeError(f'Missing required HDF5 variables in {product["id"]}: {missing}')
        grid_paths = resolve_grid_paths(h5)
        epsg = find_epsg(h5, grid_paths['projection'])
        x = h5[grid_paths['x']][:].astype(float)
        y = h5[grid_paths['y']][:].astype(float)
        if x.ndim != 1 or y.ndim != 1 or len(x) < 2 or len(y) < 2:
            raise RuntimeError('Unexpected GUNW coordinate arrays.')
        dx, dy = float(np.median(np.diff(x))), float(np.median(np.diff(y)))
        if not np.allclose(np.diff(x), dx, rtol=0, atol=abs(dx) * 1e-6) or not np.allclose(np.diff(y), dy, rtol=0, atol=abs(dy) * 1e-6):
            raise RuntimeError('GUNW coordinates are not a regular grid.')
        north_native = shapely_transform(Transformer.from_crs(4326, epsg, always_xy=True).transform, north_wgs84)
        minx, miny, maxx, maxy = north_native.bounds
        cols = np.where((x >= minx - abs(dx)) & (x <= maxx + abs(dx)))[0]
        rows = np.where((y >= miny - abs(dy)) & (y <= maxy + abs(dy)))[0]
        if not len(cols) or not len(rows):
            raise RuntimeError(f'No North-Jakarta grid overlap in {product["id"]}.')
        rs, cs = slice(rows.min(), rows.max() + 1), slice(cols.min(), cols.max() + 1)
        expected_shape = (len(y), len(x))
        for key in ('unwrapped_phase', 'coherence', 'connected_components', 'mask',
                    'ionosphere_phase', 'ionosphere_uncertainty'):
            if h5[VARIABLE_PATHS[key]].shape != expected_shape:
                raise RuntimeError(f'Unexpected {key} shape in {product["id"]}: {h5[VARIABLE_PATHS[key]].shape} != {expected_shape}')
        phase = h5[VARIABLE_PATHS['unwrapped_phase']][rs, cs]
        coherence = h5[VARIABLE_PATHS['coherence']][rs, cs]
        component_ds = h5[VARIABLE_PATHS['connected_components']]
        components = component_ds[rs, cs]
        default_component_fill = np.iinfo(component_ds.dtype).max
        component_fill = int(np.asarray(component_ds.attrs.get('_FillValue', default_component_fill)).reshape(-1)[0])
        mask_ds = h5[VARIABLE_PATHS['mask']]
        supplied_mask = mask_ds[rs, cs]
        # Read the required correction layers to prove their presence and report
        # finite coverage; they are not applied to phase in this feasibility test.
        ionosphere = h5[VARIABLE_PATHS['ionosphere_phase']][rs, cs]
        ionosphere_uncertainty = h5[VARIABLE_PATHS['ionosphere_uncertainty']][rs, cs]
        covered, permitted = supplied_mask_flags(supplied_mask, dict(mask_ds.attrs))

    native_to_projected = Transformer.from_crs(epsg, 32748, always_xy=True).transform
    weights = np.zeros(phase.shape, dtype=np.float64)
    for local_r, source_r in enumerate(range(rows.min(), rows.max() + 1)):
        for local_c, source_c in enumerate(range(cols.min(), cols.max() + 1)):
            cell = box(x[source_c] - abs(dx) / 2, y[source_r] - abs(dy) / 2,
                       x[source_c] + abs(dx) / 2, y[source_r] + abs(dy) / 2)
            cell_projected = shapely_transform(native_to_projected, cell)
            weights[local_r, local_c] = cell_projected.intersection(north_projected_area).area
    in_north = weights > 0
    footprint_area = float(weights[in_north & covered].sum())
    usable = (in_north & permitted & np.isfinite(phase) & np.isfinite(coherence)
              & (components > 0) & (components != component_fill)
              & (coherence >= threshold))
    usable_area = float(weights[usable].sum())
    component_areas = {}
    for label in np.unique(components[usable]):
        component_areas[int(label)] = float(weights[usable & (components == label)].sum())
    largest_share = max(component_areas.values(), default=0.0) / usable_area if usable_area else 0.0
    return {
        'id': product['id'], 'track': product['track'], 'frame': product['frame'],
        'direction': product['direction'], 'pair': product['pair'], 'epsg': epsg,
        'resolved_grid_paths': grid_paths,
        'x': x[cs], 'y': y[rs], 'weights': weights, 'coherence': coherence,
        'components': components, 'usable': usable, 'permitted': permitted,
        'phase_finite': np.isfinite(phase),
        'footprint_area_m2': footprint_area,
        'footprint_coverage_fraction': footprint_area / north_total_area_m2,
        'usable_area_m2': usable_area, 'usable_fraction': usable_area / north_total_area_m2,
        'largest_component_share_of_usable': largest_share,
        'component_count': len(component_areas),
        'median_coherence_on_north': float(np.nanmedian(np.where(in_north, coherence, np.nan))),
        'ionosphere_finite_fraction': float(weights[in_north & np.isfinite(ionosphere)].sum() / north_total_area_m2),
        'ionosphere_uncertainty_finite_fraction': float(weights[in_north & np.isfinite(ionosphere_uncertainty)].sum() / north_total_area_m2),
        'mask_value_counts': {str(int(k)): int(v) for k, v in zip(*np.unique(supplied_mask[in_north], return_counts=True))},
    }

analyses = {threshold: [analyse_product(product, threshold) for product in inventory_rows]
            for threshold in (PRIMARY_COHERENCE_THRESHOLD, *SENSITIVITY_THRESHOLDS)}

def public_metrics(item):
    omitted = {'x', 'y', 'weights', 'coherence', 'components', 'usable', 'permitted', 'phase_finite'}
    return {key: value for key, value in item.items() if key not in omitted}

print(json.dumps([public_metrics(item) for item in analyses[PRIMARY_COHERENCE_THRESHOLD]], indent=2))
"""
    ),
    code(
        """# 7 — Apply the frozen per-track gates and report non-decisional sensitivity
def evaluate_threshold(items, threshold, decisional=False):
    tracks = {}
    for track in (10, 18):
        pair_items = sorted((item for item in items if item['track'] == track), key=lambda item: item['pair'])
        if len(pair_items) != 2:
            raise RuntimeError(f'Expected two interferograms for track {track}.')
        first, second = pair_items
        if first['epsg'] != second['epsg'] or not np.array_equal(first['x'], second['x']) or not np.array_equal(first['y'], second['y']):
            raise RuntimeError(f'Track {track} pair grids differ; exact same-pixel overlap is not evaluable.')
        if not np.allclose(first['weights'], second['weights'], rtol=0, atol=1e-6):
            raise RuntimeError(f'Track {track} North-area weights differ between pairs.')
        common_area = float(first['weights'][first['usable'] & second['usable']].sum())
        common_fraction = common_area / north_total_area_m2
        failures = []
        if any(item['footprint_coverage_fraction'] < MIN_FOOTPRINT_COVERAGE for item in pair_items):
            failures.append('footprint_coverage')
        if any(item['usable_fraction'] < MIN_EACH_IFG_USABLE_FRACTION for item in pair_items):
            failures.append('each_interferogram_usable_fraction')
        if common_fraction < MIN_TWO_IFG_COMMON_USABLE_FRACTION:
            failures.append('two_interferogram_common_usable_fraction')
        if any(item['largest_component_share_of_usable'] < MIN_LARGEST_COMPONENT_SHARE for item in pair_items):
            failures.append('largest_component_share')
        tracks[str(track)] = {
            'track': track, 'direction': pair_items[0]['direction'],
            'interferograms': [public_metrics(item) for item in pair_items],
            'two_interferogram_common_usable_area_m2': common_area,
            'two_interferogram_common_usable_fraction': common_fraction,
            'passed': not failures, 'gate_failures': failures,
        }
    pass_count = sum(item['passed'] for item in tracks.values())
    decision = 'strong_feasibility' if pass_count == 2 else 'partial_feasibility' if pass_count == 1 else 'failure'
    return {'coherence_threshold': threshold, 'decisional': decisional, 'tracks': tracks,
            'passing_track_count': pass_count, 'decision': decision}

primary_result = evaluate_threshold(analyses[PRIMARY_COHERENCE_THRESHOLD], PRIMARY_COHERENCE_THRESHOLD, True)
sensitivity_results = [evaluate_threshold(analyses[value], value, False) for value in SENSITIVITY_THRESHOLDS]
summary = {
    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'experiment': 'North-Jakarta provisional NISAR L-band GUNW usability feasibility',
    'official_boundary_sha256': BOUNDARY_SHA256,
    'north_denominator': 'exact projected area in EPSG:32748 of checksum-frozen official Jakarta Utara kelurahan polygons',
    'north_total_area_m2': north_total_area_m2,
    'usable_definition': 'supplied WRS mask permits land; finite unwrapped phase; connected component > 0; coherence >= threshold',
    'thresholds': {
        'primary_coherence': PRIMARY_COHERENCE_THRESHOLD,
        'sensitivity_only_coherence': list(SENSITIVITY_THRESHOLDS),
        'min_footprint_coverage': MIN_FOOTPRINT_COVERAGE,
        'min_each_interferogram_usable_fraction': MIN_EACH_IFG_USABLE_FRACTION,
        'min_two_interferogram_common_usable_fraction': MIN_TWO_IFG_COMMON_USABLE_FRACTION,
        'min_largest_component_share': MIN_LARGEST_COMPONENT_SHARE,
    },
    'primary_result': primary_result,
    'sensitivity_non_decisional': sensitivity_results,
    'interpretation_limits': [
        'No velocity or deformation rate can be estimated from this experiment.',
        'No loop-closure test is possible because the available pairs form no three-edge temporal cycle.',
        'A connected unwrapped component does not independently validate phase accuracy.',
        'The result cannot validate the 2020-2023 Sentinel-1 v9 candidate.',
        'L-band is confounded with 2026 dates, season, geometry, polarization, resolution, baselines and processor.',
        'The supplied ionospheric and atmospheric corrections are not applied by default; correction layers are reported, not used to infer deformation.',
        'The provisional P05023 products may change during calibration and validated reprocessing.',
    ],
    'allowed_claim': 'Repeatable NISAR L-band interferometric usability over North Jakarta under these four 2026 provisional acquisition conditions.',
    'prohibited_claims': ['velocity', 'subsidence rate', 'loop closure', 'band causality', 'v9 validation', 'hazard map', 'risk map'],
    'product_downloads': downloads,
}
atomic_json(SUMMARY_PATH, summary)
print(json.dumps(summary, indent=2))
"""
    ),
    code(
        """# 8 — Render diagnostic maps and create a verified, restart-safe results archive
primary_items = analyses[PRIMARY_COHERENCE_THRESHOLD]
fig, axes = plt.subplots(4, 2, figsize=(13, 18), constrained_layout=True)
for row, item in enumerate(primary_items):
    extent = [item['x'].min(), item['x'].max(), item['y'].min(), item['y'].max()]
    image_origin = 'lower' if item['y'][-1] > item['y'][0] else 'upper'
    coherence_plot = np.where(item['weights'] > 0, item['coherence'], np.nan)
    image = axes[row, 0].imshow(coherence_plot, extent=extent, origin=image_origin, vmin=0, vmax=1, cmap='gray')
    axes[row, 0].set_title(f'Track {item["track"]} {item["pair"]}: coherence')
    fig.colorbar(image, ax=axes[row, 0], fraction=0.046)
    axes[row, 1].imshow(np.where(item['weights'] > 0, item['usable'].astype(float), np.nan),
                        extent=extent, origin=image_origin, vmin=0, vmax=1, cmap='viridis')
    axes[row, 1].set_title(f'Usable at coherence ≥ {PRIMARY_COHERENCE_THRESHOLD:.2f}')
for axis in axes.flat:
    axis.set_xlabel('Native projected x (m)'); axis.set_ylabel('Native projected y (m)')
figure_path = OUT_DIR / 'v12_nisar_north_coherence_and_usable.png'
fig.savefig(figure_path, dpi=180)
plt.close(fig)

archive_members = [INVENTORY_PATH, SUMMARY_PATH, BOUNDARY_PATH, figure_path]
archive_members.extend(sorted(OUT_DIR.glob('*_QA_SUMMARY.csv')))
partial_archive = ARCHIVE_PATH.with_suffix(ARCHIVE_PATH.suffix + '.partial')
partial_archive.unlink(missing_ok=True)
with tarfile.open(partial_archive, 'w:gz') as archive:
    for member in archive_members:
        archive.add(member, arcname=member.name)
with tarfile.open(partial_archive, 'r:gz') as archive:
    archived_names = set(archive.getnames())
if {member.name for member in archive_members} != archived_names:
    raise RuntimeError('Diagnostic archive inventory mismatch.')
os.replace(partial_archive, ARCHIVE_PATH)
archive_sha = sha256_file(ARCHIVE_PATH)
ARCHIVE_SHA_PATH.write_text(f'{archive_sha}  {ARCHIVE_PATH.name}\\n', encoding='utf-8')
if sha256_file(ARCHIVE_PATH) != archive_sha:
    raise RuntimeError('Final archive checksum verification failed.')
print(f'VERIFIED archive: {ARCHIVE_PATH} ({ARCHIVE_PATH.stat().st_size / 1e6:.1f} MB)')
print('SHA-256:', archive_sha)
print('Decision:', primary_result['decision'])
print('STOP: this experiment does not authorize velocity, deformation, hazard or risk claims.')
"""
    ),
]


notebook = {
    "cells": cells,
    "metadata": {
        "colab": {"provenance": []},
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}
# Match the archived notebook's registered bytes on every OS.
OUTPUT.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\r\n")
print(OUTPUT)
