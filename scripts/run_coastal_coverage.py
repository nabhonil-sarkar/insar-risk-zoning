"""Separate Stage 1 entry point. No acquisition without fresh exact-hash approval.

The immutable seasonal protocol remains preparation-only; execution authority
must live in a separately reviewed record. This module has no Stage 2 path.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import threading
import xml.etree.ElementTree as ET

import numpy as np

from scripts import coastal_coverage as coverage
from scripts import run_coastal_pilot as native
from scripts import coastal_pilot_pc as pc
from scripts.coastal_transport import Budget, Transport, GateError
from scripts.coastal_validation import ValidationError, xml_nodata_contract, record_failure

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/output/coastal_jun_sep_v1'
PROTOCOL_SHA = '948626ae2e8267177ab8ced5a18ac65f5cef23a019e2cc46fd0c461133a7c917'
YEAR_ORDER = (2022, 2021, 2024, 2023, 2020, 2025)
RUN_NAME = 'stage1_run'
CEILING = 3 * 1024**3
DOCUMENTATION_HOLD = 67108864
RECORDED_BYTES = 814247424
PRIOR_SECONDS = 734
MIN_DISK = 7 * 1024**3
METHOD = 'docs/InSAR_Subsidence_Risk_Zoning_Methodology.docx'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def checked(path, expected):
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
        raise GateError('Explicit SHA-256 required')
    if not Path(path).is_file():
        raise GateError('Required record absent: ' + Path(path).name)
    if digest(path) != expected:
        raise GateError('Hash mismatch: ' + Path(path).name)
    return json.loads(Path(path).read_bytes())


def load_bundle(root, out):
    """Offline metadata only. Preserve original assets and every source contract."""
    protocol = checked(out / 'protocol.json', PROTOCOL_SHA)
    if protocol['execution_approved'] is not False:
        raise GateError('Immutable proposal status changed')
    bundle = {n: checked(out / n, h) for n, h in protocol['bundle_sha256'].items()}
    for name, h in protocol['evidence_sha256'].items():
        checked(root / name, h) if name.endswith('.json') else _hash_gate(root / name, h)
    prior = bundle['prior_evidence.json']['files_sha256']
    for name, h in prior.items():
        if name.startswith('data/output/') or name in native.FIXED:
            _hash_gate(root / name, h)
    _hash_gate(native.f.WC_PATH, native.f.WC_SHA)
    acquisitions = bundle['acquisitions.json']
    selected = checked(root / acquisitions['source_selection_path'],
                       acquisitions['source_selection_sha256'])
    by_id = {i['id']: i for i in selected['selected_items']}
    records = acquisitions['acquisitions']
    resources = bundle['selected_resources.json']
    originals = checked(root / resources['parent_resources_path'], resources['parent_resources_sha256'])
    original_scenes = {s['item']: s for s in originals['scenes']}
    scenes = resources['scenes']
    expected_ids = {i['id'] for i in selected['selected_items']
                    if 6 <= int(i['properties']['datetime'][5:7]) <= 9}
    if (len(records) != 48 or len(scenes) != 48 or len(expected_ids) != 48
            or {a['item_id'] for a in records} != expected_ids
            or {s['item'] for s in scenes} != expected_ids
            or len({a['date_utc'] for a in records}) != 48
            or tuple(protocol['observations']['yearly_acquisition_order']) != YEAR_ORDER
            or sum(len(s['assets']) for s in scenes) != 288):
        raise GateError('Frozen scene/asset/year selection changed')
    contracts = {}
    for scene in scenes:
        item = by_id[scene['item']]
        if scene != original_scenes[scene['item']] or {a['asset'] for a in scene['assets']} != set(protocol['source']['assets']):
            raise GateError('Registered asset/range changed')
        pc.contract(item)
        record = next(a for a in records if a['item_id'] == scene['item'])
        props = item['properties']
        if (record['sensing_timestamp_utc'] != props['datetime']
                or record['spacecraft'] != props['platform']
                or record['processing_baseline'] != props['s2:processing_baseline']
                or record['date_utc'] != props['datetime'][:10]):
            raise GateError('Acquisition provenance changed')
        raw = (root / record['product_xml_path']).read_bytes()
        for asset in scene['assets']:
            contracts[(scene['item'], asset['asset'])] = xml_nodata_contract(raw, item, scene, asset['asset'])
        if pc.radiometry(raw, props['s2:processing_baseline']) != scene['radiometry']:
            raise GateError('Calibration mismatch')
    for year in range(2020, 2026):
        if len([a for a in records if a['year'] == year]) != 8:
            raise GateError('Eight dates per year required')
    return dict(protocol=protocol, acquisitions=acquisitions, scenes=scenes,
                by_id=by_id, contracts=contracts, budget=bundle['budget.json'])


def _hash_gate(path, expected):
    if digest(path) != expected:
        raise GateError('Protected file changed: ' + Path(path).name)


def accounting(approval):
    """The documentation allowance is one separate hold, never a second charge."""
    later = approval.get('additional_recorded_charges_bytes')
    later_seconds = approval.get('additional_acquisition_seconds')
    if (type(later) is not int or later < 0 or type(later_seconds) is not int or later_seconds < 0
            or approval.get('recorded_cumulative_debit_bytes') != RECORDED_BYTES
            or approval.get('documentation_hold_bytes') != DOCUMENTATION_HOLD):
        raise GateError('Invalid cumulative accounting/hold')
    total = RECORDED_BYTES + DOCUMENTATION_HOLD + later
    seconds = PRIOR_SECONDS + later_seconds
    if total >= CEILING or seconds >= 7200:
        raise GateError('Cumulative budget exhausted')
    if (approval.get('effective_prior_reserved_bytes') != total
            or approval.get('effective_prior_seconds') != seconds):
        raise GateError('Carry-in or documentation hold counted incorrectly')
    return total, seconds


def verify_authority(root, out, approval_sha, verification_sha, *, free_bytes=None,
                     commit_fn=native.clean_commit):
    """No network, writes, or output reservation before all local gates pass."""
    a = checked(out / 'stage1_execution_approval.json', approval_sha)
    expected = dict(schema='coastal_jun_sep_execution_approval_v1', stage=1,
                    execution_approved=True, acquisition_approved=True, protocol_sha256=PROTOCOL_SHA,
                    output_directory=RUN_NAME, total_acquisition_ceiling_bytes=CEILING,
                    acquisition_wall_seconds=7200, minimum_free_disk_bytes=MIN_DISK,
                    no_classification=True, no_stage2=True)
    if any(a.get(k) != v for k, v in expected.items()):
        raise GateError('Separate Stage 1 execution approval required')
    if not a.get('owner_wording'):
        raise GateError('Owner execution authorization absent')
    carried = accounting(a)
    reconciliation = checked(out / 'stage1_accounting_reconciliation.json', a.get('accounting_reconciliation_sha256'))
    for key in ('recorded_cumulative_debit_bytes', 'documentation_hold_bytes',
                'additional_recorded_charges_bytes', 'additional_acquisition_seconds',
                'effective_prior_reserved_bytes', 'effective_prior_seconds'):
        if reconciliation.get(key) != a.get(key):
            raise GateError('Accounting reconciliation disagrees')
    if reconciliation.get('protocol_sha256') != PROTOCOL_SHA:
        raise GateError('Accounting not bound to seasonal protocol')
    v = checked(out / 'stage1_execution_verification.json', verification_sha)
    if (v.get('schema') != 'coastal_jun_sep_execution_verification_v1'
            or v.get('protocol_sha256') != PROTOCOL_SHA or v.get('stage') != 1
            or v.get('execution_approval_sha256') != approval_sha):
        raise GateError('Fresh Stage 1 execution verification required')
    junit = out / v['tests_xml']
    _hash_gate(junit, v['tests_xml_sha256'])
    tree = ET.parse(junit)
    suites = list(tree.getroot().iter('testsuite'))
    totals = {k: sum(int(s.get(k, '0')) for s in suites) for k in ('tests', 'failures', 'errors', 'skipped')}
    if (totals['tests'] <= 326 or len(list(tree.iter('testcase'))) != totals['tests']
            or any(totals[k] for k in ('failures', 'errors', 'skipped'))
            or totals['tests'] != v.get('passed')
            or not any('test_coastal_stage1' in t.get('classname', '') for t in tree.iter('testcase'))):
        raise GateError('Full Stage 1 suite missing/incomplete/failed')
    # Hash every script and test, including imported legacy native helpers.
    required = {str(p.relative_to(root)).replace('\\', '/')
                for folder in ('scripts', 'tests') for p in (root / folder).rglob('*.py')}
    required.update({METHOD, 'pyproject.toml', 'requirements.lock.txt'})
    hashes = v.get('executing_file_sha256', {})
    if not required <= hashes.keys():
        raise GateError('Incomplete code/test/methodology verification')
    for name, h in hashes.items():
        _hash_gate(root / name, h)
    review = checked(out / v['methodology_review'], v['methodology_review_sha256'])
    if review.get('all_pages_reviewed') is not True or review.get('docx_sha256') != digest(root / METHOD):
        raise GateError('Methodology render review missing/stale')
    commit = commit_fn(root)
    if v.get('commit') != commit:
        raise GateError('Verification is not for executing commit')
    if (free_bytes if free_bytes is not None else shutil.disk_usage(out).free) < MIN_DISK:
        raise GateError('Less than 7 GiB free disk')
    if (out / RUN_NAME).exists():
        raise GateError('Stage 1 output exists; no overwrite or resume')
    return a, v, carried, commit


def all_rows(bundle, measured, complete, started):
    lookup = {(r['window'], r['year'], r['buffer_m']): r for r in measured}
    rows = []
    for w in bundle['protocol']['geometry']['windows']:
        for year in range(2020, 2026):
            records = [a for a in bundle['acquisitions']['acquisitions'] if a['year'] == year]
            done = [a for a in records if a['date_utc'] in complete]
            attempted = [a for a in records if a['date_utc'] in started]
            for buffer in coverage.BUFFERS:
                row = dict(lookup.get((w['id'], year, buffer),
                    dict(window=w['id'], year=year, season='Jun-Sep', buffer_m=buffer,
                         status='partially_acquired' if attempted else 'not_acquired_after_stop',
                         selected_dates=8, acquired_dates=len(done), core_cells=2500,
                         supported_cells=None, support_fraction=None, support_gate_pass=None,
                         dates=[a['date_utc'] for a in records])))
                row.update(started_dates=[a['date_utc'] for a in attempted],
                           complete_dates=[a['date_utc'] for a in done],
                           provenance=records)
                rows.append(row)
    return rows


def save_coverage(run, rows, arrays):
    write_new(run / 'coverage.json', rows)
    fields = list(dict.fromkeys(k for r in rows for k in r if k != 'provenance')) + ['provenance']
    with (run / 'coverage.csv').open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in row.items()})
    with (run / 'coverage_arrays.npz').open('xb') as stream:
        np.savez_compressed(stream, **arrays)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), layout='constrained')
    for ax, buffer in zip(axes, coverage.BUFFERS):
        a = np.full((6, 6), np.nan)
        names = ['C1', 'C2', 'C3', 'C4', 'L1', 'W1']
        for r in rows:
            if r['buffer_m'] == buffer and r['support_fraction'] is not None:
                a[names.index(r['window']), r['year'] - 2020] = r['support_fraction']
        cmap = plt.get_cmap('viridis').with_extremes(bad='#dddddd')
        ax.imshow(a, vmin=0, vmax=1, cmap=cmap, aspect='auto')
        ax.set_xticks(range(6), range(2020, 2026)); ax.set_yticks(range(6), names)
        ax.set_title(f'June-September support; {buffer} m buffer; required >=80%')
        for i, j in np.ndindex(a.shape):
            ax.text(j, i, 'unmeasured' if np.isnan(a[i, j]) else f'{a[i,j]:.1%}',
                    ha='center', va='center', fontsize=8)
    fig.savefig(run / 'coverage.png', dpi=160); plt.close(fig)


def execute_coverage(bundle, run, budget, transport, *, inspect=native.inspect_native,
                     acquire=native.acquire_scene):
    """Internal orchestration; callbacks enable entirely synthetic offline tests.

    Live caller must use run(), which validates authority before creating transport.
    No classification callback or automatic continuation exists.
    """
    measured, arrays, complete, started, fields = [], {}, {}, set(), {}
    lock = threading.Lock()
    windows = bundle['protocol']['geometry']['windows']
    scenes = {s['item']: s for s in bundle['scenes']}
    records = bundle['acquisitions']['acquisitions']
    failures = run / 'validation_failures'; failures.mkdir(exist_ok=False)
    result = {}

    def guarded(function, *args):
        try:
            budget.check()
            return function(*args)
        except Exception as exc:
            if isinstance(exc, ValidationError):
                record_failure(failures, exc)
            budget.stop(str(exc) if isinstance(exc, GateError) else type(exc).__name__)
            raise

    def get_scene(a):
        budget.check()
        with lock:
            started.add(a['date_utc'])
        return guarded(acquire, scenes[a['item_id']], bundle['by_id'][a['item_id']],
                       fields, transport, run, windows, bundle['contracts'])

    def retain(a, observation):
        # Validate/prepare all masks before marking a scene complete.
        masks = {f"{a['date_utc']}_{w['id']}_{b}_clear": coverage.clear_mask(observation[w['id']], b)
                 for w in windows for b in coverage.BUFFERS}
        arrays.update(masks)
        complete[a['date_utc']] = a

    try:
        jobs = [(bundle['by_id'][s['item']], asset, bundle['contracts'][(s['item'], asset['asset'])])
                for s in bundle['scenes'] for asset in s['assets']]
        with ThreadPoolExecutor(max_workers=6) as pool:
            pending = [pool.submit(guarded, inspect, job, transport) for job in jobs]
            try:
                for future in as_completed(pending):
                    record = future.result()
                    fields[(record['item'], record['asset'])] = record
            except Exception:
                for future in pending:
                    future.cancel()
                raise
        if len(fields) != 288:
            raise GateError('All 288 native headers must pass before pixels')
        write_new(run / 'native_metadata.json', list(fields.values()))
        areas = {w['id']: coverage.cell_areas(w['core_bounds_utm']) for w in windows}
        for year in YEAR_ORDER:
            budget.check()
            batch = sorted((a for a in records if a['year'] == year), key=lambda a: a['date_utc'])
            first_error = None
            with ThreadPoolExecutor(max_workers=6) as pool:
                pending = {pool.submit(get_scene, a): a for a in batch}
                for future in as_completed(pending):
                    if future.cancelled():
                        continue
                    try:
                        retain(pending[future], future.result())
                    except Exception as exc:
                        first_error = first_error or exc
                        budget.stop(str(exc) if isinstance(exc, GateError) else type(exc).__name__)
                        for other in pending:
                            other.cancel()
            if first_error is not None:
                raise first_error
            dates = [a['date_utc'] for a in batch]
            year_rows = []
            for w in windows:
                for buffer in coverage.BUFFERS:
                    clear = np.stack([arrays[f'{d}_{w["id"]}_{buffer}_clear'] for d in dates])
                    row, metrics = coverage.coverage_row(w['id'], year, dates, clear, buffer, areas[w['id']])
                    year_rows.append(row)
                    arrays.update({f'{year}_{w["id"]}_{buffer}_{k}': v for k, v in metrics.items()})
            measured.extend(year_rows)
            write_new(run / f'coverage_{year}_Jun-Sep.json', year_rows)
            if not all(r['support_gate_pass'] for r in year_rows):
                result = dict(status='STOP_TEMPORAL_SUPPORT', failed_rows=[r for r in year_rows if not r['support_gate_pass']],
                              reason='First failed coverage gate; optical branch closed under current scope. No replacement or rescue.')
                break
        if not result:
            result = dict(status='COVERAGE_PASSED_AWAITING_OWNER_REVIEW',
                          reason='All six years pass; stop for owner review without classification.')
    except Exception as exc:
        result = dict(status='STOP_EXECUTION_GATE', error_type=type(exc).__name__,
                      reason=budget.stop_reason or (str(exc) if isinstance(exc, GateError) else type(exc).__name__))
        if isinstance(exc, ValidationError):
            result['validation_failure'] = exc.detail
    finally:
        if not (run / 'native_metadata.json').exists():
            write_new(run / 'native_metadata.json', list(fields.values()))
        rows = all_rows(bundle, measured, complete, started)
        save_coverage(run, rows, arrays)
        write_new(run / 'acquisition_provenance.json', dict(selected=records,
                  yearly=bundle['acquisitions']['yearly'], complete_dates=sorted(complete), started_dates=sorted(started)))
        result.update(stage=1, protocol_sha256=PROTOCOL_SHA, transitions_inferred=False,
                      classification_performed=False, stage2_authorized=False,
                      acquired_complete_dates=sorted(complete), started_dates=sorted(started),
                      validated_assets=len(fields), body_bytes_received=budget.received,
                      total_reserved_bytes=budget.reserved, prior_reserved_bytes=budget.prior_reserved,
                      attempt_reserved_bytes=budget.reserved-budget.prior_reserved,
                      documentation_hold_bytes=DOCUMENTATION_HOLD,
                      prior_elapsed_seconds=budget.prior_seconds,
                      acquisition_elapsed_seconds=budget.clock()-budget.start,
                      attempt_elapsed_seconds=budget.clock()-budget.attempt_start,
                      no_scale_up=True, no_phase_c=True,
                      failure_scope=bundle['protocol']['failure_conclusion'])
        if (run / 'execution.json').exists():
            execution = json.loads((run / 'execution.json').read_bytes())
            result.update({k: execution[k] for k in ('commit', 'execution_approval_sha256',
                           'execution_verification_sha256')})
        write_new(run / 'results.json', result)
        write_new(run / 'output_audit.json', dict(files_sha256={str(p.relative_to(run)).replace('\\', '/'): digest(p)
                  for p in sorted(run.rglob('*')) if p.is_file()}))
    return result


def run(root=ROOT, out=OUT, *, approval_sha, verification_sha):
    root, out = Path(root), Path(out)
    approval, verification, carried, commit = verify_authority(root, out, approval_sha, verification_sha)
    bundle = load_bundle(root, out)
    dest = out / RUN_NAME
    dest.mkdir(exist_ok=False)
    write_new(dest / 'execution.json', dict(stage=1, protocol_sha256=PROTOCOL_SHA,
        execution_approval_sha256=approval_sha, execution_verification_sha256=verification_sha,
        commit=commit, prior_reserved_bytes=carried[0], prior_elapsed_seconds=carried[1],
        documentation_hold_bytes=DOCUMENTATION_HOLD, free_disk_bytes=shutil.disk_usage(out).free))
    budget = Budget(CEILING, 7200, dest / 'transfer.jsonl', prior_reserved=carried[0], prior_seconds=carried[1])
    return execute_coverage(bundle, dest, budget, Transport(budget))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approval-sha256', required=True)
    parser.add_argument('--verification-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(run(approval_sha=args.approval_sha256, verification_sha=args.verification_sha256), indent=2))
