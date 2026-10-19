"""Small, provider-free provenance trace; never classification or discovery credit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3

from pastor_transcript_extractor.caption_normalization import normalize_caption_fragments
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_classification import build_transcript_blocks
from pastor_transcript_extractor.sermon_classifier_typesafe import build_role_contexts
from pastor_transcript_extractor.sermon_topics import build_topic_context, resolve_topic_analysis_artifact

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'docs/review-proposals/evidence-pipeline-trace-v1'
SPEC = ROOT / 'docs/review-proposals/context-extraction-probe-v1/source-panel-spec-v1.json'
OLD_INPUT = ROOT / 'docs/review-proposals/collector-retrieval-repair-v1.1/development-input-v1.1.json'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path, sealed=False):
    path = Path(path)
    if path.stat().st_size > 20_000_000:
        raise ValueError('Bounded trace file size exceeded')
    value = json.loads(path.read_text())
    if sealed and seal(value) != value:
        raise ValueError('Invalid source/report seal: ' + str(path))
    return value


def view(text):
    """Whitespace-only diagnostic comparison, NOT canonical coordinate mapping."""
    return re.sub(r'\s+', ' ', text).strip()


def span_presence(spans, text):
    normalized = view(text)
    return dict(all_present=all(view(s['text']) in normalized for s in spans),
                literal_all_present=all(s['text'] in text for s in spans),
                missing=[name for name, s in enumerate(spans) if view(s['text']) not in normalized])


def source_location(source, span):
    if source['text'][span['start']:span['end']] != span['text']:
        raise ValueError('Oracle span does not match canonical source')
    units = [u for u in source['units'] if u['start'] < span['end'] and u['end'] > span['start']]
    if not units:
        raise ValueError('Source span has no timestamped unit provenance')
    return dict(canonical_start=span['start'], canonical_end=span['end'],
                unit_ids=[u['unit_id'] for u in units],
                source_segment_indexes=sorted({i for u in units for i in u['source_segment_indexes']}),
                conservative_start_seconds=min(u['start_seconds'] for u in units),
                conservative_end_seconds=max(u['end_seconds'] for u in units),
                precision='Whole normalization-unit bounds, not word-level timestamps')


def block_row(block, ordinal=None):
    value = dict(block_id=block.block_id, start_seconds=block.start_seconds,
                 end_seconds=block.end_seconds, segment_indexes=block.segment_indexes,
                 duration_seconds=block.end_seconds-block.start_seconds, characters=len(block.text),
                 exceeds_60_second_target=block.end_seconds-block.start_seconds>60, exceeds_3200_character_target=len(block.text)>3200)
    if ordinal is not None:
        value['artifact_ordinal'] = ordinal
    return value


def trace_case(case, source, persisted, blocks, contexts, role_contexts):
    oracle = case['oracle']
    roles = list(oracle['focal_roles'].values())
    spans = roles + oracle['required_source_supports']
    locations = [source_location(source, s) for s in spans]
    role_indexes = {i for loc in locations[:len(roles)] for i in loc['source_segment_indexes']}
    candidates = [b for b in blocks if role_indexes.intersection(b.segment_indexes)]
    rows = []
    for block in candidates:
        context = contexts[block.block_id]
        role_context = role_contexts[block.block_id]
        topic_text = '\n'.join((context.leading_context, block.text, context.trailing_context))
        role_text = '\n'.join([*[b['text'] for b in role_context.preceding_blocks], block.text,
                               *[b['text'] for b in role_context.following_blocks]])
        position = blocks.index(block)
        adjacent_text = '\n'.join(b.text for b in blocks[max(0, position-1):position+2])
        rows.append(dict(**block_row(block), center=span_presence(spans, block.text),
                         current_topic_payload=span_presence(spans, topic_text),
                         current_role_payload=span_presence(spans, role_text),
                         full_adjacent_block_counterfactual=span_presence(spans, adjacent_text),
                         topic_context_diagnostics=context.diagnostics))
    actual = []
    for ordinal, b in enumerate(persisted):
        if not role_indexes.intersection(b['segment_indexes']):
            continue
        actual.append(dict(artifact_ordinal=ordinal, block_id=b['block_id'], start_seconds=b['start_seconds'],
                           end_seconds=b['end_seconds'], source_presence=span_presence(spans, b['text'])))
    return dict(case_id=case['case_id'], kind=case['kind'], route=case['route'], video_id=case['video_id'],
                oracle_scope='Full focal footprint; clipped cases retain parent footprint, not clipped-context success criteria',
                locations=locations, persisted_matching_blocks=actual, reconstructed_minute_candidates=rows,
                footprint_available=dict(center=any(r['center']['all_present'] for r in rows),
                    current_topic_payload=any(r['current_topic_payload']['all_present'] for r in rows),
                    current_role_payload=any(r['current_role_payload']['all_present'] for r in rows),
                    full_adjacent_block_counterfactual=any(r['full_adjacent_block_counterfactual']['all_present'] for r in rows)),
                evidence_authority=False, semantic_recovery=None, admission=None)


def inventory():
    names = ('collector-retrieval-design-v1', 'collector-retrieval-implementation-v1',
             'collector-retrieval-repair-v1.1', 'context-evidence-architecture-v1',
             'context-extraction-probe-v1', 'fresh-discovery-readiness-v1',
             'fresh-discovery-readiness-v2', 'fresh-discovery-readiness-v3', 'source-unit-repair-v1')
    rows = []
    for name in names:
        directory = ROOT / 'docs/review-proposals' / name
        files = [p for p in directory.rglob('*') if p.is_file()]
        needle = str(directory.relative_to(ROOT))
        dependents = []
        for path in (ROOT/'docs/review-proposals').rglob('*.json'):
            if not path.is_relative_to(directory) and needle in path.read_text():
                dependents.append(str(path.relative_to(ROOT)))
        rows.append(dict(path=needle, files=len(files), bytes=sum(f.stat().st_size for f in files),
                         external_json_dependents=dependents,
                         disposition='retain_frozen_support' if name=='source-unit-repair-v1' else 'retire_from_active_guidance_preserve_historical_seals'))
    return rows


def build(base_dir=None):
    paths = build_paths(base_dir)
    spec, old = read(SPEC, True), read(OLD_INPUT, True)
    if len(spec['cases']) != 24 or set(old['source_files']) != {'520', '1094', '951'}:
        raise ValueError('Only the existing 24 cases / three retired sources may be traced')
    cases, sources, input_files = [], [], {str(SPEC): digest(SPEC), str(OLD_INPUT): digest(OLD_INPUT)}
    with sqlite3.connect(paths.database.as_uri()+'?mode=ro', uri=True) as db:
        for vid in (520, 1094, 951):
            info = old['source_files'][str(vid)]
            if digest(info['path']) != info['sha256']:
                raise ValueError('Frozen source snapshot changed')
            source = read(info['path'], True)
            path = Path(source['source_manifest_row']['proposed_json_path'])
            expected = source['source_manifest_row']['file_hashes']['proposed_json_path']
            if digest(path) != expected:
                raise ValueError('Persisted extraction changed')
            extracted = read(path)
            segments = extracted['segments']
            if len(segments) > 5000:
                raise ValueError('Bounded trace segment limit exceeded')
            drafts = [SegmentDraft(s['start_seconds'],s['end_seconds'],s['text'],s.get('speaker_hint'),s['label'],s.get('confidence')) for s in segments]
            normalized = normalize_caption_fragments((i,s['text']) for i,s in enumerate(segments))
            if '\n'.join(u.text for u in normalized.units)!=source['text']:
                raise ValueError('Canonical snapshot cannot be reconstructed from persisted segments')
            if any(list(u.source_segment_indexes)!=old_unit['source_segment_indexes'] for u,old_unit in zip(normalized.units,source['units'],strict=True)):
                raise ValueError('Canonical source unit lineage differs')
            persisted = extracted['classification']['blocks']
            # Reconstruct deterministic views only; do NOT classify, route or infer.
            normalize = any(b.get('normalization') is not None for b in persisted)
            blocks = build_transcript_blocks(drafts, target_seconds=60, max_chars=3200,
                                             normalize_rolling_captions=normalize)
            if len(blocks)>200:
                raise ValueError('Bounded trace block limit exceeded')
            role_contexts = build_role_contexts(blocks)
            contexts = {b.block_id:build_topic_context(drafts,b) for b in blocks}
            try:
                topics = resolve_topic_analysis_artifact(extracted['classification'])
                topic_count = len(topics.get('blocks',[]))
            except ValueError:
                topic_count = 0
            run_count = db.execute('select count(*) from sermon_analysis_runs where video_id=?',(vid,)).fetchone()[0]
            source_cases = [c for c in spec['cases'] if c['video_id']==vid]
            cases.extend(trace_case(c,source,persisted,blocks,contexts,role_contexts) for c in source_cases)
            sources.append(dict(video_id=vid, persisted_method=extracted['classification']['method'],
                persisted_model=extracted['classification']['model'], persisted_builder=extracted['classification']['block_builder_version'],
                persisted_block_count=len(persisted), reconstructed_minute_count=len(blocks),
                persisted_topic_block_count=topic_count, persisted_sermon_analysis_run_count=run_count,
                manifest_source_kind=source['source_manifest_row']['source_kind'], actual_extraction_source=extracted['transcript_source'],
                normalized_source_hash=source['normalized_text_sha256'],
                canonical_source_reconstructed_exactly=True, canonical_unit_segment_lineage_verified=True,
                reconstructed_over_60_seconds=sum(b.end_seconds-b.start_seconds>60 for b in blocks),
                reconstructed_over_3200_characters=sum(len(b.text)>3200 for b in blocks),
                reconstructed_max_seconds=max(b.end_seconds-b.start_seconds for b in blocks),
                reconstructed_max_characters=max(len(b.text) for b in blocks),
                reconstruction_scope='Full persisted transcript stream, before current coarse eligibility, sermon membership and any topic routing. No current provider decisions exist.',
                database_segment_artifacts=[dict(artifact_id=r[0],count=r[1]) for r in db.execute('select artifact_id,count(*) from transcript_segments where video_id=? group by artifact_id',(vid,))]))
            input_files[str(path)] = expected
            input_files[info['path']] = info['sha256']
    cases.sort(key=lambda r:r['case_id'])
    positives = [r for r in cases if r['kind']=='adequate']
    return seal(dict(version='evidence-pipeline-trace-v1',status='PROVIDER_FREE_DIAGNOSTIC_NOT_EVALUATION',
        source_spec_fingerprint=spec['content_fingerprint'], sources=sources, cases=cases,
        adequate_footprint_diagnostics={route:{key:sum(r['footprint_available'][key] for r in positives if r['route']==route)
            for key in ('center','current_topic_payload','current_role_payload','full_adjacent_block_counterfactual')}
            for route in ('G2','G3_current','G3_reported')},
        input_files=input_files, implementation_files={str(Path(__file__)):digest(__file__),
            **{str(ROOT/'src/pastor_transcript_extractor'/n):digest(ROOT/'src/pastor_transcript_extractor'/n)
               for n in ('sermon_classifier_typesafe.py','sermon_classification.py','sermon_topics.py','caption_normalization.py')}},
        cleanup_inventory=inventory(), provider_requests=0, model_loading=False, classification_execution=False,
        limitations=['Whitespace-only source presence is not exact coordinate alignment, semantic target sufficiency, discovery credit or usable evidence.',
            'Timestamp mapping uses whole normalized-unit segment provenance, not word timestamps.',
            'Current minute views are deterministic reconstructions, not existing routed/current-model observations.',
            'Actual historical block IDs may repeat between coarse/fine stages; artifact ordinals are retained.',
            'No cleanup or artifact deletion was executed.']))


def save_report(report,base_dir=None):
    out = build_paths(base_dir).evaluation/'evidence-pipeline-trace-v1'
    out.mkdir(parents=True,exist_ok=True)
    path = out/'pipeline-trace-v1.json'
    raw = json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if path.exists() and path.read_text()!=raw:
        raise ValueError('Existing trace differs; preserve it rather than overwrite')
    path.write_text(raw)
    return path


def verify(base_dir=None):
    path=build_paths(base_dir).evaluation/'evidence-pipeline-trace-v1/pipeline-trace-v1.json'
    report=read(path,True)
    for name,expected in {**report['input_files'],**report['implementation_files']}.items():
        if digest(name)!=expected:
            raise ValueError('Trace dependency changed: '+name)
    if report['provider_requests']!=0 or report['classification_execution']:
        raise ValueError('Trace scope changed')
    return report,path
