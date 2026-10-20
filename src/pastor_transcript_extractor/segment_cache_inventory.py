"""Bounded, read-only inventory of persisted segment observations. No inference."""
from __future__ import annotations
from collections import Counter,defaultdict
from pathlib import Path
import json
import math

from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.inference_defaults import DEFAULT_TYPESAFE_MODEL
from pastor_transcript_extractor.sermon_topic_projection import assess_topic_profile_projection
from pastor_transcript_extractor import sermon_topic_profile_analysis as topics_projection
from pastor_transcript_extractor.sermon_topics import TOPIC_PACK_VERSION,TOPIC_SPECS,topic_pack_digest,resolve_topic_analysis_artifact,resolve_topic_block_context,validated_topic_scores
from pastor_transcript_extractor.sermon_semantic_dimensions import SEMANTIC_ANALYSIS_QUESTION_VERSION,SEMANTIC_DIMENSIONS
from pastor_transcript_extractor import sermon_salvation_relationships as salvation
from pastor_transcript_extractor.profile_analysis import resolve_profile_sermon_scope,profile_membership_fingerprint

VERSION='segment-cache-inventory-v1'
MAX_SOURCES=12


def finite_probabilities(values,expected):
    if set(values)!=set(expected) or any(type(v) not in (float,int) or not math.isfinite(v) or not 0<=v<=1 for v in values.values()):
        raise ValueError('Incompatible probability inventory')


def compatible_layers(classification,analysis,eligible_ids):
    """Reuse meanings only when question/model/policy/target identities match."""
    if analysis['question_pack_version']!=TOPIC_PACK_VERSION or analysis['question_pack_digest']!=topic_pack_digest() or analysis['requested_model_id']!=DEFAULT_TYPESAFE_MODEL:
        raise ValueError('Topic contract/model differs')
    blocks={b['block_id']:b for b in analysis['blocks']}
    if len(blocks)!=len(analysis['blocks']):raise ValueError('Duplicate topic block IDs')
    eligible={}
    for key in eligible_ids:
        b=blocks[key]
        if b['resolved_model_id']!=DEFAULT_TYPESAFE_MODEL or not b['projection_eligibility']['eligible']:
            raise ValueError('Incompatible eligible topic block')
        scores=validated_topic_scores(b)
        for score in scores.values():
            finite_probabilities(score['probabilities'],[str(i) for i in range(5)])
        eligible[key]=b
    search=classification.get('search',{})
    sem=search.get('semantic_analysis',{})
    treatment=[];treatment_reason=None
    if sem.get('question_version')!=SEMANTIC_ANALYSIS_QUESTION_VERSION or sem.get('dimensions')!=list(SEMANTIC_DIMENSIONS):
        treatment_reason='missing_or_incompatible_question_version'
    else:
        for b in sem.get('blocks',[]):
            topic=eligible.get(b['block_id'])
            if topic is None:continue
            if (b['resolved_model_id']!=DEFAULT_TYPESAFE_MODEL or any(b[k]!=topic[k] for k in ('start_seconds','end_seconds','segment_indexes'))):
                treatment_reason='model_or_target_identity_differs';treatment=[];break
            finite_probabilities(b['probabilities'],SEMANTIC_DIMENSIONS)
            treatment.append(dict(block_id=b['block_id'],probabilities=b['probabilities'],model=b['resolved_model_id']))
    sal=[];sal_reason=None
    try:raw=salvation.resolve_salvation_relationship_analysis_artifact(classification)
    except ValueError:raw={}
    expected=dict(question_pack_version=salvation.SALVATION_RELATIONSHIPS_PACK_VERSION,
        question_pack_digest=salvation.salvation_relationship_pack_digest(),requested_model_id=DEFAULT_TYPESAFE_MODEL,
        observation_policy_version=salvation.SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
        observation_thresholds=salvation.SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
        measurement_statuses=salvation.SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES,
        route_policy_version=salvation.SALVATION_ROUTE_POLICY_VERSION,route_threshold=salvation.SALVATION_ROUTE_THRESHOLD,
        final_projection_reconciled=True,missing_current_routed_block_ids=[])
    if any(raw.get(k)!=v for k,v in expected.items()):sal_reason='missing_or_incompatible_contract_policy_or_route_coverage'
    else:
        for b in raw.get('blocks',[]):
            topic=eligible.get(b['block_id'])
            if topic is None or not b.get('route',{}).get('route'):continue
            if (b['resolved_model_id']!=DEFAULT_TYPESAFE_MODEL or any(b[k]!=topic[k] for k in ('start_seconds','end_seconds','segment_indexes'))
                    or resolve_topic_block_context(b).get('target_text')!=resolve_topic_block_context(topic).get('target_text')):
                sal_reason='model_or_target_identity_differs';sal=[];break
            finite_probabilities(b['probabilities'],salvation.SALVATION_RELATIONSHIPS)
            observed=salvation.collected_salvation_relationships(b['probabilities'])
            if set(observed)!={x['relationship'] for x in b['observations']}:
                sal_reason='saved_observations_differ_from_frozen_thresholds';sal=[];break
            sal.append(dict(block_id=b['block_id'],probabilities={k:b['probabilities'][k] for k in salvation.SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS},
                observations=b['observations'],model=b['resolved_model_id']))
    expected_salvation_ids={key for key,b in eligible.items() if salvation.salvation_route_decision(b)['route']}
    if not sal_reason and {b['block_id'] for b in sal}!=expected_salvation_ids:
        sal_reason='current_route_and_measured_inventory_differ';sal=[]
    if len({b['block_id'] for b in treatment})!=len(treatment) or len({b['block_id'] for b in sal})!=len(sal):
        raise ValueError('Duplicate layer block IDs')
    return dict(eligible=eligible,treatment=treatment,treatment_reason=treatment_reason,salvation=sal,salvation_reason=sal_reason,
        absent_production_layers=['listener_directives','public_life_treatment','source_material'])


