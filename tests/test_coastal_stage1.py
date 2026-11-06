"""Synthetic/offline Stage 1 verification; never request or decode seasonal data."""

from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

from scripts import coastal_coverage as c
from scripts import run_coastal_coverage as r
from scripts import coastal_pilot_rules as old_rules
from scripts import coastal_inference as old_inference
from scripts.coastal_transport import Budget, Transport, GateError
from tests.test_coastal_execution import response


def dates(year=2022):
    return [f'{year}-{month:02}-{day:02}' for month in (6, 7, 8, 9) for day in (1, 20)]


def observation(scl=4):
    # Negative finite values must count as clear; there is no spectral sum floor.
    return dict(B03=np.full((66, 66), -.1), B11=np.full((66, 66), -.1),
                SCL=np.full((66, 66), scl, dtype=np.uint8))


def synthetic_bundle():
    windows = [dict(id=w, core_bounds_utm=[673000, 9317000, 674000, 9318000])
               for w in ('C1', 'C2', 'C3', 'C4', 'L1', 'W1')]
    records, scenes, items, contracts = [], [], {}, {}
    for year in range(2020, 2026):
        for day in dates(year):
            item = 'synthetic_' + day
            records.append(dict(item_id=item, year=year, date_utc=day,
                sensing_timestamp_utc=day+'T03:01:02.123Z', spacecraft='synthetic-A', processing_baseline='04.00'))
            assets = [dict(asset=a) for a in ('B02', 'B03', 'B04', 'B08', 'B11', 'SCL')]
            scenes.append(dict(item=item, assets=assets))
            items[item] = dict(id=item)
            contracts.update({(item, a['asset']): object() for a in assets})
    return dict(protocol=dict(geometry=dict(windows=windows), failure_conclusion='Bounded synthetic design only'),
                acquisitions=dict(acquisitions=records, yearly=[dict(year=y) for y in range(2020, 2026)]),
                scenes=scenes, by_id=items, contracts=contracts)


def forbid_classification(monkeypatch):
    forbidden = Mock(side_effect=AssertionError('Stage 1 called classification'))
    for name in ('date_states', 'season_state', 'annual_state', 'persistence'):
        monkeypatch.setattr(old_rules, name, forbidden)
    for name in ('classify', 'deliver_states', 'final_gates', 'coverage_batch'):
        monkeypatch.setattr(old_inference, name, forbidden)
    monkeypatch.setattr(r.native, 'baseline_controls', forbidden)
    return forbidden


def engine(tmp_path, monkeypatch, *, cloudy_year=None, header_failure=False, acquisition_failure=False):
    bundle = synthetic_bundle()
    forbidden = forbid_classification(monkeypatch)
    # One worker gives an exact partial-acquisition assertion; production permits six.
    if acquisition_failure:
        monkeypatch.setattr(r, 'ThreadPoolExecutor', lambda **kw: ThreadPoolExecutor(max_workers=1))
    log = []; headers = []
    def inspect(job, transport):
        item, asset, _ = job
        if header_failure:
            raise GateError('Synthetic header conflict')
        headers.append((item['id'], asset['asset']))
        return dict(item=item['id'], asset=asset['asset'])
    def acquire(scene, item, fields, transport, run, windows, contracts):
        assert len(fields) == len(headers) == 288
        day = item['id'].removeprefix('synthetic_'); year = int(day[:4])
        log.append(day)
        if acquisition_failure and day == dates()[1]:
            raise GateError('Synthetic partial scene failure')
        return {w['id']: observation(9 if year == cloudy_year else 4) for w in windows}
    budget = Budget(r.CEILING, 7200, tmp_path/'transfer.jsonl',
                    prior_reserved=r.RECORDED_BYTES+r.DOCUMENTATION_HOLD, prior_seconds=734)
    result = r.execute_coverage(bundle, tmp_path, budget, Mock(), inspect=inspect, acquire=acquire)
    forbidden.assert_not_called()
    assert result['classification_performed'] is False
    assert result['transitions_inferred'] is False and result['stage2_authorized'] is False
    files = [p.name for p in tmp_path.rglob('*') if p.is_file()]
    assert not any(any(word in n for word in ('annual', 'states', 'areas.json', 'examples', 'mndwi', 'transition')) for n in files)
    assert len(json.loads((tmp_path/'coverage.json').read_bytes())) == 72
    return result, log, headers


