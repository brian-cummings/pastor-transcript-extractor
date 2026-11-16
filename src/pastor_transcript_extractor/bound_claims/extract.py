"""Step D: one bound-claim request per stratified block for one producer.

Both producers share one prompt, schema and caps; only the model differs; reasoning
is off for both (policies in `deepinfra_requests`). Each block has its own receipt
store, so the shared one-request executor, streaming whitespace guard and receipts
are reused unchanged. A failed block is recorded, never semantically retried.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping

from pastor_transcript_extractor import deepinfra_requests as provider
from pastor_transcript_extractor import deepinfra_streaming as streaming
from pastor_transcript_extractor import evidence_requests as requests
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.context_extraction_validation import strict_json

from . import contract
from .common import REPOSITORY, file_sha256, read_json, write_json
from .ledger import PilotLedger, list_price_usd

VERSION = 'bound-claim-extraction-v1'
PRODUCERS = {
    'pro': (requests.DEEPINFRA_BOUND_CLAIM_VERSIONS[0], 'extract_pro'),
    'flash': (requests.DEEPINFRA_BOUND_CLAIM_VERSIONS[1], 'extract_flash'),
}
TRANSPORT_FAILURE_RATE = Decimal('0.05')
SCHEMA_FAILURE_RATE = Decimal('0.10')


class StopRule(ValueError):
    pass


def build_request(block: Mapping[str, Any], strata_sha: str, producer: str) -> requests.RequestSpec:
    version, _ = PRODUCERS[producer]
    policy = provider.policy_for(version)
    body = dict(
        model=policy['model'],
        messages=[dict(role='system', content=contract.SYSTEM_PROMPT),
                  dict(role='user', content=contract.user_message(block['text'], block['preceding_text'], block['following_text']))],
        max_tokens=policy['output_cap'],
        response_format=dict(type='json_schema', json_schema=dict(name='bound_claims', strict=True, schema=contract.RESPONSE_SCHEMA)),
        temperature=0, top_p=1, stream=False, n=1, reasoning_effort=policy['reasoning_effort'])
    spec = requests.RequestSpec('source_reading', body,
        dict(coordinate=block['coordinate'], strata_sha256=strata_sha, contract=contract.VERSION, stratum=block['stratum']),
        namespace=version, version=version, runtime_identity=dict(policy))
    return provider.streaming_request(spec)


def git_state() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(['git', *args], cwd=REPOSITORY, check=True, capture_output=True, text=True).stdout.strip()
    return dict(commit=git('rev-parse', 'HEAD'), src_tree=git('rev-parse', 'HEAD:src'), dirty=bool(git('status', '--porcelain', '--', 'src', 'pyproject.toml')))


def published_prices(metadata: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    """Live public DeepInfra prices recorded at freeze; reservations assume the policy's full list prices."""
    result = {}
    for name, (version, _) in PRODUCERS.items():
        policy = provider.policy_for(version)
        published = dict(metadata(policy['model']))
        for field, key in (('input_usd_per_million', 'input_cents_per_token'), ('output_usd_per_million', 'output_cents_per_token')):
            if Decimal(published[key]) * 10000 != Decimal(policy[field]):
                raise ValueError(f"Published {name} {field} {Decimal(published[key]) * 10000} differs from the reserved list price {policy[field]}")
        result[name] = published
    return result