def select_profile(rows):
    groups=defaultdict(list)
    for row in rows:
        if row['status']=='compatible':groups[row['profile_id']].append(row)
    if not groups:raise ValueError('No compatible materialized segment evidence in bounded inventory')
    # Coverage, not positive answers, prominence or presumed pastor quality.
    return min(groups,key=lambda pid:(-sum(r['eligible_blocks'] for r in groups[pid]),-len(groups[pid]),pid))


def build(base_dir=None):
    paths=build_paths(base_dir);db=Database(paths.database,readonly=True)
    with db.connect() as connection:
        run_rows=[dict(r) for r in connection.execute("SELECT * FROM sermon_analysis_runs WHERE id IN (SELECT MAX(id) FROM sermon_analysis_runs WHERE analyzer_key=? AND analyzer_version=? GROUP BY video_id) ORDER BY id DESC LIMIT ?",
            (topics_projection.TOPIC_SERMON_ANALYZER_KEY,topics_projection.TOPIC_SERMON_ANALYZER_VERSION,MAX_SOURCES))]
    rows=[];data={};files={}
    for row in run_rows:
        video=db.get_video_by_id(row['video_id']);gate=assess_topic_profile_projection(db,video)
        basic=dict(run_id=row['id'],video_id=video.id,title=video.title,url=video.url,published_at=video.published_at,
            profile_id=gate.profile_id,gate=gate.to_dict(),status='excluded',reasons=list(gate.reason_codes))
        if gate.eligible:
            try:
                classification=topics_projection.read_classification_for_gate(gate)
                analysis=resolve_topic_analysis_artifact(classification);projection=analysis['sermon_projection']
                if topics_projection._sha256(analysis)!=gate.topic_analysis_fingerprint:
                    raise ValueError('Source changed during eligibility check')
                stored_current=(row['input_fingerprint']==topics_projection._sermon_input_fingerprint(gate,analyzer_version=topics_projection.TOPIC_SERMON_ANALYZER_VERSION) and row['source_content_sha256']==gate.topic_analysis_fingerprint)
                measurements=topics_projection._projection_measurements(projection)
                saved=topics_projection.load_topic_sermon_measurements(db,row['id'])
                stored_current=stored_current and saved['topic_measurements']==measurements and saved['topic_question_pack_version']==TOPIC_PACK_VERSION
                basic['materialized_projection_status']='current' if stored_current else 'stale_not_reused'
                basic['measurement_origin']='existing current source-artifact sermon_projection; no regeneration or database materialization'
                layers=compatible_layers(classification,analysis,projection['eligible_block_ids'])
                basic.update(status='compatible',eligible_blocks=len(layers['eligible']),treatment_blocks=len(layers['treatment']),
                    salvation_measured_blocks=len(layers['salvation']),treatment_gap=layers['treatment_reason'],salvation_gap=layers['salvation_reason'],
                    source_path=gate.source_path,source_sha256=trace.digest(gate.source_path),topic_pack=TOPIC_PACK_VERSION,model=DEFAULT_TYPESAFE_MODEL)
                files[gate.source_path]=basic['source_sha256'];data[video.id]=(measurements,layers)
            except (ValueError,KeyError,TypeError) as error:basic['reasons'].append(str(error))
        rows.append(basic)
    chosen=select_profile(rows);scope=resolve_profile_sermon_scope(db,chosen);profile=db.get_speaker_profile(chosen)
    sermons=[]
    for row in rows:
        if row['status']!='compatible' or row['profile_id']!=chosen:continue
        measurements,layers=data[row['video_id']]
        top=sorted(measurements,key=lambda k:(-measurements[k]['developed_emphasis_probability'],k))[:4]
        evidence=[]
        for topic in top:
            links=measurements[topic]['representative_blocks']
            candidate=next((link for link in links if link['block_id'] in layers['eligible']),None)
            if candidate is None:continue
            block=layers['eligible'][candidate['block_id']]
            evidence.append(dict(topic=topic,label=TOPIC_SPECS[topic].label,existing_sermon_measurement=measurements[topic],
                block_id=block['block_id'],start_seconds=block['start_seconds'],end_seconds=block['end_seconds'],segment_indexes=block['segment_indexes'],
                full_target_text=resolve_topic_block_context(block)['target_text'],scores=block['scores'][topic],
                support_scope='topical attention in this sermon, not an adopted doctrinal position',quote_extraction_performed=False))
        counts=Counter(x['relationship'] for b in layers['salvation'] for x in b['observations'])
        sermons.append(dict(**row,topic_examples=evidence,treatment=layers['treatment'],salvation=layers['salvation'],
            salvation_positive_observation_counts=dict(counts),eligible_block_ids=sorted(layers['eligible'])))
    report=seal(dict(version=VERSION,status='CACHED_SEGMENT_SLICE_INVENTORIED_NO_NEW_INFERENCE',
        scope='At most the latest 12 persisted version-1 topic runs, one latest materialization per video. Not a corpus scan or new collection.',
        candidates=rows,selected_profile=dict(id=chosen,display_label=profile.display_label,lifecycle_state=profile.lifecycle_state,
            created_reason=profile.created_reason,membership_fingerprint=profile_membership_fingerprint(db,scope),
            effective_member_video_ids=sorted(v.id for v in scope.videos),
            selection_rule='Most compatible eligible cached topic blocks in this bounded inventory, then sermon count, then lower profile ID; independent of positive answers.'),
        sermons=sermons,source_files=files,
        coverage=dict(cached_sources_considered=len(rows),compatible_sources=sum(r['status']=='compatible' for r in rows),
            stale_materializations_not_reused=sum(r.get('materialized_projection_status')=='stale_not_reused' for r in rows),
            sample_sermons=len(sermons),eligible_topic_blocks=sum(s['eligible_blocks'] for s in sermons),
            compatible_treatment_blocks=sum(s['treatment_blocks'] for s in sermons),salvation_measured_blocks=sum(s['salvation_measured_blocks'] for s in sermons),
            approved_salvation_leaves=list(salvation.SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS),
            unresolved_salvation_leaves=sorted(salvation.UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS),
            production_layers_not_present=['listener_directives','public_life_treatment','source_material']),
        supported_view='Per-sermon topical attention with segment links; cached treatment probabilities; nine-leaf salvation observations on routed targets. No new pastor-level averages, recurrence, stance or scoring.',
        gaps=['Current reviewed profile has no display label; video titles are supplied metadata, not accepted identity evidence.',
            'These source artifacts lack production listener-directive, public-life and source-material layers despite bounded question validation elsewhere.',
            'Salvation unrouted, below-threshold, unresolved and absent data must remain distinct; none establishes a negative pastor position.',
            'Raw cache compatibility is not a new source audit or proof that every positive judgment is correct.',
            'Only three selected sermons; no independent recurrence, period/series stability or comprehensive theology claim.',
            'Illustrative Ollama quotes remain downstream and unimplemented.'],
        recommendation='Build the first read-only segment-backed view from these existing observations and sources. Do not add a measurement just to extract quotes. Keep desired unsupported fields visibly unknown; missing enrichments can receive a separately bounded collection decision later.',
        implementation_files={str(Path(__file__)):trace.digest(__file__)},provider_requests=0,database_writes=0,
        new_profile_projection=False,new_collection=False,quote_execution=False))
    return report