def test_complete_success_stops_coverage_only(tmp_path, monkeypatch):
    result, log, headers = engine(tmp_path, monkeypatch)
    assert result['status'] == 'COVERAGE_PASSED_AWAITING_OWNER_REVIEW'
    assert len(log) == 48 and len(headers) == 288
    assert [int(log[n][:4]) for n in range(0, 48, 8)] == list(r.YEAR_ORDER)
    rows = json.loads((tmp_path/'coverage.json').read_bytes())
    assert all(row['support_gate_pass'] and row['status'] == 'measured' for row in rows)
    assert all(len(row['provenance']) == 8 and len(row['complete_dates']) == 8 for row in rows)
    with np.load(tmp_path/'coverage_arrays.npz') as archive:
        assert len([k for k in archive if k.endswith('_clear')]) == 48*6*2
        assert all(archive[k].dtype == bool for k in archive if k.endswith('_clear'))


@pytest.mark.parametrize('failed_year,expected_count', [(2022, 8), (2024, 24)])
def test_first_failed_year_prevents_later_pixels(tmp_path, monkeypatch, failed_year, expected_count):
    result, log, _ = engine(tmp_path, monkeypatch, cloudy_year=failed_year)
    assert result['status'] == 'STOP_TEMPORAL_SUPPORT'
    assert len(log) == expected_count and len(result['failed_rows']) == 12
    assert set(int(d[:4]) for d in log) == set(r.YEAR_ORDER[:expected_count//8])
    rows = json.loads((tmp_path/'coverage.json').read_bytes())
    unmeasured = [row for row in rows if row['status'] != 'measured']
    assert all(row['supported_cells'] is None and row['acquired_dates'] == 0 for row in unmeasured)


def test_header_failure_prevents_every_pixel(tmp_path, monkeypatch):
    result, log, _ = engine(tmp_path, monkeypatch, header_failure=True)
    assert result['status'] == 'STOP_EXECUTION_GATE' and not log
    assert result['acquired_complete_dates'] == []


def test_partial_acquisitions_preserved_honestly(tmp_path, monkeypatch):
    result, log, _ = engine(tmp_path, monkeypatch, acquisition_failure=True)
    assert result['status'] == 'STOP_EXECUTION_GATE'
    assert result['acquired_complete_dates'] == [dates()[0]]
    assert all(d.startswith('2022') for d in log)
    rows = json.loads((tmp_path/'coverage.json').read_bytes())
    partial = [row for row in rows if row['year'] == 2022]
    assert all(row['status'] == 'partially_acquired' and row['acquired_dates'] == 1
               and row['supported_cells'] is None and row['support_gate_pass'] is None for row in partial)
    with np.load(tmp_path/'coverage_arrays.npz') as archive:
        assert len([k for k in archive if k.endswith('_clear')]) == 12


@pytest.mark.parametrize('ds,expected', [
    (['2022-06-01', '2022-07-01', '2022-07-31'], False),  # only two months
    (['2022-06-03', '2022-07-01', '2022-08-01'], False),  # 59 days
    (['2022-06-02', '2022-07-01', '2022-08-01'], True),   # 60 days
    (['2022-06-30', '2022-07-01', '2022-09-01'], False), # only two spaced dates
    (['2022-06-21', '2022-07-01', '2022-09-01'], True),  # 10-day boundary
    (['2022-06-22', '2022-07-01', '2022-09-01'], False), # 9-day separation
    (['2022-06-01', '2022-09-01'], False),
])
def test_temporal_boundaries(ds, expected):
    assert c.temporal_support(ds, np.ones((len(ds), 1), bool))['support'][0] == expected


def test_temporal_support_matches_frozen_synthetic_rules():
    # Every possible clear-date combination for all 48 frozen dates, metadata only.
    acquisitions = json.loads((r.OUT/'acquisitions.json').read_bytes())
    for year in range(2020, 2026):
        ds = [a['date_utc'] for a in acquisitions['acquisitions'] if a['year'] == year]
        clear = np.array([[(mask >> i) & 1 for mask in range(256)] for i in range(8)], bool)
        previous, _ = old_rules.season_state(ds, clear, np.full(clear.shape, -1, dtype=np.int8))
        np.testing.assert_array_equal(c.temporal_support(ds, clear)['support'], previous)


@pytest.mark.parametrize('buffer', [60, 120])
def test_quality_buffers_and_required_band_validity(buffer):
    a = observation(); assert c.clear_mask(a, buffer).all()
    a['B03'][8, 8] = np.nan; a['B11'][8, 9] = np.nan
    a['SCL'][30, 30] = 9
    actual = c.clear_mask(a, buffer)
    assert not actual[0, 0] and not actual[0, 1]
    radius = buffer // 20
    assert not actual[22, 22+radius] and actual[22, 23+radius]
    expected, _ = old_rules.date_states(a['B03'], a['B11'], a['SCL'], buffer_m=buffer)
    np.testing.assert_array_equal(actual, expected[8:-8, 8:-8])


@pytest.mark.parametrize('code', range(12))
def test_all_scl_codes(code):
    assert c.clear_mask(observation(code), 60).all() == (code in (4, 5, 6))


def test_zero_mask_and_all_four_native_contributors():
    dn = np.full((132, 132), 1000, dtype=np.uint16); dn[16, 16] = 0
    rho = old_rules.mean_2x2(old_rules.reflectance(dn, -1000))
    a = observation(); a['B03'] = rho
    assert not c.clear_mask(a, 60)[0, 0]
    assert c.clear_mask(a, 60)[1:, 1:].all()  # zero calibrated reflectance remains finite/clear


@pytest.mark.parametrize('n,passed', [(1999, False), (2000, True)])
def test_fixed_denominator_coverage_boundary(n, passed):
    clear = np.zeros((8, 50, 50), bool); clear.reshape(8, -1)[:, :n] = True
    row, _ = c.coverage_row('C1', 2022, dates(), clear, 60, np.full((50, 50), 400.))
    assert row['support_gate_pass'] is passed and row['supported_cells'] == n


@pytest.mark.parametrize('invalid', ['duplicate', 'unsorted', 'other_season', 'year', 'dtype', 'empty'])
def test_invalid_temporal_input(invalid):
    ds = dates(); clear = np.ones((8, 1), bool)
    if invalid == 'duplicate': ds[1] = ds[0]
    if invalid == 'unsorted': ds.reverse()
    if invalid == 'other_season': ds[0] = '2022-05-01'
    if invalid == 'year': ds[-1] = '2023-09-20'
    if invalid == 'dtype': clear = clear.astype(int)
    if invalid == 'empty': ds = []; clear = clear[:0]
    with pytest.raises(GateError): c.temporal_support(ds, clear)


def authority_accounting():
    return dict(recorded_cumulative_debit_bytes=r.RECORDED_BYTES,
                documentation_hold_bytes=r.DOCUMENTATION_HOLD, additional_recorded_charges_bytes=0,
                additional_acquisition_seconds=0, effective_prior_reserved_bytes=r.RECORDED_BYTES+r.DOCUMENTATION_HOLD,
                effective_prior_seconds=734)


@pytest.mark.parametrize('delta', [-r.DOCUMENTATION_HOLD, r.DOCUMENTATION_HOLD, -1, 1])
def test_documentation_hold_exactly_once(delta):
    a = authority_accounting(); a['effective_prior_reserved_bytes'] += delta
    with pytest.raises(GateError): r.accounting(a)


def test_accounting_cap_deadline_cancellation_and_retry(tmp_path):
    a = authority_accounting(); carry, seconds = r.accounting(a)
    assert carry == 881356288 and seconds == 734
    now = [0.]; b = Budget(r.CEILING, 7200, tmp_path/'log', clock=lambda: now[0], prior_reserved=carry, prior_seconds=seconds)
    assert b.ceiling-b.reserved == 2339869184
    session = Mock(); session.request.side_effect = [response(503, **{'Retry-After':'0'}), response()]
    t = Transport(b, session, sleep=lambda _: None)
    t.request('GET', 'https://example.invalid', length=4, expected=(0, 4, 10, 'v1'))
    assert b.reserved == carry + 2*(65536+4)
    b.reserve(b.ceiling-b.reserved)
    with pytest.raises(GateError): t.request('GET', 'https://example.invalid', length=1)
    assert session.request.call_count == 2
    now[0] = 6466
    with pytest.raises(GateError): b.check()
    b.stop('cancelled')
    with pytest.raises(GateError): t.request('HEAD', 'https://example.invalid')
    assert session.request.call_count == 2


def test_real_bundle_offline_metadata_contracts():
    bundle = r.load_bundle(r.ROOT, r.OUT)
    assert len(bundle['contracts']) == 288
    assert len(bundle['scenes']) == 48
    assert {a['spacecraft'] for a in bundle['acquisitions']['acquisitions']} == {'Sentinel-2A', 'Sentinel-2B', 'Sentinel-2C'}


def test_no_acquisition_authority_no_network_or_run(tmp_path, monkeypatch):
    transport = Mock(); monkeypatch.setattr(r, 'Transport', transport)
    with pytest.raises(GateError, match='absent'):
        r.run(tmp_path, tmp_path, approval_sha='a'*64, verification_sha='b'*64)
    transport.assert_not_called(); assert not (tmp_path/r.RUN_NAME).exists()


def authority_fixture(tmp_path):
    (tmp_path/'scripts').mkdir(); (tmp_path/'tests').mkdir()
    for name in [r.METHOD, 'pyproject.toml', 'requirements.lock.txt', 'scripts/runner.py', 'tests/test_coastal_stage1.py']:
        p = tmp_path/name; p.parent.mkdir(exist_ok=True); p.write_text('synthetic')
    a = dict(authority_accounting(), schema='coastal_jun_sep_execution_approval_v1', stage=1,
             execution_approved=True, acquisition_approved=True, protocol_sha256=r.PROTOCOL_SHA,
             output_directory=r.RUN_NAME, total_acquisition_ceiling_bytes=r.CEILING,
             acquisition_wall_seconds=7200, minimum_free_disk_bytes=r.MIN_DISK,
             no_classification=True, no_stage2=True, owner_wording='SYNTHETIC TEST ONLY')
    reconciliation = dict(authority_accounting(), protocol_sha256=r.PROTOCOL_SHA)
    r.write_new(tmp_path/'stage1_accounting_reconciliation.json', reconciliation)
    a['accounting_reconciliation_sha256'] = r.digest(tmp_path/'stage1_accounting_reconciliation.json')
    r.write_new(tmp_path/'stage1_execution_approval.json', a)
    cases = ''.join(f'<testcase classname="tests.test_coastal_stage1" name="synthetic_{i}"/>' for i in range(327))
    (tmp_path/'tests.xml').write_text('<testsuites><testsuite tests="327" failures="0" errors="0" skipped="0">'+cases+'</testsuite></testsuites>')
    r.write_new(tmp_path/'review.json', dict(all_pages_reviewed=True, docx_sha256=r.digest(tmp_path/r.METHOD)))
    v = dict(schema='coastal_jun_sep_execution_verification_v1', stage=1, protocol_sha256=r.PROTOCOL_SHA,
             execution_approval_sha256=r.digest(tmp_path/'stage1_execution_approval.json'),
             tests_xml='tests.xml', tests_xml_sha256=r.digest(tmp_path/'tests.xml'), passed=327,
             executing_file_sha256={str(p.relative_to(tmp_path)).replace('\\','/'):r.digest(p)
                 for p in tmp_path.rglob('*') if p.is_file() and p.suffix in ('.py','.docx','.toml','.txt')},
             methodology_review='review.json', methodology_review_sha256=r.digest(tmp_path/'review.json'), commit='synthetic-clean')
    r.write_new(tmp_path/'stage1_execution_verification.json', v)
    return a, v


@pytest.mark.parametrize('case', ['pass', 'implementation_only', 'old_protocol', 'double_hold', 'reconciliation',
    'failed_tests', 'skipped_tests', 'missing_new_tests', 'stale_code', 'methodology', 'commit', 'disk', 'existing_run', 'approval_hash'])
def test_fresh_authority_and_verification_gates(tmp_path, case):
    a, v = authority_fixture(tmp_path)
    if case == 'implementation_only': a['execution_approved'] = False
    if case == 'old_protocol': a['protocol_sha256'] = r.native.PROTOCOL_SHA
    if case == 'double_hold': a['effective_prior_reserved_bytes'] += r.DOCUMENTATION_HOLD
    if case == 'reconciliation': a['accounting_reconciliation_sha256'] = '0'*64
    if case in ('failed_tests', 'skipped_tests', 'missing_new_tests'):
        text = (tmp_path/'tests.xml').read_text()
        if case == 'failed_tests': text = text.replace('failures="0"', 'failures="1"')
        elif case == 'skipped_tests': text = text.replace('skipped="0"', 'skipped="1"')
        else: text = text.replace('tests.test_coastal_stage1', 'tests.old_pilot')
        (tmp_path/'tests.xml').write_text(text); v['tests_xml_sha256'] = r.digest(tmp_path/'tests.xml')
    if case == 'stale_code': (tmp_path/'scripts/runner.py').write_text('changed')
    if case == 'methodology': (tmp_path/r.METHOD).write_text('changed')
    if case == 'commit': v['commit'] = 'old'
    if case == 'existing_run':
        (tmp_path/r.RUN_NAME).mkdir(); (tmp_path/r.RUN_NAME/'sentinel').write_text('preserve')
    (tmp_path/'stage1_execution_approval.json').write_text(json.dumps(a))
    approval_sha = r.digest(tmp_path/'stage1_execution_approval.json')
    v['execution_approval_sha256'] = approval_sha
    (tmp_path/'stage1_execution_verification.json').write_text(json.dumps(v))
    kw = dict(free_bytes=0 if case == 'disk' else r.MIN_DISK, commit_fn=lambda _: 'synthetic-clean')
    call = lambda: r.verify_authority(tmp_path, tmp_path, '0'*64 if case == 'approval_hash' else approval_sha,
                                      r.digest(tmp_path/'stage1_execution_verification.json'), **kw)
    if case == 'pass':
        assert call()[2] == (881356288, 734)
    else:
        with pytest.raises(GateError): call()
    if case == 'existing_run': assert (tmp_path/r.RUN_NAME/'sentinel').read_text() == 'preserve'
