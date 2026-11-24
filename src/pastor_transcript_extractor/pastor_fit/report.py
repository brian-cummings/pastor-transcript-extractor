"""REPORT.json and REPORT.md for the pastor fit experiment."""
from __future__ import annotations

from . import EXPERIMENT
from .experiment import KINDS, PASS, PART1_MIN_SERMONS

KIND_NAMES = {'style': 'How they talk (stylometry, Burrows\' Delta)', 'embed': 'What they talk about (MiniLM embeddings)'}


def build(manifest: dict, p1: dict, p2: dict, verdicts: dict, removal: dict) -> dict:
    part1 = {n: {name: {'summary': r['summary'],
                        'same_church': {k: r['same_church'][k] for k in ('wins', 'comparisons')},
                        'words_most_often_driving_correct_matches': r['words_most_often_driving_correct_matches']}
                 for name, r in entry['results'].items()}
             for n, entry in p1['part1'].items()}
    channel_vocab = {c: v['channel_vocabulary'] for c, v in removal['channels'].items() if v['channel_vocabulary']}
    return {
        'experiment': EXPERIMENT, 'spec': 'docs/PASTOR_FIT_EXPERIMENT.md', 'pass_marks': PASS,
        'fingerprints': manifest, 'verdicts': verdicts,
        'part1': part1, 'part1b': {name: r['summary'] for name, r in p1['part1b'].items()},
        'part2': {'summaries': {name: r['summary'] for name, r in p2['results'].items()},
                  'cases': {name: r['rows'] for name, r in p2['results'].items() if name.endswith('/stripped')}},
        'removal': {'boilerplate_words': sum(s['boilerplate_words'] for s in removal['sermons'].values()),
                    'channel_vocabulary_words': sum(s['channel_vocabulary_words_removed'] for s in removal['sermons'].values()),
                    'words': sum(s['words'] for s in removal['sermons'].values()),
                    'channel_vocabulary': channel_vocab},
    }


def _pct(value: float) -> str:
    return f'{100 * value:.0f}%'


def _mark(ok: bool) -> str:
    return 'PASS' if ok else 'fail'


def markdown(data: dict) -> str:
    v = data['verdicts']
    lines = [f'# Pastor fit experiment: report ({EXPERIMENT})', '',
             'Spec: `docs/PASTOR_FIT_EXPERIMENT.md`. No LLM, Jev or voice processing. Pass marks were fixed before the run.', '',
             '## Verdicts', '',
             '| Fingerprint | Part 1 overall | Part 1 same church | Part 1b pre-filter | Part 2 church fit |',
             '| --- | --- | --- | --- | --- |']
    for kind in KINDS:
        lines.append(f'| {KIND_NAMES[kind]} | {_mark(v[kind]["part1_overall"])} | {_mark(v[kind]["part1_same_church"])} '
                     f'| {_mark(v[kind]["part1b"])} | {_mark(v[kind]["part2"])} |')
    removal = data['removal']
    lines += ['', '## Text removed before matching', '',
              f'- Words in the sermon windows: {removal["words"]:,}',
              f'- Removed as channel boilerplate: {removal["boilerplate_words"]:,} ({_pct(removal["boilerplate_words"] / max(removal["words"], 1))})',
              f'- Removed as channel vocabulary (stripped text only): {removal["channel_vocabulary_words"]:,}',
              f'- Channels with a vocabulary list: {len(removal["channel_vocabulary"])} (lists in REPORT.json)', '']
    for n in (str(m) for m in PART1_MIN_SERMONS):
        lines += [f'## Part 1: distinctness, profiles with at least {n} sermons', '',
                  '| Fingerprint / text | top 1 | top 3 | median rank | same-church wins |', '| --- | --- | --- | --- | --- |']
        for name, r in sorted(data['part1'][n].items()):
            s, c = r['summary'], r['same_church']
            lines.append(f'| {name} | {_pct(s["top1"])} | {_pct(s["top3"])} | {s["median_expected_rank"]:.1f} of {s["n"]} '
                         f'| {c["wins"]:g} of {c["comparisons"]} |')
        lines.append('')
    lines += ['Words most often driving correct style matches (clean text, 4+ sermons): '
              + ', '.join(data['part1'][str(PART1_MIN_SERMONS[0])]['style/clean']['words_most_often_driving_correct_matches']), '',
              '## Part 1b: identity pre-filter (right profile in the text top 5)', '',
              '| Fingerprint / text | top 5 | median rank | held-out sermons |', '| --- | --- | --- | --- |']
    for name, s in sorted(data['part1b'].items()):
        lines.append(f'| {name} | {_pct(s["top5"])} | {s["median_expected_rank"]:.1f} | {s["n"]} |')
    lines += ['', '## Part 2: church fit (held-out preacher among all candidates)', '',
              '| Fingerprint / text | cases in top 5 | median rank | cases |', '| --- | --- | --- | --- |']
    for name, s in sorted(data['part2']['summaries'].items()):
        if s.get('n'):
            lines.append(f'| {name} | {s["top5_cases"]:g} | {s["median_expected_rank"]:.1f} | {s["n"]} |')
    for name, rows in sorted(data['part2']['cases'].items()):
        lines += ['', f'### Part 2 cases, {name}', '', '| channel | preacher | expected rank | of | evidence |', '| --- | --- | --- | --- | --- |']
        for r in rows:
            evidence = ', '.join(r.get('shared_words', [])[:6]) or ' / '.join(r.get('preacher_chunks_nearest_church', [])[:1])
            lines.append(f'| {r["source_id"]} | {r["profile_id"]} | {r["expected_rank"]:.1f} | {r["candidates"]} | {evidence.replace("|", "/")} |')
    lines += ['', '## Reading', '',
              'Read the verdicts against spec section 6. A pass in Part 1 overall without the same-church control means the '
              'fingerprint mostly recognizes channels. Check the words and passages above for church names, series topics or '
              'other speakers before treating any match as a pastor signal.', '']
    return '\n'.join(lines)
