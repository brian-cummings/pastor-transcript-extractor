"""Step A: propose five pastors / ten sermons from cached topic projections; no provider call."""
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Callable, Mapping

from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.sermon_topics import resolve_topic_analysis_artifact, topic_supporting_or_above_probability

from .common import ensure_outside_repository, file_sha256, pilot_dir, read_json, write_json

VERSION = 'bound-claim-slice-v1'
PROFILE_COUNT = 5
MINIMUM_PROFILES = 3
SERMONS_PER_PROFILE = 2
HISTORICAL_PROFILE = 318
PUBLIC_LIFE_PROFILES = 2
PUBLIC_LIFE_TOPIC = 'society_public_life'
NEAR_FLOOR, STRONG_FLOOR = 0.40, 0.70
ANALYZER_KEY = 'typesafe-topic-projection'

# Profiles and sermons come from active or provisional profiles; a sermon is
# "analyzed" when a cached TypeSafe topic projection exists for it, because the
# leaf pass reuses those saved block contexts instead of re-segmenting.
CANDIDATE_SQL = f"""
WITH latest AS (SELECT profile_id, observation_id, MAX(id) AS event_id FROM profile_observation_events GROUP BY 1, 2)
SELECT p.id AS profile_id, p.display_label, p.lifecycle_state, o.video_id,
       v.youtube_video_id, v.title, v.url, v.published_at, v.duration_seconds,
       (SELECT r.source_path FROM sermon_analysis_runs r WHERE r.video_id = o.video_id
         AND r.analyzer_key = '{ANALYZER_KEY}' ORDER BY r.id DESC LIMIT 1) AS source_path,
       (SELECT COUNT(DISTINCT o2.video_id) FROM latest l2
          JOIN profile_observation_events e2 ON e2.id = l2.event_id AND e2.action = 'attach'
          JOIN speaker_observations o2 ON o2.id = e2.observation_id WHERE l2.profile_id = p.id) AS attached_sermons
FROM latest l
JOIN profile_observation_events e ON e.id = l.event_id AND e.action = 'attach'
JOIN speaker_profiles p ON p.id = e.profile_id AND p.lifecycle_state IN ('active', 'provisional')
JOIN speaker_observations o ON o.id = e.observation_id
JOIN videos v ON v.id = o.video_id
WHERE source_path IS NOT NULL
GROUP BY p.id, o.video_id
ORDER BY p.id, o.video_id
"""


def candidate_rows(database: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(CANDIDATE_SQL)]
    finally:
        connection.close()


def sermon_attention(source_path: str) -> dict[str, Any]:
    """Public-life attention and block inventory from the cached topic projection."""
    proposed = read_json(Path(source_path))
    classification = proposed['classification']
    blocks = resolve_topic_analysis_artifact(classification)['blocks']
    mass = [topic_supporting_or_above_probability(block['scores'][PUBLIC_LIFE_TOPIC]) for block in blocks]
    return dict(block_count=len(blocks), model=classification['model'],
                public_life_near_or_above=sum(value >= NEAR_FLOOR for value in mass),
                public_life_strong=sum(value >= STRONG_FLOOR for value in mass))


def _order(sermon: Mapping[str, Any]) -> tuple:
    return (sermon['published_at'] or '', sermon['video_id'])