def freeze_plan(pilot: Path, slice_sha: str, strata_sha: str, ledger: PilotLedger,
                state: Callable[[], dict[str, Any]] = git_state,
                metadata: Callable[[str], Mapping[str, Any]] = provider.public_model_metadata) -> dict[str, Any]:
    """Freeze the implementation before the first paid extraction and re-verify it on every later paid step."""
    current = state()
    if current['dirty']:
        raise ValueError('Uncommitted source changes: the implementation must be committed and frozen before extraction')
    path = pilot / 'plan.json'
    if path.exists():
        plan = read_json(path)
        if seal(plan) != plan:
            raise ValueError('plan.json seal differs')
        if (plan['slice_sha256'], plan['strata_sha256'], plan['implementation']['src_tree']) != (slice_sha, strata_sha, current['src_tree']):
            raise ValueError('Frozen plan differs from the slice, strata or implementation; the pilot allows no variant')
        return plan
    prices = published_prices(metadata)
    plan = seal(dict(
        version='bound-claim-pilot-plan-v1', slice_sha256=slice_sha, strata_sha256=strata_sha, prompt_version=contract.VERSION,
        implementation=current, ceiling=dict(usd=str(ledger.ceiling_usd), attempts=ledger.ceiling_attempts),
        policies={name: provider.policy_for(version) for name, (version, _) in PRODUCERS.items()},
        jev=dict(model='jev-1.13.0', input_usd_per_million='0.042'), published_deepinfra_metadata=prices,
        retries='none; one attempt per block, no semantic retry', stop_rules=dict(
            transport_failure_rate=str(TRANSPORT_FAILURE_RATE), pro_schema_failure_rate=str(SCHEMA_FAILURE_RATE))))
    write_json(path, plan)
    return plan


def decode(response: Mapping[str, Any], block: Mapping[str, Any]) -> dict[str, Any]:
    claims = contract.validate_claims(strict_json(response['output']))
    accepted, failures = [], []
    for claim in claims:
        anchor = contract.check_anchor(claim, block['text'], block['preceding_text'], block['following_text'])
        if anchor['status'] != 'ok':
            failures.append(dict(claim=claim, anchor=anchor))
            continue
        accepted.append(dict(claim=claim, anchor=anchor, fingerprint=contract.claim_fingerprint(block['video_id'], block['block_id'], claim)))
    return dict(claims=accepted, anchor_failures=failures)


def _physical_usage(store: requests.ReceiptStore) -> dict[str, Any]:
    """Tokens over every physical attempt; one without usage (a cancelled stream) is counted apart and charged in full."""
    input_tokens = output_tokens = unmetered = 0
    seen = False
    for attempt in store.attempts():
        path = store.root / 'receipts' / (attempt['request_fingerprint'] + '.json')
        receipt = read_json(path) if path.exists() else None
        for record in streaming.usage_records(store, attempt, receipt) or []:
            seen = True
            usage = record.get('usage') or {}
            if type(usage.get('prompt_tokens')) is int and type(usage.get('completion_tokens')) is int:
                input_tokens += usage['prompt_tokens']
                output_tokens += usage['completion_tokens']
            else:
                unmetered += 1
    return dict(input_tokens=input_tokens, output_tokens=output_tokens, unmetered_attempts=unmetered) if seen else {}


def _classify(error: Exception) -> str:
    return 'schema_failure' if isinstance(error, contract.SchemaError) else 'transport_failure'


