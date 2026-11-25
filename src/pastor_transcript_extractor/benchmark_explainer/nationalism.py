"""Christian nationalism indicators (avoid concern A2; docs/BENCHMARK_EXPLAINER.md section 16).

Three steps under `<out>/nationalism-v1/`, fixed before any result:
1. `probe` (paid, cents): the authored sample passages. Passes when at most one passage misses and no critical
   passage (Adventist church-state warnings, the Revelation 13 United States reading, religious liberty for all,
   a refuted quotation) is wrong. A leaf is positive at 0.5 or more.
2. `add` (paid, needs a passed probe): the four questions on every kept, scored sermon's blocks at the public-life
   route (topic at least 0.55). Answers go to the explainer's per-sermon caches and to `round/signals.json`, never
   into the signals the explainer and church fit read. Every block at 0.5 or more on any leaf is written to
   REVIEW.md for Brian to read.
3. `decide` (free): Brian accepts or rejects. Accept merges the answers into the signals files, after which every
   later scoring round asks these questions on routed blocks. Reject leaves every reader unchanged.
"""
from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from ..bound_claims.common import exceeds_failure_rate, read_json, write_json
from ..bound_claims.leaf_pass import JEV_REQUEST_RESERVATION, LedgeredClient, PACKS, signals_for, worst_case_requests
from ..sermon_classification import TranscriptBlock
from ..sermon_leaf_packs import CHRISTIAN_NATIONALISM
from ..sermon_topics import TopicBlockContext
from ..thought_units import arms
from . import score

LETTER = 'N'
PACK = PACKS[LETTER][0]
ROUTE = score.ROUTED[LETTER]
POSITIVE = 0.5
PROBE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'christian-nationalism-probes-v1.json'
MAX_PROBE_MISSES = 1
MAX_INVOCATIONS = 2


def folder(out: Path) -> Path:
    return out / score.NATIONALISM_DIR


def _client(ledger, factory, scope):
    if factory is None:
        from ..recording_verifier_typesafe import TypeSafeSdkAdapter
        factory = lambda model: TypeSafeSdkAdapter(model=model)
    return LedgeredClient(ledger, factory, score.MODEL, scope)


def _start(files: Path, plan: dict, state) -> dict:
    """Shared bounded-run bookkeeping: a frozen plan, at most one resume, committed source."""
    path = files / 'plan.json'
    if path.exists():
        plan = read_json(path)
    elif state is not None and state()['dirty']:
        raise ValueError('Uncommitted source changes: commit before the paid step so the run is reproducible')
    if (files / 'result.json').exists():
        raise ValueError(f'{files.name} is complete and runs once')
    if plan.get('invocations', 0) >= MAX_INVOCATIONS:
        raise ValueError(f'{files.name} was already started {MAX_INVOCATIONS} times (bounded retry)')
    plan['invocations'] = plan.get('invocations', 0) + 1
    files.mkdir(parents=True, exist_ok=True)
    write_json(path, plan)
    return plan


# ---- step 1: sample passages ------------------------------------------------------------------------------------

def probe_blocks(probes: list[dict]) -> tuple[list[TranscriptBlock], dict[int, TopicBlockContext]]:
    blocks = [TranscriptBlock(block_id=i, segment_indexes=[i], start_seconds=0.0, end_seconds=0.0, text=p['target_text'])
              for i, p in enumerate(probes)]
    contexts = {b.block_id: TopicBlockContext(leading_context='', target_text=b.text, trailing_context='',
                                              diagnostics={'source': 'authored_probe'}) for b in blocks}
    return blocks, contexts


def judge_probes(probes: list[dict], probabilities: Mapping[int, Mapping[str, float]]) -> dict:
    cases = []
    for i, probe in enumerate(probes):
        found = sorted(leaf for leaf, p in probabilities[i].items() if p >= POSITIVE)
        cases.append(dict(probe=i, target_text=probe['target_text'], reason=probe['reason'], critical=probe['critical'],
                          expected=sorted(probe['expected_positive_leaves']), found=found,
                          correct=found == sorted(probe['expected_positive_leaves']),
                          probabilities={k: round(v, 4) for k, v in probabilities[i].items()}))
    misses = [c for c in cases if not c['correct']]
    critical = [c for c in misses if c['critical']]
    passed = len(misses) <= MAX_PROBE_MISSES and not critical
    return dict(passed=passed, cases=len(cases), misses=len(misses), critical_misses=len(critical),
                pass_mark=f'at most {MAX_PROBE_MISSES} miss and no critical miss; a leaf is positive at {POSITIVE}',
                results=cases)


