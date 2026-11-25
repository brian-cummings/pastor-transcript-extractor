"""Who and what is compared: the 47 analyzed profiles and the two benchmarks' target sermons (spec section 3)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3

from ..pastor_fit import corpus
from ..sermon_analysis import _load_sermon_source
from . import BENCHMARK_PASTORS

BENCHMARK_SQL = """
SELECT c.pastor_id, v.id, v.youtube_video_id, v.source_id, e.proposed_json_path
FROM video_target_contexts AS c
JOIN videos AS v ON v.id = c.video_id
JOIN extraction_results AS e ON e.video_id = c.video_id
WHERE c.pastor_id IN ({ids})
  AND e.id = (SELECT MAX(id) FROM extraction_results WHERE video_id = c.video_id)
  AND e.proposed_json_path IS NOT NULL
ORDER BY c.pastor_id, v.id
"""


@dataclass(frozen=True)
class Sermon:
    video_id: int
    youtube_video_id: str
    pastor: str             # 'p<profile id>' for the pool, 'b<pastor id>' for a benchmark
    source_id: int
    extraction_path: str


def pool_key(profile_id: int) -> str:
    return f'p{profile_id}'


def benchmark_key(pastor_id: int) -> str:
    return f'b{pastor_id}'


def load(database: Path, excluded: list | None = None) -> list[Sermon]:
    """Pool and benchmark sermons. A benchmark extraction with no identified sermon window (for example one the
    recording verifier rejected as a multi-speaker program) is left out and listed in `excluded`."""
    pool = [Sermon(s.video_id, s.youtube_video_id, pool_key(s.profile_id), s.source_id, s.extraction_path)
            for s in corpus.load_population(database)]
    connection = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
    try:
        rows = connection.execute(BENCHMARK_SQL.format(ids=','.join('?' * len(BENCHMARK_PASTORS))),
                                  tuple(BENCHMARK_PASTORS)).fetchall()
    finally:
        connection.close()
    pooled = {s.video_id for s in pool}
    benchmarks = []
    for pastor_id, video_id, youtube_id, source_id, path in rows:
        if video_id in pooled:
            raise ValueError(f'Benchmark video {video_id} is also in an analyzed profile')
        try:
            _load_sermon_source(Path(path))
        except (ValueError, OSError) as error:
            if excluded is not None:
                excluded.append(dict(video_id=int(video_id), pastor=benchmark_key(int(pastor_id)), reason=str(error)))
            continue
        benchmarks.append(Sermon(int(video_id), str(youtube_id), benchmark_key(int(pastor_id)), int(source_id), str(path)))
    return pool + benchmarks


def video_details(database: Path, video_ids: list[int]) -> dict[int, dict]:
    connection = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
    try:
        rows = connection.execute(
            f"SELECT id, title, url FROM videos WHERE id IN ({','.join('?' * len(video_ids))})", video_ids).fetchall()
    finally:
        connection.close()
    return {int(i): {'title': t, 'url': u} for i, t, u in rows}


def pastor_names(database: Path, pastors: list[str]) -> dict[str, str]:
    ids = [int(p[1:]) for p in pastors if p.startswith('p')]
    connection = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
    try:
        marks = ','.join('?' * len(ids))
        rows = dict(connection.execute(
            f"SELECT id, display_label FROM speaker_profiles WHERE id IN ({marks})", ids).fetchall()) if ids else {}
        # Unlabeled profiles: the reviewed name claim attached to the profile (latest event per claim is 'attach').
        claimed = dict(connection.execute(f"""
            SELECT e.profile_id, c.display_name FROM profile_name_claim_events AS e
            JOIN speaker_name_claims AS c ON c.id = e.claim_id
            WHERE e.profile_id IN ({marks}) AND e.action = 'attach'
              AND e.id = (SELECT MAX(id) FROM profile_name_claim_events
                          WHERE profile_id = e.profile_id AND claim_id = e.claim_id)
            ORDER BY e.id""", ids).fetchall()) if ids else {}
    finally:
        connection.close()
    names = {}
    for pastor in pastors:
        number = int(pastor[1:])
        names[pastor] = (BENCHMARK_PASTORS[number] if pastor.startswith('b')
                         else (rows.get(number) or (f'{claimed[number]} (profile {number})' if number in claimed
                                                    else f'profile {number}')))
    return names


def as_dicts(sermons: list[Sermon]) -> list[dict]:
    return [asdict(s) for s in sermons]
