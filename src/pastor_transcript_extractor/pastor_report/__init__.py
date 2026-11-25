"""One pastor's report (`pte analysis pastor-report`): assembles evidence that is already saved, measures nothing new.

Sources, each reused with its own rules and none reinterpreted:
- Distinctive and stable traits: `benchmark_explainer.values.explain` against every other pastor (|z| >= 1.5, both
  halves agree), with its breadth check (`values.breadth`) and passages.
- Notable measures: every other dimension with |z| >= 1.0 that the explainer did not offer, labeled by why
  (distinctive but unstable across his sermons, or simply leaning).
- Church fit: `church_fit.reading` for one approved concerns file, when one is given.
- Scripture usage: the latest materialized Scripture summary (`pte analysis summarize-profile`), when one exists.
Nothing here is a verdict or label; small sermon counts are stated, not corrected for.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from ..benchmark_explainer import values

NOTABLE_Z = 1.0
FEW_SERMONS = 5


def assemble(pastor: str, sermons: Sequence[Mapping], scored, measured, table, dimensions,
             fit: Mapping | None = None) -> dict:
    """The report content for one pastor key ('p<profile id>'). `fit` is a `church_fit.reading` result or None."""
    if pastor not in table:
        raise ValueError(f'{pastor} has no scored sermons in the benchmark-explainer pool')
    explained = values.explain(pastor, sermons, table, scored, measured, dimensions)
    videos = [s['video_id'] for s in sermons if s['pastor'] == pastor]
    for row in explained['explained']:
        row['breadth'] = values.breadth(row, videos, scored, measured)
    offered = {r['dimension'] for r in explained['explained']}
    unstable = set(explained['distinct_but_unstable'])
    notable = []
    for row in sorted(explained['all_rows'], key=lambda r: -abs(r['z'])):
        if row['dimension'] in offered or abs(row['z']) < NOTABLE_Z:
            continue
        notable.append(dict(row, why='distinctive but not stable across his sermons' if row['dimension'] in unstable
                            else 'leans this way, below the distinctive mark'))
    church = None
    if fit is not None:
        row = fit['pastors'].get(pastor)
        church = dict(version=fit['version'], ranked_of=len(fit['ranked']),
                      included=row is not None, row=row)
    return dict(pastor=pastor, sermons=len(videos), video_ids=videos, halves=explained['halves'],
                few_sermons=len(videos) < FEW_SERMONS, explained=explained['explained'], notable=notable,
                not_enough_evidence=explained['not_enough_evidence'], church_fit=church)