def markdown(report):
    p=report['selected_profile'];cov=report['coverage'];lines=['# Cached segment evidence: bounded sample','',
        f"Reviewed profile **{p['id']}** (display label unavailable). {cov['sample_sermons']} sermons; {cov['eligible_topic_blocks']} eligible topic blocks; {cov['compatible_treatment_blocks']} compatible treatment blocks; {cov['salvation_measured_blocks']} routed salvation blocks.",'',
        'These are existing observations, not a newly inferred pastor theology or recurrence profile. Video titles remain source metadata.','',
        '| Sermon | Existing highest topic-attention measurements |','|---|---|']
    for s in report['sermons']:
        topics=', '.join(e['label'] for e in s['topic_examples'])
        lines.append(f"| [{s['title'].replace('|','/')} ]({s['url']}) | {topics} |")
    lines+=['','## Segment evidence examples','']
    for s in report['sermons']:
        lines += [f"### Video {s['video_id']}: {s['title']}",'']
        for e in s['topic_examples'][:2]:
            lines += [f"**{e['label']}** — block {e['block_id']}, {e['start_seconds']:.1f}–{e['end_seconds']:.1f}s. Existing sermon support-probability mean: {e['existing_sermon_measurement']['developed_emphasis_probability']:.3f}.",'',
                'Full target segment (source evidence, not a selected illustrative quotation):','', '> '+e['full_target_text'].replace('\n','\n> '),'']
        lines += ['Stored positive salvation observations on routed blocks: '+', '.join(f'{k}: {v}' for k,v in sorted(s['salvation_positive_observation_counts'].items()))+'.','']
    lines+=['## Reuse and gaps','']+['- '+gap for gap in report['gaps']]+['','Recommendation: '+report['recommendation'],'','Provider requests: **0**. Database writes: **0**. Quote extraction: **none**.','']
    return '\n'.join(lines)


def prepare(base_dir=None):
    report=build(base_dir);out=build_paths(base_dir).evaluation/VERSION/report['content_fingerprint'];out.mkdir(parents=True,exist_ok=True)
    path=out/'inventory-v1.json';raw=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if path.exists() and path.read_text()!=raw:raise ValueError('Immutable inventory differs')
    path.write_text(raw);(out/'sample-v1.md').write_text(markdown(report))
    return report,path