def probe(out: Path, *, ceiling_usd: Decimal, client_factory: Callable | None = None,
          state: Callable[[], dict] | None = None) -> dict:
    from ..bound_claims.ledger import PilotLedger
    from ..sermon_classifier_typesafe import TypeSafeBlockCache
    files = folder(out) / 'probe'
    probes = json.loads(PROBE_PATH.read_text())
    blocks, contexts = probe_blocks(probes)
    requests = worst_case_requests({LETTER: len(blocks)}, {LETTER: len(CHRISTIAN_NATIONALISM.definitions)})
    plan = _start(files, dict(pack=PACK, probes=len(probes), ceiling_usd=str(ceiling_usd),
                              ceiling_attempts=requests + 2, worst_case_requests=requests), state)
    if Decimal(plan['ceiling_usd']) != ceiling_usd:
        raise ValueError(f"The probe plan was frozen with --ceiling-usd {plan['ceiling_usd']}")
    ledger = PilotLedger(files / 'ledger.json', ceiling_usd=ceiling_usd, ceiling_attempts=plan['ceiling_attempts'])
    cache = TypeSafeBlockCache(files / 'cache', model=score.MODEL)
    answers = cache.assess_packs(_client(ledger, client_factory, 'probe'), {}, blocks,
                                 requested_packs=frozenset({PACK}), topic_contexts=contexts)
    probabilities = {b.block_id: answers[b.block_id].leaf_answers[PACK]['probabilities'] for b in blocks}
    result = judge_probes(probes, probabilities) | dict(
        ledger=json.loads(json.dumps(ledger.summary(), default=str)))
    write_json(files / 'result.json', result)
    (files / 'PROBES.md').write_text(_probe_markdown(result))
    return {k: v for k, v in result.items() if k != 'results'} | dict(report=str(files / 'PROBES.md'))


def _probe_markdown(result: dict) -> str:
    lines = ['# Christian nationalism: sample passages', '',
             f"**{'PASSED' if result['passed'] else 'FAILED'}**: {result['misses']} of {result['cases']} missed, "
             f"{result['critical_misses']} critical. Pass mark: {result['pass_mark']}.", '',
             '| # | Expected | Found | OK | Critical | Passage |', '|---|---|---|---|---|---|']
    for c in result['results']:
        lines.append(f"| {c['probe']} | {', '.join(c['expected']) or 'none'} | {', '.join(c['found']) or 'none'} | "
                     f"{'yes' if c['correct'] else '**no**'} | {'yes' if c['critical'] else ''} | {c['target_text']} |")
    return '\n'.join(lines) + '\n'


# ---- step 2: the pool -------------------------------------------------------------------------------------------

def routed(signals: Mapping) -> set[int]:
    return {b['ordinal'] for b in signals['blocks'] if b['signals'].get(ROUTE, 0.0) >= score.ROUTE_MIN}


def add(out: Path, sermons: list[dict], *, ceiling_usd: Decimal, check_only: bool = False,
        client_factory: Callable | None = None, state: Callable[[], dict] | None = None, echo=print) -> dict:
    from ..bound_claims.ledger import PilotLedger
    probe_result = folder(out) / 'probe' / 'result.json'
    if not probe_result.exists() or not read_json(probe_result)['passed']:
        raise ValueError('The sample-passage check has not passed: run `pte analysis benchmark-explainer nationalism-probe`')
    unscored = [s['video_id'] for s in sermons if not (out / 'signals' / f"v{s['video_id']}.json").exists()]
    if unscored:
        raise ValueError(f'{len(unscored)} kept sermons are not scored yet ({unscored[:5]}): run `score-added` first')
    work, misses = [], 0
    for sermon in sermons:
        signals = read_json(out / 'signals' / f"v{sermon['video_id']}.json")
        chosen = routed(signals)
        if not chosen:
            continue
        _, blocks, contexts = score.sermon_blocks(sermon['extraction_path'])
        blocks = [b for b in blocks if b.block_id in chosen]
        cache = score.cache_for(out, sermon['video_id'])
        misses += sum(1 for b in blocks if not any(cache._pack_path(PACK, i).exists()
                                                    for i in arms._identities(cache, b, PACK, contexts[b.block_id])))
        work.append((sermon, blocks, contexts))
    requests = worst_case_requests({LETTER: misses}, {LETTER: len(CHRISTIAN_NATIONALISM.definitions)})
    census = dict(sermons=len(sermons), sermons_with_routed_blocks=len(work), routed_blocks=sum(len(b) for _, b, _ in work),
                  cache_misses=misses, worst_case_requests=requests,
                  worst_case_reserved_usd=str(JEV_REQUEST_RESERVATION * requests), ceiling_usd=str(ceiling_usd))
    if check_only:
        return census
    files = folder(out) / 'round'
    plan = _start(files, census | dict(video_ids=[s['video_id'] for s, _, _ in work],
                                       ceiling_attempts=requests + 6), state)
    if Decimal(plan['ceiling_usd']) != ceiling_usd:
        raise ValueError(f"The round was frozen with --ceiling-usd {plan['ceiling_usd']}; resume with that ceiling")
    planned = set(plan['video_ids'])
    ledger = PilotLedger(files / 'ledger.json', ceiling_usd=ceiling_usd, ceiling_attempts=plan['ceiling_attempts'])
    saved = read_json(files / 'signals.json') if (files / 'signals.json').exists() else {}
    failures: list[dict] = []
    for number, (sermon, blocks, contexts) in enumerate(work, 1):
        key = str(sermon['video_id'])
        if sermon['video_id'] not in planned or key in saved:
            continue
        client = _client(ledger, client_factory, f"v{sermon['video_id']}")
        try:
            answers = score.cache_for(out, sermon['video_id']).assess_packs(
                client, {}, blocks, requested_packs=frozenset({PACK}), topic_contexts=contexts)
        except Exception as error:   # recorded, never retried in this invocation
            failures.append(dict(video_id=sermon['video_id'], error=type(error).__name__, detail=str(error)[:200]))
            echo(f"  v{key}: {type(error).__name__}")
        else:
            saved[key] = {str(b.block_id): signals_for(LETTER, answers[b.block_id]) for b in blocks}
            write_json(files / 'signals.json', saved)
        echo(f"{number}/{len(work)} v{key}: {client.requests} requests; ledger ${ledger.committed_usd()}")
        if exceeds_failure_rate(len(failures), number, score.FAILURE_RATE):
            write_json(files / 'failures.json', failures)
            raise RuntimeError(f'Stopped: {len(failures)} failed sermons of {number} (more than 5%); see failures.json')
    write_json(files / 'failures.json', failures)
    incomplete = sorted(planned - {int(k) for k in saved})
    summary = dict(plan=plan, failed=len(failures), incomplete_sermons=incomplete,
                   ledger=json.loads(json.dumps(ledger.summary(), default=str)))
    if not incomplete:
        write_json(files / 'result.json', summary)
        (files / 'REVIEW.md').write_text(review_markdown(out, sermons, saved))
        summary['review'] = str(files / 'REVIEW.md')
    return summary


