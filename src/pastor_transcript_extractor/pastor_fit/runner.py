"""Steps of the pastor fit experiment and where their outputs live.

Every output goes under `<base>/evaluation/pastor-fit-v1/`. `fingerprints`, `match` and
`church-fit` each run once: an existing result is never overwritten (spec section 10).
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Callable

from . import EXPERIMENT, cleaning, corpus, experiment, fingerprints, report

VARIANTS = ('clean', 'stripped', 'baseline')


def output_dir(base_dir: Path) -> Path:
    from ..bound_claims.common import ensure_outside_repository
    from ..config import build_paths, evaluation_root_for
    return ensure_outside_repository(evaluation_root_for(build_paths(base_dir), base_dir) / EXPERIMENT)


def _database(base_dir: Path) -> Path:
    from ..config import build_paths
    return build_paths(base_dir).database


def _read(path: Path):
    return json.loads(path.read_text())


def _once(path: Path) -> None:
    if path.exists():
        raise ValueError(f'{path.name} already exists; this step runs once (docs/PASTOR_FIT_EXPERIMENT.md section 6)')


def run_census(base_dir: Path) -> dict:
    sermons = [asdict(s) for s in corpus.load_population(_database(base_dir))]
    return experiment.census(sermons)


def default_encoder(base_dir: Path) -> Callable[[str], list[float] | None]:
    from .. import collector_retrieval_design as design
    from .. import collector_retrieval_encoder as encoder
    lock = design.sealed(encoder.LOCK)
    from ..config import build_paths, evaluation_root_for
    model_dir = evaluation_root_for(build_paths(base_dir), base_dir) / 'collector-retrieval-development-v1' / 'model' / lock['revision']
    return encoder.LocalEncoder(model_dir, execution_authorized=True).encode


def build_fingerprints(base_dir: Path, encode=None, echo=print) -> dict:
    out = output_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / 'fingerprints.json'
    _once(manifest_path)
    population = corpus.load_population(_database(base_dir))
    texts, provenance = {}, {}
    for sermon in population:
        texts[sermon.video_id], provenance[sermon.video_id] = corpus.sermon_text(sermon)
    channel_of = {s.video_id: s.source_id for s in population}
    variant_texts, removal = cleaning.variants(texts, channel_of)
    fingerprints.write_json(out / 'population.json', {
        'fingerprint': corpus.population_fingerprint(population),
        'sermons': [asdict(s) | provenance[s.video_id] for s in population]})
    fingerprints.write_json(out / 'removal.json', removal)
    encode = encode or default_encoder(base_dir)
    cache = fingerprints.EmbeddingCache(out / 'embedding-cache.npz')
    stats = {}
    for variant in VARIANTS:
        echo(f'{variant}: counting words and embedding chunks')
        fingerprints.write_json(out / f'counts-{variant}.json', fingerprints.word_counts(variant_texts[variant]))
        chunk_index, counter = fingerprints.build_embeddings(
            variant_texts[variant], encode, cache,
            progress=lambda n, total, s: echo(f'  {n}/{total} sermons, {s["encoded"]} chunks encoded'))
        fingerprints.write_json(out / f'chunks-{variant}.json', chunk_index)
        stats[variant] = dict(counter) | {'sermons_with_text': cleaning.nonempty(variant_texts[variant].values())}
    manifest = {'experiment': EXPERIMENT, 'sermons': len(population),
                'rolling_caption_normalized': sum(p['rolling_caption_normalized'] for p in provenance.values()),
                'variants': stats}
    fingerprints.write_json(manifest_path, manifest)
    return manifest


def _load(base_dir: Path):
    out = output_dir(base_dir)
    if not (out / 'fingerprints.json').exists():
        raise ValueError('Run `pte analysis pastor-fit fingerprints` first')
    sermons = _read(out / 'population.json')['sermons']
    vectors = fingerprints.EmbeddingCache(out / 'embedding-cache.npz').vectors
    fps = {v: experiment.Fingerprints(_read(out / f'counts-{v}.json'), _read(out / f'chunks-{v}.json'), vectors)
           for v in VARIANTS}
    return out, sermons, fps, vectors


def run_match(base_dir: Path) -> dict:
    out, sermons, fps, vectors = _load(base_dir)
    _once(out / 'part1.json')
    result = {'part1': experiment.part1(sermons, fps, vectors), 'part1b': experiment.part1b(sermons, fps)}
    fingerprints.write_json(out / 'part1.json', result)
    return {k: {name: r['summary'] for name, r in (v['4']['results'] if k == 'part1' else v).items()}
            for k, v in result.items()}


def run_church_fit(base_dir: Path) -> dict:
    out, sermons, fps, vectors = _load(base_dir)
    _once(out / 'part2.json')
    result = experiment.part2(sermons, fps, vectors)
    fingerprints.write_json(out / 'part2.json', result)
    return {name: r['summary'] for name, r in result['results'].items()}


def write_report(base_dir: Path) -> Path:
    out = output_dir(base_dir)
    for name in ('fingerprints.json', 'part1.json', 'part2.json'):
        if not (out / name).exists():
            raise ValueError(f'{name} is missing; run the earlier steps first')
    p1 = _read(out / 'part1.json')
    p2 = _read(out / 'part2.json')
    verdicts = experiment.verdicts(p1['part1'], p1['part1b'], p2)
    removal = _read(out / 'removal.json')
    data = report.build(_read(out / 'fingerprints.json'), p1, p2, verdicts, removal)
    fingerprints.write_json(out / 'REPORT.json', data)
    (out / 'REPORT.md').write_text(report.markdown(data))
    return out / 'REPORT.md'