def run(strata_path: Path, producer: str, ledger: PilotLedger, *, check_only: bool = False,
        transport: Callable | None = None, state: Callable[[], dict[str, Any]] = git_state,
        metadata: Callable[[str], Mapping[str, Any]] = provider.public_model_metadata) -> dict[str, Any]:
    if producer not in PRODUCERS:
        raise ValueError('Producer must be pro or flash')
    strata_path = Path(strata_path).resolve()
    pilot = strata_path.parent
    strata = read_json(strata_path)
    version, step = PRODUCERS[producer]
    policy = provider.policy_for(version)
    blocks = strata['blocks']
    specs = {block['coordinate']: build_request(block, file_sha256(strata_path), producer) for block in blocks}
    reservation = provider.reserved_usd(next(iter(specs.values())).version)
    pending = [b for b in blocks if not (pilot / 'extract' / producer / b['coordinate'] / 'receipts' / (specs[b['coordinate']].fingerprint + '.json')).exists()
               and ledger.entry_status(f"{step}/{b['coordinate']}") is None]
    worst = reservation * len(pending)
    plan = dict(version=VERSION, producer=producer, model=policy['model'], reasoning_effort=policy['reasoning_effort'],
                blocks=len(blocks), already_received=len(blocks) - len(pending), requests_to_send=len(pending),
                per_request_reserved_usd=str(reservation), worst_case_reserved_usd=str(worst), check_only=check_only,
                remaining_ledger_usd=str(ledger.remaining()[0]))
    if check_only:
        return plan
    if pending:
        ledger.require_step(step, worst, len(pending))
    frozen = freeze_plan(pilot, strata['slice_sha256'], file_sha256(strata_path), ledger, state, metadata)
    send = transport or provider.transport
    rows, counts = [], dict(transport_failure=0, schema_failure=0)
    stopped = None
    for block in blocks:
        coordinate, spec = block['coordinate'], specs[block['coordinate']]
        store = requests.ReceiptStore(pilot / 'extract' / producer / coordinate)
        entry = f'{step}/{coordinate}'
        receipt_path = store.root / 'receipts' / (spec.fingerprint + '.json')
        row = dict(coordinate=coordinate, stratum=block['stratum'], status='pending', claims=[], anchor_failures=[])
        if not receipt_path.exists() and ledger.entry_status(entry) is not None:
            row.update(status='lost_attempt', error='A prior attempt has no receipt; uncertain spend, never retried')
        else:
            if not receipt_path.exists():
                ledger.reserve(entry, step, reservation, coordinate=coordinate, version=version)
            response = failure = None
            try:
                response = requests.execute(spec, provider.OneRequestLedger(str(reservation), spec.version), store, send)
            except (ValueError, KeyError, TypeError, OSError) as error:
                failure = error
            if ledger.entry_status(entry) == 'reserved':
                usage = _physical_usage(store)
                ledger.resolve(entry, actual_usd=(list_price_usd(usage['input_tokens'], usage['output_tokens'],
                    policy['input_usd_per_million'], policy['output_usd_per_million'])
                    + usage['unmetered_attempts'] * provider.reserved_usd(version) if usage else None), **usage)
            if failure is None:
                try:
                    row.update(status='ok', usage=response['usage'], **decode(response, block))
                except (ValueError, KeyError, TypeError) as error:
                    failure = contract.SchemaError(str(error))
            if failure is not None:
                row.update(status=_classify(failure), error=str(failure)[:500])
        rows.append(row)
        for status in ('transport_failure', 'schema_failure'):
            counts[status] = sum(r['status'] == status for r in rows)
        if counts['transport_failure'] > TRANSPORT_FAILURE_RATE * len(blocks):
            stopped = f"stop rule: transport failures {counts['transport_failure']} exceed 5% of {len(blocks)} requests"
        elif producer == 'pro' and counts['schema_failure'] > SCHEMA_FAILURE_RATE * len(blocks):
            stopped = f"stop rule: schema failures {counts['schema_failure']} exceed 10% of {len(blocks)} V4 Pro outputs"
        if stopped:
            break
    summary = dict(blocks=len(blocks), attempted=len(rows), ok=sum(r['status'] == 'ok' for r in rows),
                   transport_failures=counts['transport_failure'], schema_failures=counts['schema_failure'],
                   lost_attempts=sum(r['status'] == 'lost_attempt' for r in rows),
                   claims=sum(len(r['claims']) for r in rows), anchor_failures=sum(len(r['anchor_failures']) for r in rows),
                   offsets_corrected=sum(c['anchor']['offsets_corrected'] for r in rows for c in r['claims']))
    result = seal(dict(version=VERSION, producer=producer, model=policy['model'], reasoning_effort=policy['reasoning_effort'],
                       prompt_version=contract.VERSION, strata_sha256=file_sha256(strata_path), plan_fingerprint=frozen['content_fingerprint'],
                       stopped=stopped, summary=summary, rows=rows, ledger=ledger.summary()))
    output = pilot / 'extract' / producer / 'extraction.json'
    write_json(output, result)
    return dict(plan, output=str(output), output_sha256=file_sha256(output), stopped=stopped, summary=summary)
