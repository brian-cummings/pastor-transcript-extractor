"""Read-only retirement record and Git-backed frozen snapshot verification."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess

from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT/'docs/review-proposals/minute-evidence-handoff-v1'
CLOSURE = HERE/'probe-supersession-v1.json'
OLD = ROOT/'docs/review-proposals/context-extraction-probe-v1'
FROZEN_COMMIT = '3c466bd'
INPUT_FINGERPRINT = '54ada40ca8926a6bae0a89cd41c091fcc0ce9e31c3c4cc27969feee892e7a76a'


def read(path):
    value = json.loads(Path(path).read_text())
    if seal(value) != value:
        raise ValueError('Invalid retirement/archive seal')
    return value


def closure():
    value = read(CLOSURE)
    if (value['status'] != 'SUPERSEDED_UNEXECUTED' or value['input_fingerprint'] != INPUT_FINGERPRINT
            or value['execution_allowed'] is not False or value['prepare_allowed'] is not False
            or value['frozen_preparation_commit'] != FROZEN_COMMIT):
        raise ValueError('Probe retirement decision changed')
    authority = OLD/'execution-authorization-v1.json'
    if hashlib.sha256(authority.read_bytes()).hexdigest() != value['historical_authorization_sha256']:
        raise ValueError('Historical execution authorization changed')
    return value


def archived_bytes(path):
    relative = Path(path)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Invalid frozen Git path')
    try:
        return subprocess.run(['git','show',f'{FROZEN_COMMIT}:{relative.as_posix()}'],cwd=ROOT,
                              check=True,capture_output=True).stdout
    except subprocess.CalledProcessError as error:
        raise ValueError('Frozen preparation commit unavailable; do not execute the retired probe') from error


def verify(base_dir=None):
    decision = closure()
    manifest = read(OLD/'input-manifest-v1.json')
    input_path = Path(manifest['input_path'])
    if hashlib.sha256(input_path.read_bytes()).hexdigest() != manifest['input_sha256']:
        raise ValueError('Historical prepared input changed')
    packet = read(input_path)
    if packet['content_fingerprint'] != INPUT_FINGERPRINT:
        raise ValueError('Historical input fingerprint changed')
    preparation = read(OLD/'packet-v1.json')
    files = {**packet['pins'], **preparation['files']}
    for name, expected in files.items():
        if hashlib.sha256(archived_bytes(name)).hexdigest() != expected:
            raise ValueError('Frozen preparation bytes differ: '+name)
    for key in ('panel','oracle'):
        artifact = read(packet[key+'_path'])
        if artifact['content_fingerprint'] != packet[key+'_fingerprint']:
            raise ValueError('Historical panel/oracle binding changed')
    run_dir = build_paths(base_dir).evaluation/'context-extraction-probe-v1'/INPUT_FINGERPRINT
    if list(run_dir.glob('*.attempt.json')) or list(run_dir.glob('*.receipt.json')) or (run_dir/'results-v1.json').exists():
        raise ValueError('Unexpected execution artifacts; retain and review separately')
    return dict(status=decision['status'],input_fingerprint=INPUT_FINGERPRINT,
                verified_archived_files=len(files),frozen_commit=FROZEN_COMMIT,
                provider_requests=0,execution_allowed=False)