def build_slice(rows: list[dict[str, Any]], attention: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    profiles: dict[int, dict[str, Any]] = {}
    for row in rows:
        profile = profiles.setdefault(row['profile_id'], dict(
            profile_id=row['profile_id'], display_label=row['display_label'], lifecycle_state=row['lifecycle_state'],
            attached_sermons=row['attached_sermons'], candidates=[]))
        profile['candidates'].append(dict(row, **attention(row['source_path'])))
    for profile in profiles.values():
        profile['analyzed_sermons'] = len(profile['candidates'])
        profile['public_life_attention'] = sum(c['public_life_near_or_above'] for c in profile['candidates'])
        profile['public_life_strong'] = sum(c['public_life_strong'] for c in profile['candidates'])
    ranked = sorted(profiles.values(), key=lambda p: (-p['analyzed_sermons'], -p['attached_sermons'], p['profile_id']))
    eligible = [p for p in ranked if p['analyzed_sermons'] >= 3]
    notes: list[str] = []
    chosen: list[dict[str, Any]] = []
    reasons: dict[int, str] = {}

    def take(profile: dict[str, Any], reason: str) -> None:
        if profile not in chosen and len(chosen) < PROFILE_COUNT:
            chosen.append(profile)
            reasons[profile['profile_id']] = reason

    if HISTORICAL_PROFILE in profiles and profiles[HISTORICAL_PROFILE]['analyzed_sermons'] >= SERMONS_PER_PROFILE:
        take(profiles[HISTORICAL_PROFILE], 'historical comparison profile')
    by_attention = sorted((p for p in eligible if p not in chosen), key=lambda p: (-p['public_life_attention'], p['profile_id']))
    for profile in by_attention[:PUBLIC_LIFE_PROFILES]:
        take(profile, f"{PUBLIC_LIFE_TOPIC} attention: {profile['public_life_attention']} blocks at or above {NEAR_FLOOR}")
    for profile in eligible:
        take(profile, 'analyzed-sermon count')
    if len(chosen) < PROFILE_COUNT:
        for profile in ranked:
            if profile['analyzed_sermons'] >= SERMONS_PER_PROFILE:
                take(profile, 'analyzed-sermon count (two analyzed sermons; floor relaxed)')
    if any('floor relaxed' in reason for reason in reasons.values()):
        notes.append('The three-sermon floor was relaxed for at least one profile that has two cached topic-analyzed sermons.')
    if len(chosen) < MINIMUM_PROFILES:
        raise ValueError(f'Only {len(chosen)} profiles have two or more cached topic-analyzed sermons')
    if len(chosen) < PROFILE_COUNT:
        notes.append(
            f'Only {len(chosen)} of the {PROFILE_COUNT} requested profiles currently have two or more attached sermons '
            'with a cached topic projection, so the slice has fewer profiles than requested. A fifth profile would need '
            'fresh block segmentation, which has no saved Jev answers to reuse; that is a separate decision.')
    sermons: list[dict[str, Any]] = []
    undated = False
    for profile in chosen:
        ordered = sorted(profile['candidates'], key=_order)
        undated = undated or any(c['published_at'] is None for c in ordered)
        # Earliest and latest by date, else by video id, to spread series and dates.
        picked = [ordered[0], ordered[-1]] if len(ordered) > SERMONS_PER_PROFILE else ordered
        for sermon in picked:
            cache_dir = str(Path(sermon['source_path']).parent / 'inference-cache')
            sermons.append(dict(
                profile_id=profile['profile_id'], video_id=sermon['video_id'], youtube_video_id=sermon['youtube_video_id'],
                title=sermon['title'], url=sermon['url'], duration_seconds=sermon['duration_seconds'],
                published_at=sermon['published_at'], source_path=sermon['source_path'],
                source_sha256=file_sha256(Path(sermon['source_path'])), cache_dir=cache_dir, model=sermon['model'],
                block_count=sermon['block_count'], public_life_strong=sermon['public_life_strong'],
                public_life_near_or_above=sermon['public_life_near_or_above']))
    if undated:
        notes.append('Some sermons lack published_at; the earliest/latest pair falls back to video id order.')
    return dict(
        version=VERSION, selection_rule=(
            f'Profiles in an active/provisional lifecycle state ranked by cached topic-analyzed sermon count: profile '
            f'{HISTORICAL_PROFILE}, the {PUBLIC_LIFE_PROFILES} highest-{PUBLIC_LIFE_TOPIC}-attention profiles, then count; '
            f'{SERMONS_PER_PROFILE} sermons each, earliest and latest.'),
        notes=notes,
        profiles=[dict(profile_id=p['profile_id'], display_label=p['display_label'], lifecycle_state=p['lifecycle_state'],
                       analyzed_sermons=p['analyzed_sermons'], attached_sermons=p['attached_sermons'],
                       public_life_attention=p['public_life_attention'], public_life_strong=p['public_life_strong'],
                       reason=reasons[p['profile_id']]) for p in chosen],
        sermons=sermons, total_blocks=sum(s['block_count'] for s in sermons))


def verify_slice(path: Path, approved_sha256: str) -> dict[str, Any]:
    """Every provider-facing step proves Brian approved exactly this file and its sources are unchanged."""
    if file_sha256(path) != approved_sha256:
        raise ValueError('Slice differs from the approved SHA-256; run slice-propose and approve the new file')
    slice_ = read_json(path)
    if slice_.get('version') != VERSION:
        raise ValueError('Foreign slice version')
    for sermon in slice_['sermons']:
        if file_sha256(Path(sermon['source_path'])) != sermon['source_sha256']:
            raise ValueError(f"Source changed after slice approval: video {sermon['video_id']}")
    return slice_


def propose(base_dir: Path | None, output: Path | None = None) -> dict[str, Any]:
    paths = build_paths(base_dir)
    output = ensure_outside_repository(output if output is not None else pilot_dir(base_dir) / 'slice.json')
    slice_ = build_slice(candidate_rows(paths.database), sermon_attention)
    write_json(output, slice_)
    return dict(slice=str(output), sha256=file_sha256(output), profiles=slice_['profiles'],
                sermons=[{k: s[k] for k in ('profile_id', 'video_id', 'title', 'block_count', 'public_life_strong')} for s in slice_['sermons']],
                total_blocks=slice_['total_blocks'], notes=slice_['notes'],
                approve_with=f"--approve-slice {file_sha256(output)}")
