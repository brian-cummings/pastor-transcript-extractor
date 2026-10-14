"""Read-only human acceptance record for the closed bounded G1 gate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / 'evaluation/g1-binding/feasibility-stage-gate-v2.json'


def is_closed() -> bool:
    # Fail closed even if an existing decision artifact becomes unreadable.
    return GATE.exists()


def show() -> None:
    gate = json.loads(GATE.read_text())
    payload = {k: v for k, v in gate.items() if k != 'content_fingerprint'}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    if gate.get('content_fingerprint') != digest or gate.get('status') != 'PASS' or gate.get('closed') is not True:
        raise ValueError('Invalid G1 stage-gate decision; no provider requests permitted')
    result_path = ROOT / gate['result_file']
    raw = result_path.read_bytes()
    result = json.loads(raw)
    result_digest = hashlib.sha256(json.dumps({k: v for k, v in result.items() if k != 'content_fingerprint'}, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    if (hashlib.sha256(raw).hexdigest() != gate['result_file_sha256']
            or result_digest != gate['result_fingerprint']
            or result.get('content_fingerprint') != result_digest
            or result.get('input_fingerprint') != gate['input_fingerprint']):
        raise ValueError('G1 accepted result integrity mismatch; no provider requests permitted')
    print('PASS: bounded G1 passage-level feasibility CLOSED by Brian; provider_requests=0')
    print('Accepted conservative withholding and residual/regression limitations; frozen oracle unchanged (198/209).')
    print('No G1 V3 or additional provider requests. Broader collection, projection/comparison, G4 and scoring remain held.')
    print(f'Decision: {GATE.with_suffix(".md")} and {GATE}')
