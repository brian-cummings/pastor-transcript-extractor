"""One reserved request: the whole sermon, one named object. No semantic retry, no second prompt (spec section 4)."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

from pastor_transcript_extractor import deepinfra_requests as provider
from pastor_transcript_extractor import evidence_requests as requests
from pastor_transcript_extractor.bound_claims.common import digest, file_sha256, read_json, write_json
from pastor_transcript_extractor.bound_claims.extract import _physical_usage, git_state
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger, list_price_usd
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.context_extraction_validation import strict_json

from . import components, contract, sermon as sermons

VERSION = 'object-position-check-v1'
VERSION_ID = requests.DEEPINFRA_BOUND_CLAIM_VERSIONS[2]
STEP = 'extract_pro'  # the ledger's existing step name; this check has its own ledger file
CEILING_USD, CEILING_ATTEMPTS = Decimal('0.50'), 2
MAX_RECORDS = 40


def build_request(sermon: sermons.Sermon, object_name: str) -> requests.RequestSpec:
    policy = provider.policy_for(VERSION_ID)
    body = dict(
        model=policy['model'],
        messages=[dict(role='system', content=contract.SYSTEM_PROMPT),
                  dict(role='user', content=contract.user_message(object_name, sermon.text))],
        max_tokens=policy['output_cap'],
        response_format=dict(type='json_schema', json_schema=dict(name='bound_claims', strict=True, schema=contract.RESPONSE_SCHEMA)),
        temperature=0, top_p=1, stream=False, n=1, reasoning_effort=policy['reasoning_effort'])
    spec = requests.RequestSpec('source_reading', body,
        dict(coordinate=f'v{sermon.video_id}', object=object_name, source_sha256=sermon.source_sha256, contract=contract.VERSION),
        namespace=VERSION_ID, version=VERSION_ID, runtime_identity=dict(policy))
    return provider.streaming_request(spec)


def _prices(metadata: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    policy = provider.policy_for(VERSION_ID)
    published = dict(metadata(policy['model']))
    for field, key in (('input_usd_per_million', 'input_cents_per_token'), ('output_usd_per_million', 'output_cents_per_token')):
        if Decimal(published[key]) * 10000 != Decimal(policy[field]):
            raise ValueError(f"Published {field} {Decimal(published[key]) * 10000} differs from the reserved list price {policy[field]}")
    return published


def freeze_plan(output: Path, sermon: sermons.Sermon, object_name: str, leaf_sha: str, state: Callable[[], dict[str, Any]],
                metadata: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    current = state()
    if current['dirty']:
        raise ValueError('Uncommitted source changes: the implementation must be committed and frozen before the request')
    identity = dict(object=object_name, video_id=sermon.video_id, source_sha256=sermon.source_sha256, leaf_sha256=leaf_sha,
                    instruction_sha256=digest(contract.SYSTEM_PROMPT), components_sha256=digest(components.COMPONENTS))
    path = output / 'plan.json'
    if path.exists():
        plan = read_json(path)
        if seal(plan) != plan:
            raise ValueError('plan.json seal differs')
        if ({key: plan[key] for key in identity}, plan['implementation']['src_tree']) != (identity, current['src_tree']):
            raise ValueError('Frozen plan differs from the object, sermon, instruction, components or implementation; no variant is allowed')
        return plan
    plan = seal(dict(version=VERSION, **identity, implementation=current, policy=provider.policy_for(VERSION_ID),
                     ceiling=dict(usd=str(CEILING_USD), attempts=CEILING_ATTEMPTS), published_deepinfra_metadata=_prices(metadata),
                     retries='none; one request, only the bounded whitespace/transport recovery', stop_rules=dict(max_records=MAX_RECORDS)))
    write_json(path, plan)
    return plan


def decode(response: Mapping[str, Any], sermon: sermons.Sermon) -> dict[str, Any]:
    records, failures = [], []
    for claim in contract.validate_claims(strict_json(response['output'])):
        anchor = contract.check_anchor(claim, sermon.text)
        if anchor['status'] != 'ok':
            failures.append(dict(claim=claim, anchor=anchor))
            continue
        coordinate, _ = sermon.block_at(anchor['start'])
        records.append(dict(claim=claim, anchor=anchor, coordinate=coordinate, watch_url=sermon.link_at(anchor['start'])))
    records.sort(key=lambda record: (record['anchor']['start'], record['anchor']['end']))
    for number, record in enumerate(records, 1):
        record['number'] = number
    return dict(records=records, anchor_failures=failures)


def run(leaf_path: Path, output: Path, video_id: int, object_name: str, *, check_only: bool = False,
        transport: Callable | None = None, state: Callable[[], dict[str, Any]] = git_state,
        metadata: Callable[[str], Mapping[str, Any]] = provider.public_model_metadata) -> dict[str, Any]:
    leaf_path, output = Path(leaf_path).resolve(), Path(output).resolve()
    sermon = sermons.load(leaf_path, video_id)
    spec = build_request(sermon, object_name)
    reservation = provider.reserved_usd(spec.version)
    policy = provider.policy_for(VERSION_ID)
    spans = components.located(sermon.text)
    ledger = PilotLedger(output / 'ledger.json', ceiling_usd=CEILING_USD, ceiling_attempts=CEILING_ATTEMPTS)
    receipt = output / 'receipts' / (spec.fingerprint + '.json')
    plan = dict(version=VERSION, object=object_name, video_id=video_id, title=sermon.title, model=policy['model'],
                sermon_characters=len(sermon.text), blocks=len(sermon.blocks), request_bytes=len(provider.wire(spec.body).encode()),
                reserved_usd=str(reservation), ceiling_usd=str(CEILING_USD), ceiling_attempts=CEILING_ATTEMPTS,
                already_received=receipt.exists(), check_only=check_only,
                components_located={str(key): [len(found) for found in value] for key, value in spans.items()})
    unique = all(len(found) == 1 for value in spans.values() for found in value)
    if check_only:
        return dict(plan, every_component_span_located_exactly_once=unique)
    if not unique:
        raise ValueError('A component span is missing or ambiguous in the sermon text; the frozen components must locate exactly once')
    entry = f'{STEP}/v{video_id}'
    if not receipt.exists():
        ledger.require_step(STEP, reservation, 1)
    frozen = freeze_plan(output, sermon, object_name, file_sha256(leaf_path), state, metadata)
    store = requests.ReceiptStore(output)
    row = dict(status='pending', records=[], anchor_failures=[])
    if not receipt.exists() and ledger.entry_status(entry) is not None:
        row.update(status='lost_attempt', error='A prior attempt has no receipt; uncertain spend, never retried')
    else:
        if not receipt.exists():
            ledger.reserve(entry, STEP, reservation, coordinate=f'v{video_id}', version=VERSION_ID)
        response = failure = None
        try:
            response = requests.execute(spec, provider.OneRequestLedger(str(reservation), spec.version), store, transport or provider.transport)
        except (ValueError, KeyError, TypeError, OSError) as error:
            failure = error
        if ledger.entry_status(entry) == 'reserved':
            usage = _physical_usage(store)
            ledger.resolve(entry, actual_usd=(list_price_usd(usage['input_tokens'], usage['output_tokens'],
                policy['input_usd_per_million'], policy['output_usd_per_million'])
                + usage['unmetered_attempts'] * provider.reserved_usd(VERSION_ID) if usage else None), **usage)
        if failure is None:
            try:
                row.update(status='ok', usage=response['usage'], **decode(response, sermon))
            except (ValueError, KeyError, TypeError) as error:
                failure = contract.SchemaError(str(error))
        if failure is not None:
            row.update(status='schema_failure' if isinstance(failure, contract.SchemaError) else 'transport_failure', error=str(failure)[:500])
    stopped = (f"stop rule: {len(row['records'])} records exceed the maximum of {MAX_RECORDS}" if len(row['records']) > MAX_RECORDS
               else None if row['status'] == 'ok' else f"stop rule: request {row['status']}")
    result = seal(dict(version=VERSION, object=object_name, video_id=video_id, plan_fingerprint=frozen['content_fingerprint'],
                       prompt_version=contract.VERSION, source_sha256=sermon.source_sha256, stopped=stopped, **row, ledger=ledger.summary()))
    path = output / 'result.json'
    write_json(path, result)
    return dict(plan, output=str(path), output_sha256=file_sha256(path), stopped=stopped, status=row['status'],
                records=len(row['records']), anchor_failures=len(row['anchor_failures']))
