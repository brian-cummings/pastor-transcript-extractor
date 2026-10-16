"""Authorized single-attempt V4 execution; Brian runs the CLI, never preparation.

Frozen packet/measurement modules are unchanged. This authorization is a sidecar,
not an acceptance of preliminary source notes or any future source-review witness.
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile

from pastor_transcript_extractor import evidence_supply_boundary_v4 as panel
from pastor_transcript_extractor.config import build_paths

FROZEN_FINGERPRINT = '3deba35907971549e9693c170e53ace6c8e3444b447a1715c5fd28501c7a893c'
AUTHORIZATION = panel.HERE / 'execution-authorization-v4.json'
MAX_ATTEMPTS = 37
RESERVED_TOKENS = 64000
PRICE = Decimal('0.000000042')
MAX_USD = Decimal('0.099456')


def authorization(packet, base_dir=None):
    panel.validate_packet(packet, reproduce=True)
    decision = panel.proposal.load_sealed(AUTHORIZATION)
    if (decision.get('version') != 'boundary-v4-semantic-execution-authorization'
            or packet['content_fingerprint'] != FROZEN_FINGERPRINT
            or decision.get('input_fingerprint') != FROZEN_FINGERPRINT
            or decision.get('input_file_sha256') != panel.old.frozen.v1.file_hash(panel.INPUT)
            or decision.get('runner_file_sha256') != panel.old.frozen.v1.file_hash(Path(__file__))
            or decision.get('status') != 'EXECUTION_AUTHORIZED'
            or decision.get('decision_owner') != 'Brian'
            or decision.get('executor') != 'Brian'
            or decision.get('runtime_directory') != str(panel.output_directory(base_dir))
            or decision.get('maximum_attempts') != MAX_ATTEMPTS
            or decision.get('maximum_input_tokens') != MAX_ATTEMPTS * RESERVED_TOKENS
            or Decimal(decision['maximum_list_price_usd']) != MAX_USD
            or decision.get('automatic_retries') != 0
            or decision.get('model') != packet['model']
            or decision.get('case_geometries') != 24
            or decision.get('selected_option_probability_gate') != .80
            or decision.get('long_context') is not False
            or decision.get('provider_calls_authorized') is not True
            or decision.get('semantic_execution_authorized') is not True
            or decision.get('source_oracle_accepted') is not False
            or decision.get('future_review_witness_accepted') is not False
            or decision.get('downstream_authorized') is not False):
        raise ValueError('Missing or mismatched fingerprint-bound V4 execution authorization')
    return decision


def seal(value):
    return panel.old.seal(value)


def safe_child(directory, name):
    directory = Path(directory).resolve()
    path = directory / name
    if path.is_symlink() or not path.resolve().is_relative_to(directory):
        raise ValueError('Runtime path escapes the V4 directory')
    return path


def atomic_json(path, value):
    """Persist reservation/bytes before sending/parsing; replace only complete files."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(handle, 'w') as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def execution_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    lock = safe_child(directory, 'execution.lock')
    import fcntl
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('V4 execution already running; do not start another process') from error
        yield
    finally:
        os.close(descriptor)


