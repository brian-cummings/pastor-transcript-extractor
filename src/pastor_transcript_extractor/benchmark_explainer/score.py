"""Jev dimensions per block (spec section 4, step 3; ceilings in section 6).

Blocks are the classifier's saved final-pass sermon blocks, rebuilt with the same block and context rule
the thought-unit experiment used (`public_set.sermon_blocks`, `arms.transcript_blocks`). Every saved answer
whose whole identity matches is copied in first, so it is never paid for again. T, H, L and M run on
every block; S and P only on blocks at the product route (topic at least 0.55).

Dollars: each request reserves its worst case before dispatch and the ledger refuses any reservation that
would pass $15, so spend can never exceed the ceiling. The whole-run worst case (65,536-token reservation
per request) is far above real usage (about a tenth), so it is reported but not required to fit up front.
"""
from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from ..bound_claims.common import exceeds_failure_rate, read_json, write_json
from ..bound_claims.leaf_pass import (
    CheckOnlyClient, JEV_REQUEST_RESERVATION, LedgeredClient, PACKS, SIGNAL_COUNTS, signals_for, worst_case_requests,
)
from ..bound_claims.ledger import PilotLedger
from ..sermon_classifier_typesafe import TypeSafeBlockCache
from ..thought_units import arms, public_set

MODEL = 'jev-1.13.0'
CEILING_USD = Decimal('15.00')
EXTRA_ATTEMPTS = 6
MAX_INVOCATIONS = 2   # the run, plus one resume after an interruption or failed calls (a bounded retry)
FAILURE_RATE = 0.05
EVERY_BLOCK = 'THLM'
ROUTED = {'S': 'T:salvation_gospel', 'P': 'T:society_public_life'}
ROUTE_MIN = 0.55
ORDER = 'THLMSP'
# Earlier caches whose saved answers may match exactly (copied in when their identity is identical).
SEED_SETS = ('thought-unit-experiment-v1/public-life-set-v1', 'thought-unit-experiment-v1/public-life-set-v2')


def sermon_blocks(extraction_path: str):
    proposed = read_json(Path(extraction_path))
    units = public_set.unit_records(public_set.sermon_blocks(proposed))
    blocks, contexts = arms.transcript_blocks(units, proposed['segments'])
    return units, blocks, contexts


def cache_for(out: Path, video_id: int) -> TypeSafeBlockCache:
    return TypeSafeBlockCache(out / 'cache' / f'v{video_id}', model=MODEL)


def seed_roots(evaluation_root: Path, sermon: Mapping[str, Any]) -> list[Path]:
    roots = [TypeSafeBlockCache(Path(sermon['extraction_path']).parent / 'inference-cache', model=MODEL).root]
    for name in SEED_SETS:
        roots.append(TypeSafeBlockCache(evaluation_root / name / 'cache' / f"v{sermon['video_id']}", model=MODEL).root)
    return [root for root in roots if (root / 'packs').exists()]


def census(out: Path, evaluation_root: Path, sermons: list[dict], *, seed: bool) -> dict:
    """Seed reusable answers (when `seed`) and count what is still missing; never opens a client."""
    misses = {letter: 0 for letter in ORDER}
    seeded = {'reusable': 0, 'already_here': 0}
    blocks_total = 0
    for sermon in sermons:
        _, blocks, contexts = sermon_blocks(sermon['extraction_path'])
        blocks_total += len(blocks)
        cache = cache_for(out, sermon['video_id'])
        roots = seed_roots(evaluation_root, sermon)
        if seed:
            for root in roots:
                seeded['reusable'] += arms.seed_from_pilot(cache, root, blocks, contexts, ORDER, copy=True)['reusable']
        for letter in ORDER:
            # S and P: every block is the upper bound; only routed blocks are sent.
            pack = PACKS[letter][0]
            for block in blocks:
                names = [cache._pack_path(pack, identity).name
                         for identity in arms._identities(cache, block, pack, contexts[block.block_id])]
                here = any(cache._pack_path(pack, identity).exists()
                           for identity in arms._identities(cache, block, pack, contexts[block.block_id]))
                saved = any((root / 'packs' / pack / name).exists() for root in roots for name in names)
                if not here and not saved:
                    misses[letter] += 1
                elif saved and not here and not seed:
                    seeded['reusable'] += 1
    requests = worst_case_requests(misses, {letter: SIGNAL_COUNTS[letter] for letter in ORDER})
    return dict(sermons=len(sermons), blocks=blocks_total, cache_misses=misses, reusable_saved_answers=seeded['reusable'],
                worst_case_requests=requests, worst_case_reserved_usd=str(JEV_REQUEST_RESERVATION * requests),
                expected_usd_note='real usage has run at about a tenth of the reservation (section 31 ledgers)',
                ceiling_usd=str(CEILING_USD))


