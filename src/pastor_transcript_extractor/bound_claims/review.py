"""Step F: blind accept/reject queue. Decisions are evaluation labels and never become runtime evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
from typing import Any, Callable, Mapping

from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal

from . import contract
from .common import file_sha256, read_json, write_json
from .verify import collect_claims

VERSION = 'bound-claim-review-queue-v1'
PRODUCERS = ('pro', 'flash')
DECISIONS = 'decisions.jsonl'
RECORD_FIELDS = ('area', 'object', 'proposition', 'polarity', 'voiced_by', 'preacher_adoption', 'speech_role',
                 'conditions', 'qualifications', 'reasons', 'anchor_text')


def parse_decision(text: str) -> str | None:
    """`accept`, `reject` or `reject:<field>`; also the shortcuts `a`, `r` and `r:<field>`."""
    text = text.strip().lower().replace(' ', ':', 1) if text.strip().lower().startswith(('r ', 'reject ')) else text.strip().lower()
    head, _, field = text.partition(':')
    if head in ('a', 'accept') and not field:
        return 'accept'
    if head in ('r', 'reject'):
        if not field:
            return 'reject'
        if field in contract.REJECTION_FIELDS:
            return 'reject:' + field
    return None


def extraction_paths(pilot: Path) -> list[Path]:
    paths = [pilot / 'extract' / producer / 'extraction.json' for producer in PRODUCERS]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise ValueError('Both producers must be extracted before review; missing ' + ', '.join(missing))
    return paths


def build_queue(pilot: Path) -> dict[str, Any]:
    strata_path, slice_path = pilot / 'strata.json', pilot / 'slice.json'
    strata = read_json(strata_path)
    labels = {p['profile_id']: p['display_label'] for p in read_json(slice_path)['profiles']}
    blocks = {b['coordinate']: b for b in strata['blocks']}
    items = []
    for found in collect_claims(extraction_paths(pilot)):
        block = blocks[found['coordinate']]
        text, start, end = found['text'], found['anchor']['start'], found['anchor']['end']
        claim = found['claim']
        items.append(dict(
            id=found['fingerprint'], coordinate=found['coordinate'],
            pastor=labels.get(block['profile_id']) or f"Profile {block['profile_id']}",
            title=block['title'], watch_url=block['watch_url'],
            preceding_text=found['preceding_text'], target_before=text[:start], anchor=text[start:end], target_after=text[end:],
            following_text=found['following_text'], record={key: claim[key] for key in RECORD_FIELDS}))
    # Order is a pure function of the slice seed and claim identity; producer identity is not in the queue.
    items.sort(key=lambda item: item['id'])
    random.Random(f"{strata['seed']}:review").shuffle(items)
    return seal(dict(version=VERSION, strata_sha256=file_sha256(strata_path), seed=strata['seed'], item_count=len(items),
                     decisions=['accept', 'reject', *('reject:' + field for field in contract.REJECTION_FIELDS)], items=items))


def write_queue(pilot: Path, output: Path | None = None) -> dict[str, Any]:
    queue = build_queue(pilot)
    output = Path(output) if output else pilot / 'review.json'
    write_json(output, queue)
    return dict(output=str(output), sha256=file_sha256(output), items=queue['item_count'])


def _queue(pilot: Path) -> dict[str, Any]:
    path = pilot / 'review.json'
    if not path.exists():
        write_queue(pilot)
    queue = read_json(path)
    if seal(queue) != queue or queue['strata_sha256'] != file_sha256(pilot / 'strata.json'):
        raise ValueError('review.json is not the sealed queue for this strata file; regenerate it with review-queue')
    return queue


def load_decisions(pilot: Path) -> dict[str, dict[str, Any]]:
    """Latest record per claim wins; a `void` record returns the claim to the queue."""
    path = pilot / DECISIONS
    latest: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record['decision'] == 'void':
                latest.pop(record['claim_fingerprint'], None)
            else:
                latest[record['claim_fingerprint']] = record
    return latest


def record_decision(pilot: Path, fingerprint: str, decision: str, source: str | None = None) -> dict[str, Any]:
    """`source` is label provenance; records without one are the reviewer's own (reported as `human`)."""
    if decision != 'void' and parse_decision(decision) != decision:
        raise ValueError(f'Unknown decision: {decision}')
    record = dict(claim_fingerprint=fingerprint, decision=decision, decided_at=datetime.now(timezone.utc).isoformat())
    if source:
        record['source'] = source
    with (pilot / DECISIONS).open('a') as stream:
        stream.write(json.dumps(record, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    return record


def replay(pilot: Path, decisions: Path) -> dict[str, Any]:
    """Non-interactive labels from `{claim fingerprint: decision}` JSON or JSON lines; idempotent."""
    queue = _queue(pilot)
    known = {item['id'] for item in queue['items']}
    text = Path(decisions).read_text().strip()
    try:
        entries = json.loads(text)
    except json.JSONDecodeError:
        entries = {record['claim_fingerprint']: record['decision'] for record in map(json.loads, text.splitlines())}
    if not isinstance(entries, dict):
        raise ValueError('Decisions must map claim fingerprints to decisions')
    existing = load_decisions(pilot)
    written = 0
    for fingerprint, decision in entries.items():
        if fingerprint not in known:
            raise ValueError('Decision for a claim that is not in the queue: ' + fingerprint)
        if parse_decision(decision) is None:
            raise ValueError(f'Unknown decision: {decision}')
        if existing.get(fingerprint, {}).get('decision') != parse_decision(decision):
            record_decision(pilot, fingerprint, parse_decision(decision))
            written += 1
    return progress(pilot) | dict(written=written)


def load_ids(path: Path) -> set[str]:
    """Claim ids from a JSON list, or the keys/`claim_id` values of a JSON object."""
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        data = [value['claim_id'] if isinstance(value, dict) and 'claim_id' in value else key for key, value in data.items()]
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise ValueError('Expected a JSON list of claim ids')
    return set(data)


def import_proposals(pilot: Path, proposals: Path, source: str) -> dict[str, Any]:
    """Write proposed labels (`{claim_id: decision}` or `{key: {claim_id, decision}}`) for claims with no label yet.

    Existing labels always win, and every written record carries `source`, so the report can state how much of the
    labeling was not the reviewer's own.
    """
    if not source.strip():
        raise ValueError('A provenance source is required')
    queue = _queue(pilot)
    known = {item['id'] for item in queue['items']}
    data = json.loads(Path(proposals).read_text())
    if not isinstance(data, dict):
        raise ValueError('Proposals must be a JSON object')
    entries = {}
    for key, value in data.items():
        claim_id, decision = (value['claim_id'], value['decision']) if isinstance(value, dict) else (key, value)
        if claim_id not in known:
            raise ValueError('Proposal for a claim that is not in the queue: ' + claim_id)
        if parse_decision(decision) is None:
            raise ValueError(f'Unknown decision: {decision}')
        entries[claim_id] = parse_decision(decision)
    existing = load_decisions(pilot)
    written = 0
    for claim_id, decision in entries.items():
        if claim_id not in existing:
            record_decision(pilot, claim_id, decision, source.strip())
            written += 1
    return progress(pilot) | dict(written=written, skipped_already_labeled=len(entries) - written, source=source.strip())


def progress(pilot: Path) -> dict[str, Any]:
    queue = _queue(pilot)
    decided = load_decisions(pilot)
    return dict(items=queue['item_count'], decided=sum(item['id'] in decided for item in queue['items']),
                remaining=sum(item['id'] not in decided for item in queue['items']), decisions_file=str(pilot / DECISIONS))


def render(item: Mapping[str, Any], number: int, total: int) -> str:
    record = item['record']
    lines = [f"\n[{number}/{total}] {item['pastor']} — {item['title']}", item['watch_url'], '',
             'PRECEDING: ' + (item['preceding_text'] or '(none)'), '',
             'TARGET: ' + item['target_before'] + '«' + item['anchor'] + '»' + item['target_after'], '',
             'FOLLOWING: ' + (item['following_text'] or '(none)'), '',
             f"AREA: {record['area']}    OBJECT: {record['object']}",
             f"PROPOSITION: {record['proposition']}",
             f"POLARITY: {record['polarity']}    VOICED BY: {record['voiced_by']}    PREACHER: {record['preacher_adoption']}    ROLE: {record['speech_role']}"]
    for name in ('conditions', 'qualifications', 'reasons'):
        lines.append(name.upper() + ': ' + ('; '.join(record[name]) if record[name] else '(none)'))
    lines.append('ANCHOR: «' + record['anchor_text'] + '»')
    return '\n'.join(lines)


PROMPT = ('accept (a) / reject (r) / reject:<field> where field is ' + ', '.join(contract.REJECTION_FIELDS) +
          ' / undo last (u) / quit (q): ')


def interactive(pilot: Path, input_fn: Callable[[str], str] = input, output_fn: Callable[[str], Any] = print,
                only: set[str] | None = None) -> dict[str, Any]:
    """Resumable loop over undecided items in queue order; `only` limits it to those claim ids."""
    queue = _queue(pilot)
    items, last = queue['items'], None
    while True:
        decided = load_decisions(pilot)
        todo = [(number, item) for number, item in enumerate(items, 1)
                if item['id'] not in decided and (only is None or item['id'] in only)]
        if not todo:
            output_fn('All claims are labeled.' if only is None else 'Every claim in the list is labeled.')
            break
        number, item = todo[0]
        output_fn(render(item, number, len(items)) + ('' if only is None else f'\n({len(todo)} left in this list)'))
        answer = input_fn(PROMPT).strip().lower()
        if answer in ('q', 'quit'):
            break
        if answer in ('u', 'undo'):
            if last is None:
                output_fn('Nothing to undo in this session.')
            else:
                record_decision(pilot, last, 'void')
                last = None
            continue
        decision = parse_decision(answer)
        if decision is None:
            output_fn('Not understood.')
            continue
        record_decision(pilot, item['id'], decision)
        last = item['id']
    return progress(pilot)
