"""One explicitly approved restart; immutable evidence and cumulative limits."""

import hashlib
import json
import xml.etree.ElementTree as ET

from scripts.coastal_transport import GateError

ATTEMPT='run_attempt_02'
RECORDS='restart_attempt_02'
APPROVAL_SHA='333958643a727a9b458b9a1d90c4093339c73aec49163608b67b82889340e813'
PRIOR_BYTES=272554958
PRIOR_SECONDS=60


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def contract(out,attempt,protocol_sha):
    if attempt!=ATTEMPT:raise GateError('Unapproved restart attempt')
    directory=out/RECORDS
    path=directory/'approval.json'
    if digest(path)!=APPROVAL_SHA:raise GateError('Restart approval hash mismatch')
    a=json.loads(path.read_bytes())
    expected=dict(approved=True,attempt=ATTEMPT,protocol_sha256=protocol_sha,
        total_acquisition_ceiling_bytes=3*1024**3,minimum_free_disk_bytes=7*1024**3,
        acquisition_wall_seconds=7200,prior_reserved_bytes=PRIOR_BYTES,prior_elapsed_seconds=PRIOR_SECONDS,
        remaining_transfer_bytes=3*1024**3-PRIOR_BYTES,remaining_acquisition_seconds=7200-PRIOR_SECONDS,
        no_push=True,no_scale_up=True,no_phase_c=True)
    if any(a.get(k)!=v for k,v in expected.items()):raise GateError('Restart approval limits mismatch')
    if sum(a['prior_charges'].values())!=PRIOR_BYTES:raise GateError('Prior transfer debit mismatch')
    prior=directory/'prior_evidence.json'
    if digest(prior)!=a['prior_evidence_sha256']:raise GateError('Prior evidence registry changed')
    for name,sha in json.loads(prior.read_bytes())['files_sha256'].items():
        if digest(out/name)!=sha:raise GateError('Prior pilot evidence changed: '+name)
    if (out/ATTEMPT).exists():raise GateError('Restart attempt already exists; no resume/overwrite')
    return a


def verify_tests(directory,verification):
    if verification.get('restart_approval_sha256')!=APPROVAL_SHA:
        raise GateError('Tests not bound to restart approval')
    path=directory/'tests.xml'
    if digest(path)!=verification.get('tests_xml_sha256'):raise GateError('Restart test report changed')
    suites=list(ET.parse(path).getroot().iter('testsuite'))
    totals={k:sum(int(s.get(k,'0')) for s in suites) for k in ('tests','failures','errors','skipped')}
    if (totals['tests']<305 or any(totals[k] for k in ('failures','errors','skipped'))
            or totals['tests']!=verification.get('passed')):
        raise GateError('Restart full-suite report incomplete/failed')