def read_cache(packet, directory, decision):
    """Read-only validation/recovery: valid attempted receipt is local replay only."""
    path = safe_child(directory, 'request-ledger.json')
    ledger = dict(version='bounded-boundary-execution-v4', input_fingerprint=FROZEN_FINGERPRINT,
                  approval_key=FROZEN_FINGERPRINT, authorization_fingerprint=decision['content_fingerprint'],
                  maximum_attempts=MAX_ATTEMPTS, attempts=[])
    if path.exists():
        ledger = json.loads(path.read_text())
        panel.old.frozen._verify_seal(ledger)
    if any(ledger.get(k) != v for k, v in dict(version='bounded-boundary-execution-v4', input_fingerprint=FROZEN_FINGERPRINT,
           approval_key=FROZEN_FINGERPRINT, authorization_fingerprint=decision['content_fingerprint'], maximum_attempts=MAX_ATTEMPTS).items()):
        raise ValueError('V4 ledger authorization/packet identity changed')
    keys = [r['request_key'] for r in packet['requests']]
    attempted = [a['request_key'] for a in ledger['attempts']]
    if len(attempted) > MAX_ATTEMPTS or attempted != keys[:len(attempted)]:
        raise ValueError('Duplicate, unknown or out-of-order charged attempts')
    if len(attempted) != MAX_ATTEMPTS and any(safe_child(directory, name).exists() for name in ('results-v4.json', 'results-v4.md')):
        raise ValueError('Completed results without complete charged ledger require a recovery decision')
    receipt_dir = safe_child(directory, 'receipts')
    if receipt_dir.exists() and {p.stem for p in receipt_dir.glob('*.json')} - set(keys):
        raise ValueError('Foreign/V3 receipts cannot be reused')
    bykey = {a['request_key']: a for a in ledger['attempts']}
    reused = {}
    for request in packet['requests']:
        key = request['request_key']
        path = safe_child(receipt_dir, key + '.json')
        if key not in bykey:
            if path.exists():
                raise ValueError('Orphan receipt without charged attempt')
            continue
        attempt = bykey[key]
        if (type(attempt.get('reserved_input_tokens')) is not int or attempt['reserved_input_tokens'] != RESERVED_TOKENS
                or Decimal(attempt['reserved_usd']) != PRICE * RESERVED_TOKENS):
            raise ValueError('Charged reservation changed')
        if attempt.get('status') not in {'attempted', 'validated'} or not path.exists():
            raise ValueError('Failed/lost charged reply requires a separate recovery decision; no retry')
        receipt = json.loads(path.read_text())
        panel.old.frozen._verify_seal(receipt)
        if receipt.get('request_key') != key or receipt.get('input_fingerprint') != FROZEN_FINGERPRINT:
            raise ValueError('Receipt belongs to a different state/packet')
        try:
            raw = panel.old.frozen.validate_response(receipt['response'], request)
        except (ValueError, KeyError) as error:
            raise ValueError('Invalid charged receipt requires a separate recovery decision; no retry') from error
        if attempt['status'] == 'validated' and (attempt.get('usage') != raw['usage'] or attempt.get('receipt_fingerprint') != receipt['fingerprint']):
            raise ValueError('Validated ledger/receipt accounting differs')
        attempt.update(status='validated', usage=raw['usage'], receipt_fingerprint=receipt['fingerprint'])
        reused[key] = receipt
    if sum(Decimal(a['reserved_usd']) for a in ledger['attempts']) > MAX_USD or sum(a['reserved_input_tokens'] for a in ledger['attempts']) > MAX_ATTEMPTS * RESERVED_TOKENS:
        raise ValueError('Cumulative reservation ceiling exceeded')
    return ledger, reused


def preflight(packet, base_dir=None):
    decision = authorization(packet, base_dir)
    original = json.loads((panel.old.frozen.HERE / 'input-v2.json').read_text())
    panel.old.frozen.live_check(original, build_paths(base_dir).root)
    directory = panel.output_directory(base_dir)
    ledger, reused = read_cache(packet, directory, decision)
    return decision, ledger, reused