def flagged(out: Path, sermons: list[dict], saved: Mapping[str, Mapping]) -> list[dict]:
    pastor = {str(s['video_id']): s['pastor'] for s in sermons}
    rows = []
    for video, blocks in saved.items():
        signals = read_json(out / 'signals' / f'v{video}.json')
        by_ordinal = {str(b['ordinal']): b for b in signals['blocks']}
        for ordinal, measures in blocks.items():
            hit = {k: round(v, 3) for k, v in measures.items() if v >= POSITIVE}
            if hit:
                block = by_ordinal[ordinal]
                rows.append(dict(video_id=int(video), pastor=pastor.get(video), ordinal=int(ordinal),
                                 start_seconds=block['start_seconds'], measures=hit,
                                 text=' '.join(block['text'].split())))
    rows.sort(key=lambda r: (r['pastor'] or '', r['video_id'], r['ordinal']))
    return rows


def review_markdown(out: Path, sermons: list[dict], saved: Mapping[str, Mapping]) -> str:
    rows = flagged(out, sermons, saved)
    asked = sum(len(b) for b in saved.values())
    lines = ['# Christian nationalism: passages to read', '',
             f'{len(rows)} of {asked} public-life blocks score {POSITIVE} or more on at least one indicator. For each, '
             'judge whether the preacher holds the view (a real case) or not (a warning, refutation, prophecy or '
             'other false match). Then run `pte analysis benchmark-explainer nationalism-decide`.', '']
    for r in rows:
        measures = ', '.join(f'{k} {v}' for k, v in r['measures'].items())
        lines += [f"## {r['pastor']} · video {r['video_id']} · block {r['ordinal']} · {int(r['start_seconds'])} s",
                  '', f'**{measures}**', '', f"> {r['text']}", '']
    return '\n'.join(lines) + '\n'


# ---- step 3: decision -------------------------------------------------------------------------------------------

def decide(out: Path, *, decision: str, note: str) -> dict:
    if decision not in ('accept', 'reject'):
        raise ValueError('The decision is accept or reject')
    files = folder(out) / 'round'
    if not (files / 'result.json').exists():
        raise ValueError('The pool round has not finished: run `pte analysis benchmark-explainer nationalism-add`')
    if score.nationalism_decision(out) is not None:
        raise ValueError(f'Already decided: {score.nationalism_decision(out)}')
    saved = read_json(files / 'signals.json')
    merged = 0
    if decision == 'accept':
        for video, blocks in saved.items():
            path = out / 'signals' / f'v{video}.json'
            signals = read_json(path)
            for block in signals['blocks']:
                block['signals'].update(blocks.get(str(block['ordinal']), {}))
            signals.setdefault('added_packs', []).append(PACK)
            write_json(path, signals)
            merged += 1
    write_json(folder(out) / 'decision.json', dict(decision=decision, note=note, pack=PACK, merged_sermons=merged))
    return dict(decision=decision, merged_sermons=merged,
                next='later scoring rounds ask these questions on public-life blocks' if decision == 'accept'
                else 'no reader changed; the saved answers stay in the round folder')