def ledger_for(out: Path, ceiling_attempts: int) -> PilotLedger:
    return PilotLedger(out / 'ledger.json', ceiling_usd=CEILING_USD, ceiling_attempts=ceiling_attempts)


def score_sermon(out: Path, sermon: Mapping[str, Any], client, failures: list, echo=print) -> dict:
    """All packs for one sermon; a failing pack call is recorded and the rest continue."""
    units, blocks, contexts = sermon_blocks(sermon['extraction_path'])
    cache = cache_for(out, sermon['video_id'])
    table: dict[int, dict[str, float]] = {b.block_id: {} for b in blocks}
    calls = 0
    for letter in ORDER:
        chosen = blocks
        if letter in ROUTED:
            chosen = [b for b in blocks if table[b.block_id].get(ROUTED[letter], 0.0) >= ROUTE_MIN]
        if not chosen:
            continue
        calls += 1
        try:
            answers = cache.assess_packs(client, {}, chosen, requested_packs=frozenset({PACKS[letter][0]}),
                                         topic_contexts=contexts)
        except Exception as error:   # transport or schema failure: recorded, never retried in this run
            failures.append(dict(video_id=sermon['video_id'], pack=letter, error=type(error).__name__, detail=str(error)[:200]))
            echo(f"  v{sermon['video_id']} {letter}: {type(error).__name__}")
            if letter == 'T':
                break   # routing needs topics; the sermon's other packs are left for a resumed run
            continue
        for block in chosen:
            table[block.block_id].update(signals_for(letter, answers[block.block_id]))
    return dict(video_id=sermon['video_id'], pastor=sermon['pastor'], calls=calls,
                blocks=[dict(ordinal=u['ordinal'], block_id=u['block_id'], start_seconds=u['start_seconds'],
                             end_seconds=u['end_seconds'], text=u['text'], signals=table[u['ordinal']]) for u in units])


def run(out: Path, evaluation_root: Path, sermons: list[dict], *, client_factory: Callable | None = None,
        state: Callable[[], dict] | None = None, echo=print) -> dict:
    plan_path = out / 'score_plan.json'
    if plan_path.exists():
        plan = read_json(plan_path)
    else:
        if state is not None and state()['dirty']:
            raise ValueError('Uncommitted source changes: commit before the paid step so the run is reproducible')
        plan = census(out, evaluation_root, sermons, seed=True)
        plan['ceiling_attempts'] = plan['worst_case_requests'] + EXTRA_ATTEMPTS
        plan['invocations'] = 0
    if (out / 'score.json').exists():
        raise ValueError('score.json already exists; the Jev run is complete and runs once')
    if plan['invocations'] >= MAX_INVOCATIONS:
        raise ValueError(f'The Jev run was already started {MAX_INVOCATIONS} times; unfinished sermons stay unscored (bounded retry)')
    plan['invocations'] += 1
    write_json(plan_path, plan)
    ledger = ledger_for(out, plan['ceiling_attempts'])
    factory = client_factory
    if factory is None:
        from ..recording_verifier_typesafe import TypeSafeSdkAdapter
        factory = lambda model: TypeSafeSdkAdapter(model=model)
    failures: list[dict] = []
    calls = 0
    signals_dir = out / 'signals'
    for number, sermon in enumerate(sermons, 1):
        target = signals_dir / f"v{sermon['video_id']}.json"
        if target.exists():
            continue        # finished in an earlier, interrupted invocation
        client = LedgeredClient(ledger, factory, MODEL, f"v{sermon['video_id']}")
        before = len(failures)
        result = score_sermon(out, sermon, client, failures, echo)
        calls += result['calls']
        if len(failures) == before:
            write_json(target, result)
        echo(f"{number}/{len(sermons)} v{sermon['video_id']} ({sermon['pastor']}): {client.requests} requests; "
             f"ledger ${ledger.committed_usd()}")
        if exceeds_failure_rate(len(failures), max(calls, 1), FAILURE_RATE):
            write_json(out / 'score_failures.json', failures)
            raise RuntimeError(f'Stopped: {len(failures)} failed pack calls of {calls} (more than 5%); see score_failures.json')
    write_json(out / 'score_failures.json', failures)
    incomplete = [s['video_id'] for s in sermons if not (signals_dir / f"v{s['video_id']}.json").exists()]
    summary = dict(plan=plan, failed_calls=len(failures), incomplete_sermons=incomplete,
                   ledger=json.loads(json.dumps(ledger.summary(), default=str)))
    if not incomplete:
        write_json(out / 'score.json', summary)
    return summary
