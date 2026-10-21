"""Bounded read-only reuse of registered leaf answers; never assess or compose.

Question equality, not a version label, permits an individual/refinement leaf to
supply a current question. Raw probabilities remain unadmitted local evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.sermon_classification import TranscriptBlock
from pastor_transcript_extractor.sermon_classifier_typesafe import TypeSafeBlockCache
from pastor_transcript_extractor.sermon_leaf_packs import (
    LEAF_PACKS, LISTENER_DIRECTIVES, PUBLIC_LIFE_TREATMENT, SOURCE_MATERIAL,
)
from pastor_transcript_extractor.sermon_topics import (
    TopicBlockContext, resolve_topic_analysis_artifact, resolve_topic_block_context,
)

CURRENT = (LISTENER_DIRECTIVES, PUBLIC_LIFE_TREATMENT, SOURCE_MATERIAL)


def inspect(inventory, sources):
    checks = []
    for sermon in inventory['sermons']:
        cache = TypeSafeBlockCache(Path(sermon['source_path']).parent / 'inference-cache', model=sermon['model'])
        totals = {pack: dict(checked=0, compatible=0, incompatible=0) for pack in LEAF_PACKS}
        attempts, matches, observations = [], [], []
        analysis = resolve_topic_analysis_artifact(sources[sermon['video_id']]['classification'])
        eligible = set(sermon['eligible_block_ids'])
        for raw in analysis['blocks']:
            if raw['block_id'] not in eligible:
                continue
            context = resolve_topic_block_context(raw)
            block = TranscriptBlock(block_id=raw['block_id'], start_seconds=raw['start_seconds'],
                end_seconds=raw['end_seconds'], segment_indexes=raw['segment_indexes'], text=context['target_text'])
            target = TopicBlockContext(**context)
            expected_context = {**target.state_payload(), 'diagnostics': dict(target.diagnostics)}
            for pack, spec in LEAF_PACKS.items():
                identity = cache._pack_identity({}, block, pack=pack, role_context=None, topic_context=target)
                path = cache._pack_path(pack, identity)
                attempt = dict(block_id=block.block_id, pack=pack, path=str(path),
                    identity_fingerprint=seal(identity)['content_fingerprint'], state='absent_exact_identity')
                attempts.append(attempt)
                totals[pack]['checked'] += 1
                if not path.exists():
                    continue
                try:
                    payload = json.loads(path.read_text())
                    answer = payload['answer']
                    if payload['identity'] != identity:
                        raise ValueError('saved identity differs')
                    if not isinstance(answer, dict) or not cache._pack_payload_is_valid(pack, answer):
                        raise ValueError('malformed registered answer')
                    if answer.get('resolved_model_id') != sermon['model']:
                        raise ValueError('resolved model differs')
                    if answer['leaf_answer']['context'] != expected_context:
                        raise ValueError('answer context differs')
                    if not isinstance(answer.get('request_provenance'), dict):
                        raise ValueError('request provenance missing')
                except (OSError, ValueError, KeyError, TypeError) as error:
                    totals[pack]['incompatible'] += 1
                    attempt.update(state='incompatible', reason=str(error))
                    continue
                totals[pack]['compatible'] += 1
                attempt.update(state='compatible_saved_answer', sha256=trace.digest(path))
                matches.append(dict(attempt))
                for leaf, value in answer['leaf_answer']['probabilities'].items():
                    question = spec.questions(0)[spec.question_id(0, leaf)]
                    targets = [current.version for current in CURRENT if leaf in current.definitions and
                        question == current.questions(0)[current.question_id(0, leaf)]]
                    observations.append(dict(id=f'e-leaf-{sermon["video_id"]}-{block.block_id}-{pack}-{leaf}',
                        video_id=sermon['video_id'], block_id=block.block_id,
                        source_path=sermon['source_path'], source_sha256=sermon['source_sha256'],
                        start_seconds=block.start_seconds, end_seconds=block.end_seconds,
                        segment_indexes=list(block.segment_indexes), full_target_text=block.text,
                        watch_url=sermon['url']+('&' if '?' in sermon['url'] else '?')+'t='+str(int(block.start_seconds)),
                        layer='cached_leaf', field=leaf, value=value, state='measured_not_admitted',
                        meaning=spec.definitions[leaf], question_version=pack, question_digest=spec.digest(),
                        individual_question_fingerprint=seal(dict(question=question))['content_fingerprint'],
                        model=sermon['model'], cached_field='answer.leaf_answer.probabilities.'+leaf,
                        artifact_path=str(path), artifact_sha256=attempt['sha256'],
                        cache_identity_fingerprint=attempt['identity_fingerprint'],
                        request_provenance=answer['request_provenance'],
                        current_question_matches=targets,
                        reuse_status='current_question_equivalent' if targets else 'historical_semantics_only',
                        limit='Raw saved judgment only; no threshold, production admission, target binding or profile trait inferred.'))
        checks.append(dict(video_id=sermon['video_id'], path=str(cache.root),
            state='bounded_exact_registered_leaf_cache_check', packs=totals, matches=matches,
            attempts=attempts, observations=observations,
            limit='Exact registered full, individual/refinement and saved composed identities inspected independently. No inference, hydration, composition, migration or writes; absence is not a global cache census.'))
    return checks


GAP_REQUIREMENTS = {
    'adoption': ('proposition, evaluated target, voiced speaker, preacher adoption and attached conditions',
        'sermon_salvation_relationships.py and existing theological_binding.py upstream bound records'),
    'pastoral': ('listener act/recipient/proposition and circumstance/voice/adoption bindings',
        'sermon_leaf_packs.py listener-directive producer and existing G3 address records'),
    'scripture': ('argument relationship between cited passages and justified opportunity/frequency denominator',
        'sermon_analysis.py Scripture producer; profile_description.py compatible artifact exposure'),
    'style': ('validated prevalence interpretation with duration, dependence and missingness',
        'profile_description.py aggregation rules; existing sermon_semantic_dimensions.py observations'),
    'sampling': ('independent coverage across periods, settings and series', 'profile_analysis.py membership and coverage'),
    'identity': ('accepted display label', 'profile_analysis.py reviewed profile metadata'),
    'benchmark': ('approved comparison inputs, coverage rules and calibrated comparison meaning', 'future separately authorized comparison method'),
    'quotes': ('authorized excerpt selection and literal source location', 'held downstream quote selection and literal validator'),
}


def attach(record):
    checks = record['reuse_checks']
    supplied = [o for check in checks for o in check.get('observations', [])]
    # Several registered packs may persist the same unchanged question. Retain
    # immutable records but expose their dependence and disagreements explicitly.
    groups = {}
    for observation in supplied:
        key = (observation['video_id'], observation['block_id'], observation['individual_question_fingerprint'])
        groups.setdefault(key, []).append(observation)
    for values in groups.values():
        disagreement = len({o['value'] for o in values}) > 1
        for observation in values:
            observation['equivalent_question_observation_ids'] = [o['id'] for o in values]
            observation['supply_conflict'] = disagreement
            if disagreement:
                observation['reuse_status'] = 'conflicting_saved_answers_not_resolved'
    record['observations'].extend(supplied)
    record['evidence_supply'] = dict(version='profile-evidence-supply-v1',
        status='bounded_read_only_integration', provider_requests=0, cache_writes=0,
        supplied_observation_ids=[o['id'] for o in supplied],
        persisted_scripture=[c['scripture_payload'] for c in checks if c.get('scripture_payload')],
        inspected_reuse=[{k: v for k, v in check.items() if k != 'observations'} for check in checks],
        limit='Only exact supplied identities inspected. Compatible raw judgments are not new admitted measurements or adopted positions.')
    by_id = {o['id']: o for o in record['observations']}
    for claim in record['claims']:
        refs = list(dict.fromkeys(claim['evidence_ids']+claim.get('observation_input_ids', [])))
        claim['evidence_supply'] = dict(status='supplied_existing_materialized_observations',
            required_distinction=record['rules'][claim['rule']]['inputs'],
            producer={'topic': 'sermon_topics.py', 'salvation': 'sermon_salvation_relationships.py'}[claim['rule']],
            supplied_observation_ids=refs,
            inspected_reuse=[dict(observation_id=key, source_path=by_id[key]['source_path'],
                source_sha256=by_id[key]['source_sha256'], cached_field=by_id[key]['cached_field'],
                outcome='compatible_materialized_observation') for key in refs], missing_fields=[])
    for gap in record['gaps']:
        missing, owner = GAP_REQUIREMENTS[gap['id']]
        relevant = checks if gap['id'] in ('adoption', 'pastoral', 'scripture') else []
        gap['evidence_supply'] = dict(status='withheld_required_distinction_not_established',
            reader_point=gap['withheld'], required_distinction=missing, missing_fields=[missing],
            upstream_owner=owner,
            insertion_function={'adoption': 'theological_binding.bind / sermon_salvation_relationships.salvation_route_decision',
                'pastoral': 'sermon_leaf_packs.NoulLeafPack.questions',
                'scripture': 'sermon_analysis.prepare_sermon_analysis / profile_description.load',
                'style': 'profile_description.build', 'sampling': 'profile_analysis',
                'identity': 'profile_analysis', 'benchmark': 'separately held future comparison',
                'quotes': 'separately held downstream quotation workflow'}[gap['id']],
            not_inspected=([dict(path='other G1/G2/G3 persisted results', state='not_inspected',
                reason='Only the curated ten source-reviewed bindings and their existing G1/G2/G3 structures are checked; no general artifact census or automatic admission.')] if gap['id'] in ('adoption', 'pastoral') else []),
            inspected_reuse=[dict(video_id=c['video_id'], state=c['state'], path=c.get('path'),
                packs=c.get('packs'), matches=c.get('matches'), reason=c.get('reason'),
                limit=c.get('limit')) for c in relevant],
            available_observation_ids=[o['id'] for o in supplied] if gap['id'] in ('adoption', 'pastoral') else [],
            smallest_change=gap['remedy'], acceptance_check={
                'adoption': 'A source-bound proposition has independently evidenced voice, preacher use, polarity and qualifications; a reported/rejected control cannot become an adopted position.',
                'pastoral': 'A current-listener act has target evidence and an identified recipient; reported prayer and topic-only controls remain excluded; real listener circumstances remain unknown.',
                'scripture': 'Exact-current source-linked references are exposed under their own meaning; citation-only controls cannot establish cross-book argument or frequency.',
                'style': 'A proposed prevalence rule declares denominator, duration, dependence, missingness and contrary evidence; selected maxima alone cannot pass.',
                'sampling': 'Reviewed membership supplies independent period/setting/series coverage; duplicated or unverified dates cannot establish ministry stability.',
                'identity': 'Explicitly accepted display metadata is retained with decision provenance; recording titles alone cannot supply the label.',
                'benchmark': 'Separately approved comparison meaning and compatible coverage exist before any similarity or ranking is displayed.',
                'quotes': 'Separate authorization plus contiguous literal CENTER support and preserved attribution; removing the quote cannot change the claim.'}[gap['id']],
            authorization_boundary=gap['work_kind'])


def reviewed_bindings(record, sources):
    """Reuse curated authored bindings directly, without recursive pilot loaders.

    Frozen source/membership/context and contract identities must all match. These
    remain local proposals, including their original narrow G1 interpretation.
    """
    from pastor_transcript_extractor import profile_binding_pilot as pilot
    from pastor_transcript_extractor import profile_proposition_review as review
    from pastor_transcript_extractor import theological_binding
    from pastor_transcript_extractor.assurance_binding_adapter import interpret
    from pastor_transcript_extractor.binding_evidence import text_digest, context_digest
    authored = json.loads(review.READINGS_PATH.read_text())
    baseline = json.loads(pilot.READINGS_PATH.read_text())
    records, outcomes = [], []
    if authored['baseline_input_sha256'] != trace.digest(pilot.READINGS_PATH):
        raise ValueError('Frozen reviewed binding input changed')
    for path, digest in authored['reused_contracts'].items():
        if trace.digest(trace.ROOT / path) != digest:
            raise ValueError('Reviewed binding contract changed')
    for key in ('contract', 'composer'):
        if trace.digest(trace.ROOT / baseline[key+'_path']) != baseline[key+'_sha256']:
            raise ValueError('Frozen G1 contract changed')
    by_id = {o['id']: o for o in record['observations']}
    authored_by_id = {r['binding_id']: r for r in authored['readings']}
    for case in baseline['cases']:
        outcome = dict(path=str(review.READINGS_PATH), case_id=case['case_id'],
            evidence_id=case['evidence_id'], state='incompatible_reviewed_source_scope')
        outcomes.append(outcome)
        observation = by_id.get(case['evidence_id'])
        if (baseline['inventory_fingerprint'] != record['inventory_fingerprint'] or
            baseline['membership_fingerprint'] != record['profile'].get('membership_fingerprint') or
            observation is None or observation['source_sha256'] != case['source_sha256']):
            outcome['reason'] = 'Exact reviewed inventory, membership or supporting observation differs; no remapping.'
            continue
        analysis = resolve_topic_analysis_artifact(sources[observation['video_id']]['classification'])
        block = next(b for b in analysis['blocks'] if b['block_id'] == observation['block_id'])
        context = resolve_topic_block_context(block)
        texts = {key: context[key] for key in ('target_text', 'leading_context', 'trailing_context')}
        if (text_digest(context['target_text']) != case['target_sha256'] or
            text_digest(json.dumps(context, sort_keys=True, ensure_ascii=False)) != case['context_sha256']):
            outcome['reason'] = 'Reviewed target/context identity differs.'
            continue
        for original in case['readings']:
            provenance = dict(case_id=case['case_id'], video_id=observation['video_id'],
                block_id=observation['block_id'], source_sha256=observation['source_sha256'],
                target_sha256=text_digest(texts['target_text']), texts_sha256=context_digest(texts),
                source_inventory_fingerprint=record['inventory_fingerprint'],
                membership_fingerprint=record['profile']['membership_fingerprint'])
            binding = theological_binding.bind(texts, authored_by_id[original['id']], provenance)
            old = pilot.compile_reading(case['case_id'], texts, original)
            assurance = interpret(binding, texts, old)
            if assurance['g1_record'] != old['g1_record']:
                raise ValueError('Reused binding changed original G1 interpretation')
            records.append(dict(binding=binding, assurance_interpretation=assurance,
                evidence_id=observation['id'], status='source_reviewed_proposal_not_production_admission',
                reviewed_input_path=str(review.READINGS_PATH), reviewed_input_sha256=trace.digest(review.READINGS_PATH),
                original_g1_record_unchanged=True))
        outcome.update(state='compatible_reviewed_proposals_reused', count=len(case['readings']))
    record['evidence_supply']['reviewed_bound_records'] = records
    record['evidence_supply']['reviewed_input_identities'] = dict(
        authored_path=str(review.READINGS_PATH), authored_sha256=trace.digest(review.READINGS_PATH),
        baseline_path=str(pilot.READINGS_PATH), baseline_sha256=trace.digest(pilot.READINGS_PATH),
        reused_contracts=authored['reused_contracts'])
    record['evidence_supply']['reviewed_binding_checks'] = outcomes
    for gap in record['gaps']:
        if gap['id'] in ('adoption', 'pastoral'):
            gap['evidence_supply']['reviewed_binding_checks'] = outcomes
            gap['evidence_supply']['reviewed_proposal_ids'] = [r['binding']['binding_id'] for r in records]
            gap['evidence_supply']['limit'] = 'Compatible authored local proposals are inspectable; they do not supply general automatic coverage or production admission.'


def persisted_scripture(database, run, prepared):
    """Expose exact-current stored references/alignment without running detectors.

    The analysis uses identified-sermon segments, not the topic block projection;
    retain that source domain and do not turn references into block-level claims.
    """
    from dataclasses import asdict
    from pastor_transcript_extractor.sermon_analysis import ANALYZER_KEY, ANALYZER_VERSION
    if (run.input_fingerprint != prepared.input_fingerprint or
        run.source_content_sha256 != prepared.source_content_sha256 or
        run.source_path != str(prepared.source_path) or
        run.analyzer_key != ANALYZER_KEY or run.analyzer_version != ANALYZER_VERSION):
        raise ValueError('Persisted Scripture run differs from exact-current input')
    evidence = [asdict(row) for row in database.list_sermon_analysis_evidence(run.id)
        if row.evidence_kind in ('scripture_reference', 'scripture_text_alignment')]
    measurements = [asdict(row) for row in database.list_sermon_analysis_measurements(run.id)
        if row.metric_key.startswith(('scripture_', 'explicit_scripture_', 'contextual_scripture_',
            'distinct_scripture_', 'anchored_scripture_', 'independent_scripture_'))]
    for row in evidence:
        row['payload'] = json.loads(row.pop('payload_json'))
    for row in measurements:
        row['value'] = json.loads(row.pop('value_json'))
    return dict(state='compatible_persisted_scripture_payload_exposed',
        input_fingerprint=prepared.input_fingerprint, source_path=str(prepared.source_path),
        source_content_sha256=prepared.source_content_sha256,
        analyzer_key=run.analyzer_key, analyzer_version=run.analyzer_version,
        evidence=evidence, measurements=measurements,
        limit='Saved citation occurrences and text alignments on identified-sermon segments only. They are not cross-book reasoning, exposition frequency, adopted interpretation, or mapped eligible topic-block support.')
