"""Step B: the 59 existing Jev leaf signals on every block of the slice sermons.

Orchestration only. Each pack goes through the established per-sermon
`TypeSafeBlockCache`, so every saved compatible answer is reused and a cache hit
never opens a client. Question text, versions and batching are not changed.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

from pastor_transcript_extractor.sermon_classification import TranscriptBlock
from pastor_transcript_extractor.sermon_classifier_typesafe import (
    SALVATION_RELATIONSHIPS_PACK, TOPIC_PACK, TREATMENT_PACK, TypeSafeBlockAnswer, TypeSafeBlockCache,
)
from pastor_transcript_extractor.sermon_leaf_packs import LISTENER_DIRECTIVES, PUBLIC_LIFE_TREATMENT, SOURCE_MATERIAL
from pastor_transcript_extractor.sermon_salvation_relationships import SALVATION_RELATIONSHIPS
from pastor_transcript_extractor.sermon_semantic_dimensions import SEMANTIC_DIMENSIONS
from pastor_transcript_extractor.sermon_topics import (
    TOPICS, TopicBlockContext, resolve_topic_analysis_artifact, resolve_topic_block_context,
    topic_supporting_or_above_probability,
)

from .common import coordinate, file_sha256, read_json, write_json
from .ledger import PilotLedger, list_price_usd
from .slice import verify_slice

VERSION = 'bound-claim-leaf-pass-v1'
JEV_INPUT_USD_PER_MILLION = '0.042'
JEV_OUTPUT_USD_PER_MILLION = '0'
JEV_REQUEST_TOKEN_LIMIT = 65536  # same per-request input cap the shared verifier reservation uses
JEV_REQUEST_RESERVATION = list_price_usd(JEV_REQUEST_TOKEN_LIMIT, 0, JEV_INPUT_USD_PER_MILLION, JEV_OUTPUT_USD_PER_MILLION)
# Attempts the later paid steps need; the leaf pass must leave them within the 600-attempt pilot ceiling.
HELD_EXTRACT_ATTEMPTS = 200
HELD_VERIFY_ATTEMPTS = 250

# Priority order: the signals strata selection reads (T, S, P) are collected before the rest.
PACKS: dict[str, tuple[str, str]] = {
    'T': (TOPIC_PACK, 'topic'),
    'S': (SALVATION_RELATIONSHIPS_PACK, 'salvation relationship'),
    'P': (PUBLIC_LIFE_TREATMENT.version, 'public-life treatment'),
    'L': (LISTENER_DIRECTIVES.version, 'listener directive'),
    'M': (SOURCE_MATERIAL.version, 'source material'),
    'H': (TREATMENT_PACK, 'homiletic style'),
}
# L and M are not read by any pilot step and their misses alone would exhaust the shared attempt
# ceiling, so they are opt-in (`--packs TSPLMH`); T, S, P feed strata and H is fully cached.
DEFAULT_PACKS = 'TSPH'
SIGNAL_COUNTS = {'T': len(TOPICS), 'S': len(SALVATION_RELATIONSHIPS), 'P': len(PUBLIC_LIFE_TREATMENT.definitions),
                 'L': len(LISTENER_DIRECTIVES.definitions), 'M': len(SOURCE_MATERIAL.definitions), 'H': len(SEMANTIC_DIMENSIONS)}


class CheckOnlyMiss(Exception):
    """Raised by the check-only client in place of a provider request."""


class CheckOnlyClient:
    def assess_blocks(self, recording_context, blocks, **kwargs):
        raise CheckOnlyMiss(sorted(kwargs.get('requested_packs') or ()))


class LedgeredClient:
    """Reserves before every physical Jev request and records known list-price usage."""

    def __init__(self, ledger: PilotLedger, factory: Callable[[str], Any], model: str, scope: str):
        self.ledger, self.factory, self.model, self.scope = ledger, factory, model, scope
        self._adapter = None
        self.requests = 0

    def assess_blocks(self, recording_context, blocks, **kwargs):
        if self._adapter is None:
            self._adapter = self.factory(self.model)
        packs = sorted(kwargs.get('requested_packs') or ())
        prefix = f"leaf/{self.scope}/{'+'.join(packs)}/{blocks[0].block_id}-{blocks[-1].block_id}"
        entry = f'{prefix}/{self.ledger.entry_count(prefix + "/")}'
        self.ledger.reserve(entry, 'leaf', JEV_REQUEST_RESERVATION, packs=packs, blocks=len(blocks), model=self.model)
        self.requests += 1
        try:
            answers = self._adapter.assess_blocks(recording_context, blocks, **kwargs)
        except Exception as error:
            self.ledger.resolve(entry, actual_usd=None, error=type(error).__name__)
            raise
        usage = answers[blocks[0].block_id].request_provenance
        tokens = usage.get('input_tokens')
        if type(tokens) is int and 0 <= tokens <= JEV_REQUEST_TOKEN_LIMIT:
            self.ledger.resolve(entry, actual_usd=list_price_usd(tokens, 0, JEV_INPUT_USD_PER_MILLION, JEV_OUTPUT_USD_PER_MILLION),
                                input_tokens=tokens, output_tokens=usage.get('output_tokens') or 0)
        else:
            self.ledger.resolve(entry, actual_usd=None, error='usage_missing')
        return answers


def sermon_blocks(sermon: Mapping[str, Any]) -> tuple[list[TranscriptBlock], dict[int, TopicBlockContext]]:
    """Saved topic-analysis blocks and bounded contexts, exactly as the cached answers were keyed."""
    classification = read_json(Path(sermon['source_path']))['classification']
    blocks, contexts = [], {}
    for raw in resolve_topic_analysis_artifact(classification)['blocks']:
        context = resolve_topic_block_context(raw)
        block = TranscriptBlock(block_id=raw['block_id'], segment_indexes=list(raw['segment_indexes']),
                                start_seconds=raw['start_seconds'], end_seconds=raw['end_seconds'], text=context['target_text'])
        blocks.append(block)
        contexts[block.block_id] = TopicBlockContext(**context)
    return blocks, contexts


def signals_for(letter: str, answer: TypeSafeBlockAnswer) -> dict[str, float]:
    if letter == 'T':
        return {f'T:{topic}': round(topic_supporting_or_above_probability(answer.topic_scores[topic]), 6) for topic in TOPICS}
    if letter == 'S':
        return {f'S:{name}': float(answer.salvation_relationship_probabilities[name]) for name in SALVATION_RELATIONSHIPS}
    if letter == 'H':
        return {f'H:{name}': float(answer.semantic_probabilities[name]) for name in SEMANTIC_DIMENSIONS}
    pack = PACKS[letter][0]
    return {f'{letter}:{leaf}': float(value) for leaf, value in answer.leaf_answers[pack]['probabilities'].items()}


def worst_case_requests(misses: Mapping[str, int], questions_per_block: Mapping[str, int]) -> int:
    """Existing batching: at most 75 questions per request, at least one block."""
    total = 0
    for letter, blocks in misses.items():
        per_request = max(1, min(6, 75 // questions_per_block[letter]))
        total += -(-blocks // per_request)
    return total


def run(slice_path: Path, approved_sha256: str, ledger: PilotLedger, *, check_only: bool = False,
        letters: str = DEFAULT_PACKS, client_factory: Callable[[str], Any] | None = None) -> dict[str, Any]:
    slice_path = Path(slice_path).resolve()
    slice_ = verify_slice(slice_path, approved_sha256)
    letters = ''.join(letter for letter in PACKS if letter in letters.upper())
    if not letters:
        raise ValueError('Choose at least one pack from T S P L M H')
    pilot = slice_path.parent
    # 1. Exact per-block, per-pack cache census (no client, no provider request).
    sermons, misses, hits = [], {letter: 0 for letter in letters}, {letter: 0 for letter in letters}
    for sermon in slice_['sermons']:
        blocks, contexts = sermon_blocks(sermon)
        cache = TypeSafeBlockCache(Path(sermon['cache_dir']), model=sermon['model'])
        sermons.append((sermon, blocks, contexts, cache))
        for letter in letters:
            for block in blocks:
                try:
                    cache.assess_packs(CheckOnlyClient(), {}, [block], requested_packs=frozenset({PACKS[letter][0]}),
                                       topic_contexts={block.block_id: contexts[block.block_id]})
                    hits[letter] += 1
                except CheckOnlyMiss:
                    misses[letter] += 1
    questions = {letter: SIGNAL_COUNTS[letter] for letter in letters}
    requests = worst_case_requests(misses, questions)
    worst_usd = JEV_REQUEST_RESERVATION * requests
    held = HELD_EXTRACT_ATTEMPTS + HELD_VERIFY_ATTEMPTS
    plan = dict(version=VERSION, packs=letters, blocks=sum(len(item[1]) for item in sermons), cache_hits=hits, cache_misses=misses,
                worst_case_requests=requests, worst_case_reserved_usd=str(worst_usd),
                attempts_held_for_later_steps=held, check_only=check_only)
    if check_only:
        return plan
    if requests:
        ledger.require_step('leaf', worst_usd, requests + held)
    factory = client_factory
    if factory is None and requests:
        from pastor_transcript_extractor.recording_verifier_typesafe import TypeSafeSdkAdapter
        factory = lambda model: TypeSafeSdkAdapter(model=model)
    # 2. Collect. Cache hits come back without any client being created.
    observed, physical = [], 0
    for sermon, blocks, contexts, _census in sermons:
        # Fresh cache object: its hit/miss counters describe only this collection pass.
        cache = TypeSafeBlockCache(Path(sermon['cache_dir']), model=sermon['model'])
        client = LedgeredClient(ledger, factory, sermon['model'], str(sermon['video_id'])) if factory else CheckOnlyClient()
        table = {block.block_id: {} for block in blocks}
        for letter in letters:
            answers = cache.assess_packs(client, {}, blocks, requested_packs=frozenset({PACKS[letter][0]}), topic_contexts=contexts)
            for block in blocks:
                table[block.block_id].update(signals_for(letter, answers[block.block_id]))
        physical += getattr(client, 'requests', 0)
        observed.append(dict(
            video_id=sermon['video_id'], profile_id=sermon['profile_id'], title=sermon['title'], url=sermon['url'],
            youtube_video_id=sermon['youtube_video_id'], model=sermon['model'], source_sha256=sermon['source_sha256'],
            cache_hits=cache.hits, cache_misses=cache.misses, provider_requests=cache.provider_requests,
            blocks=[dict(coordinate=coordinate(sermon['video_id'], block.block_id), block_id=block.block_id, ordinal=ordinal,
                         start_seconds=block.start_seconds, end_seconds=block.end_seconds,
                         segment_indexes=list(block.segment_indexes), text=block.text, signals=table[block.block_id])
                    for ordinal, block in enumerate(blocks)]))
    result = dict(version=VERSION, slice_sha256=approved_sha256, packs=letters,
                  signal_inventory={letter: SIGNAL_COUNTS[letter] for letter in letters}, sermons=observed,
                  pre_run_census=plan, physical_requests=physical, ledger=ledger.summary())
    output = pilot / 'leaf' / 'leaf_observations.json'
    write_json(output, result)
    return dict(plan, output=str(output), output_sha256=file_sha256(output), physical_requests=physical, ledger=ledger.summary())