def execute(packet, approval_key, base_dir=None, provider_factory=None, progress=print):
    if approval_key != FROZEN_FINGERPRINT:
        raise ValueError('Requires exact --approve-paid-packet fingerprint')
    decision, _, _ = preflight(packet, base_dir)
    directory = panel.output_directory(base_dir)
    with execution_lock(directory):
        if (safe_child(directory, 'acceptance-decision.json').exists()
                or (panel.HERE / 'acceptance-decision-v4.json').exists()):
            raise ValueError('V4 gate already closed; no execution')
        ledger, reused = read_cache(packet, directory, decision)
        ledger.pop('fingerprint', None)
        ledger_path = safe_child(directory, 'request-ledger.json')
        provider = None
        receipts = []
        try:
            for index, request in enumerate(packet['requests'], 1):
                key = request['request_key']
                progress(f'[{index}/{MAX_ATTEMPTS}] {request["case_id"]} {request["phase"]}: ' + ('cached' if key in reused else 'requesting'), flush=True)
                if key in reused:
                    receipt = reused[key]
                else:
                    if (len(ledger['attempts']) >= MAX_ATTEMPTS
                            or sum(a['reserved_input_tokens'] for a in ledger['attempts']) + RESERVED_TOKENS > MAX_ATTEMPTS * RESERVED_TOKENS
                            or sum(Decimal(a['reserved_usd']) for a in ledger['attempts']) + PRICE * RESERVED_TOKENS > MAX_USD):
                        raise ValueError('V4 cumulative attempt/token/price ceiling reached')
                    if provider is None:
                        provider = (provider_factory or panel.old.frozen.HTTPProvider)()
                    attempt = dict(request_key=key, status='attempted', reserved_input_tokens=RESERVED_TOKENS,
                                   reserved_usd=str(PRICE * RESERVED_TOKENS))
                    ledger['attempts'].append(attempt)
                    atomic_json(ledger_path, seal(ledger))
                    path = safe_child(safe_child(directory, 'receipts'), key + '.json')
                    try:
                        response = provider.assess(request)
                        receipt = seal(dict(input_fingerprint=FROZEN_FINGERPRINT, request_key=key, response=response))
                        atomic_json(path, receipt)
                        raw = panel.old.frozen.validate_response(response, request)
                    except Exception as error:
                        attempt.update(status='failed', failure_type=type(error).__name__)
                        atomic_json(ledger_path, seal(ledger))
                        raise ValueError('Charged request failed; raw bytes retained when available; no automatic retry. Separate recovery decision required.') from error
                    attempt.update(status='validated', usage=raw['usage'], receipt_fingerprint=receipt['fingerprint'])
                    atomic_json(ledger_path, seal(ledger))
                receipts.append(receipt)
                raw = panel.old.frozen.validate_response(receipt['response'], request)
                progress(f'[{index}/{MAX_ATTEMPTS}] validated; input_tokens={raw["usage"]["input_tokens"]}', flush=True)
        finally:
            if provider is not None:
                provider.close()
        atomic_json(ledger_path, seal(ledger))
        # No preliminary oracle, accepted witness or automatic semantic decision.
        result = panel.interpret_receipts(packet, receipts)
        usage = dict(attempts=len(ledger['attempts']), input_tokens=sum(a['usage']['input_tokens'] for a in ledger['attempts']),
                     output_tokens=sum(a['usage']['output_tokens'] for a in ledger['attempts']))
        result.update(status='EXECUTION_COMPLETE_pending_Codex_source_audit_and_Brian_decisions', usage=usage,
                      actual_list_price_usd=str(Decimal(usage['input_tokens']) * PRICE),
                      authorization_fingerprint=decision['content_fingerprint'],
                      ledger_file_sha256=panel.old.frozen.v1.file_hash(ledger_path),
                      source_review='No accepted receipt-bound review; preliminary source oracle not accepted.',
                      usable_evidence_items=None, cost_per_usable_item=None)
        result['content_fingerprint'] = panel.old.frozen.fp(result)
        atomic_json(safe_child(directory, 'results-v4.json'), result)
        write_markdown(safe_child(directory, 'results-v4.md'), result)
        return result


def write_markdown(path, result):
    lines = ['# V4 semantic boundary revalidation', '',
             '**Execution complete. Raw-semantic and containment decisions await Codex source audit and Brian.**', '',
             f'Requests: {result["usage"]["attempts"]}; input tokens: {result["usage"]["input_tokens"]}; output tokens: {result["usage"]["output_tokens"]}; list price: ${result["actual_list_price_usd"]}.', '',
             '| Case | Historical differences | Forward differences | Preliminary admission |', '| --- | ---: | ---: | --- |']
    for row in result['observations']:
        counts = [sum(len(c['differences']) for c in row['comparisons'] if c['scope'] == scope) for scope in ('historical_V3_geometry_diagnostic', 'proposed_forward_check')]
        lines.append(f'| {row["case_id"]} | {counts[0]} | {counts[1]} | No accepted receipt-bound source review |')
    lines += ['', 'All raw answers, distributions and gated decisions are preserved in results-v4.json. Review every positive field, historical/forward difference and unscored failure against supplied and full-source evidence.', '',
              'Pre-review quarantine is mandatory, not evidence of semantic failure or successful containment. No preliminary source oracle or future witness has been accepted. Codex prepares the receipt-bound source review and separate raw-semantic/containment recommendations. Brian decides.', '',
              'No contract/ranker changes, automatic attestation, discovery, collection, 790-item V2 audit, recurrence/rates, production use or pastor projection/comparison/scoring. No usable-item denominator or unit cost is established.', '']
    # Markdown is derived; JSON receipts and ledger are the durable source of truth.
    path.write_text('\n'.join(lines))
