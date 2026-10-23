"""One prepared cached case, using the existing profile assembly and readers.

Selection is deliberately bounded, not an arbitrary-profile generator. Authored
presentation inputs cannot supply missing voice/adoption or theological bindings.
"""
from copy import deepcopy
import json
from pathlib import Path

from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor import profile_description, profile_portrait, profile_presentation
from pastor_transcript_extractor import profile_supporting_blocks, profile_capability_review
from pastor_transcript_extractor import segment_cache_inventory
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths

VERSION = 'pastor-profile-portability-p1'
PROFILE_ID = 130
VIDEO_IDS = (1037, 350, 4430)
INPUT_PATH = Path(__file__).with_name('data') / 'profile-portability-130-v1.json'


def validate_selection(profile_id):
    if profile_id != PROFILE_ID:
        raise ValueError('Only prepared portability profile 130 is supported; omit --profile-id for preserved profile 318')


def readable_topics(reader):
    """Use the existing contract labels where the legacy reader falls back to IDs."""
    from pastor_transcript_extractor.sermon_topics import TOPIC_SPECS
    def label(text):
        for key, spec in TOPIC_SPECS.items():
            text = text.replace(key.replace('_', ' '), spec.label.replace('&', 'and'))
        return text
    for claim in reader['claims']:
        claim['wording'] = label(claim['wording'])
        if claim['id'] == 'reader-shared-emphases' and sum(len(v) == len(reader['titles']) for v in reader['shared_topic_membership'].values()) == 1:
            claim['wording'] = claim['wording'].replace(' form a shared focus.', ' forms a shared focus of topical attention.')
    for row in reader['at_a_glance']:
        row['description'] = label(row['description'])


def assemble(inventory, sources, checks, packet):
    if inventory['selected_profile']['id'] != PROFILE_ID or {s['video_id'] for s in inventory['sermons']} != set(VIDEO_IDS):
        raise ValueError('Foreign portability sample')
    record = profile_description.build(inventory, sources, checks, source_reviews=packet)
    reader = record['reader']
    # The legacy authoring packets are exact-point guarded. None may transfer.
    if reader['portrait']['entries'] or record['evidence_supply']['reviewed_bound_records']:
        raise ValueError('Unexpected foreign portrait/binding reuse')
    readable_topics(reader)
    topic_paragraphs = [[(c['wording'], c['id'])] for c in reader['claims'] if c['id'] in reader['emphasis_claim_ids']]
    profile_portrait.apply(reader, packet['portrait'])
    reader['assessment'].extend(topic_paragraphs)
    reader['title'] = 'Pastor profile 130 · selected recordings'
    reader['assessment_scope'] = packet['portrait']['scope_note']
    entries = {e['id']: e for e in reader['portrait']['entries']}
    reader['at_a_glance'] += [dict(label=label, description=text, target=target, claim_ids=[target] if target in entries else []) for label, text, target in (
        ('Apparent theological center', 'Unknown: topic attention and local relationship observations do not establish adopted theology.', 'gap-adoption'),
        ('Potential strength', entries.get('p130-strength', {}).get('text', 'Unknown: reviewed support unavailable.'), 'p130-strength' if 'p130-strength' in entries else 'gap-style'),
        ('Question for review', entries.get('p130-question', {}).get('text', 'Unknown: reviewed support unavailable.'), 'p130-question' if 'p130-question' in entries else 'gap-scripture'))]
    # Practical-application examples cannot establish the recipient, adoption or tone.
    for row in reader['at_a_glance']:
        if row['label'] == 'Pastoral approach':
            row.update(description='Pastoral posture remains unknown. A practical-application example is available; listener-directed meaning has not been bound.', target='gap-pastoral', claim_ids=[])
    record['assessment'] = deepcopy(reader['assessment'])
    record['version'] = VERSION
    record['authoring_disclosure'] = dict(author='Codex manual source inspection and authored warrants; Brian acceptance pending',
        input_path=str(INPUT_PATH), input_sha256=trace.digest(INPUT_PATH),
        style_reviews=[r['evidence_id'] for r in packet['reviews']],
        portrait_interpretations=[e['id'] for e in reader['portrait']['entries']],
        unknown_facets=['adopted theological center', 'pastoral posture'],
        automatic_discovery=False, new_semantic_bindings=0)
    for gap in record['gaps']:
        supply = gap['evidence_supply']
        supply['inspected_reuse'].append(dict(path='selected source artifacts and observation ledger',
            state='compatible_existing_topic_treatment_salvation_observations',
            observation_count=len(record['observations']),
            limit='Local probabilities and topic attention cannot supply adoption, listener binding, prevalence or audience outcomes.'))
        if gap['id'] == 'adoption':
            gap['withheld'] = 'An apparent adopted theological center and a complete account of affirmed beliefs'
            gap['cause'] = 'No compatible reviewed bound record was supplied for this sample. Topic attention and nine local salvation leaves do not establish voiced speaker, preacher adoption, polarity or attached qualifications; three leaves remain unresolved.'
            gap['reuse'] = 'The three selected source projections, exact registered full/individual/refinement/composed leaf paths, exact-current Scripture runs and the curated reviewed binding packet were inspected. See per-path outcomes; the binding packet is incompatible with profile 130, not globally absent.'
            supply['reader_point'] = gap['withheld']
            supply['smallest_change'] = 'After a separate decision, prepare one existing upstream source-bound reading for a specific center-relevant proposition, preserving voice, adoption, polarity, conditions and full context. Until then leave the center unknown; no general theological extractor or new measurement is needed for this delivery.'
        if gap['id'] == 'pastoral':
            gap['cause'] = 'Compatible raw leaf answers and a reviewed application example are available, but no compatible reviewed address binding establishes act, recipient, circumstance, voice or adoption. They cannot establish pastoral posture.'
            supply['smallest_change'] = 'After a separate decision, integrate a compatible saved listener answer with its existing upstream act/recipient/voice/adoption binding if available. Otherwise prepare one bounded address record at that producer, preserving unknown circumstances; do not infer tone from practical application.'
    record['supporting_examples'] = profile_supporting_blocks.build(record)
    capability = deepcopy(record['capability_review']); capability.pop('content_fingerprint', None)
    capability['consequential_gaps'] = deepcopy(record['gaps'])
    capability['first_scope'] = 'Profile 130, only recordings 1037 / 350 / 4430 from the existing bounded inventory; no other membership is sampled.'
    record['capability_review'] = seal(capability)
    return seal(record)


def load(base_dir=None, profile_id=PROFILE_ID):
    validate_selection(profile_id)
    inventory = segment_cache_inventory.build(base_dir, profile_id=PROFILE_ID, video_ids=VIDEO_IDS)
    sources = {}
    for sermon in inventory['sermons']:
        if trace.digest(sermon['source_path']) != sermon['source_sha256']:
            raise ValueError('Selected source changed during loading')
        sources[sermon['video_id']] = trace.read(sermon['source_path'])
    checks = profile_description.leaf_reuse_checks(inventory, sources)
    # Same exact-current Scripture lookup as the baseline; never execute a detector.
    from pastor_transcript_extractor.sermon_analysis import prepare_sermon_analysis
    from pastor_transcript_extractor.profile_evidence_supply import persisted_scripture
    from pastor_transcript_extractor.storage import Database
    database = Database(build_paths(base_dir).database, readonly=True)
    for vid in VIDEO_IDS:
        try:
            prepared = prepare_sermon_analysis(database, database.get_video_by_id(vid))
            run = database.get_sermon_analysis_run_by_fingerprint(prepared.input_fingerprint)
            checks.append(dict(video_id=vid, path='exact-current sermon-basics input fingerprint',
                state='compatible_persisted_scripture_payload_exposed' if run else 'no_exact_current_persisted_run',
                scripture_payload=persisted_scripture(database, run, prepared) if run else None,
                run_id=run.id if run else None, input_fingerprint=prepared.input_fingerprint,
                limit='References/alignments retain their identified-sermon domain; not argument relationships or frequency. Older artifacts not globally inspected.'))
        except ValueError as error:
            checks.append(dict(video_id=vid, state='current_scripture_input_unavailable', reason=str(error)))
    return assemble(inventory, sources, checks, json.loads(INPUT_PATH.read_text()))


def prepare(base_dir=None, profile_id=PROFILE_ID):
    record = load(base_dir, profile_id)
    modules = (profile_description, profile_presentation, profile_portrait, profile_supporting_blocks,
               profile_capability_review, segment_cache_inventory)
    from pastor_transcript_extractor import profile_evidence_supply, profile_explanatory_descriptions, profile_sample_patterns, segment_profile_view
    modules += (profile_evidence_supply, profile_explanatory_descriptions, profile_sample_patterns, segment_profile_view)
    files = {str(Path(m.__file__)): trace.digest(m.__file__) for m in modules}
    files.update({str(Path(__file__)):trace.digest(__file__), str(INPUT_PATH):trace.digest(INPUT_PATH)})
    manifest = seal(dict(version=VERSION, description=record, implementation_files=files, provider_requests=0, database_writes=0))
    out = build_paths(base_dir).evaluation / VERSION / manifest['content_fingerprint']
    disclosure = record['authoring_disclosure']
    review = seal(dict(version=VERSION+'-review', status='READY_FOR_BRIAN_REVIEW_NOT_PRODUCTION_ADMISSION',
        description_fingerprint=record['content_fingerprint'], manifest_fingerprint=manifest['content_fingerprint'],
        reused_automatically=dict(observations=len(record['observations']), coverage=record['coverage'],
            supplied_leaf_answers=len(record['evidence_supply']['supplied_observation_ids']),
            reviewed_bindings=len(record['evidence_supply']['reviewed_bound_records']),
            scripture_payloads=len(record['evidence_supply']['persisted_scripture'])),
        authored_interpretation=disclosure, consequential_gaps=record['gaps'],
        provider_requests=0, database_writes=0, new_measurements=False, quote_execution=False))
    disclosure_text = ('## Manual authoring disclosure\n\nCodex manually read and authored '+str(len(disclosure['style_reviews']))+
        ' local style descriptions and '+str(len(disclosure['portrait_interpretations']))+' cross-point interpretations. '+
        'These are pending Brian’s acceptance. No local theological or listener/adoption bindings were authored. '+
        'Theological center and pastoral posture remain unknown. Full authoring inputs and exact support are in the companion JSON.\n\n')
    md = profile_description.markdown(record)
    md = md.replace('## Pastor at a glance', disclosure_text+'## Pastor at a glance', 1)
    page = profile_description.render(record)
    notice = '<p class="note">Manual authoring: Codex supplied '+str(len(disclosure['style_reviews']))+' local style descriptions and '+str(len(disclosure['portrait_interpretations']))+' cross-point interpretations; Brian acceptance pending. No theological or listener/adoption bindings were authored. Inspect the reasoning below.</p>'
    page = page.replace('<h2>Pastor at a glance</h2>', notice+'<h2>Pastor at a glance</h2>', 1)
    gap_summary = ['# Consequential gaps: profile 130', '',
        'Reuse: '+str(record['coverage']['eligible_topic_blocks'])+' compatible topic blocks, '+str(record['coverage']['compatible_treatment_blocks'])+' treatment blocks, '+str(record['coverage']['salvation_measured_blocks'])+' routed salvation blocks and '+str(len(record['evidence_supply']['supplied_observation_ids']))+' raw leaf observations. Compatible reviewed bindings: '+str(len(record['evidence_supply']['reviewed_bound_records']))+'; exact-current persisted Scripture payloads: '+str(len(record['evidence_supply']['persisted_scripture']))+'. Other G1/G2/G3 stores were not inventoried. Raw leaf answers are not adopted positions or listener bindings.', '',
        '| Blocked statement | Responsible producer | Smallest next step |', '|---|---|---|']
    gap_summary += ['| '+g['withheld'].replace('|','/')+' | '+g['evidence_supply']['upstream_owner']+' | '+g['evidence_supply']['smallest_change'].replace('|','/')+' |' for g in record['gaps']]
    gap_md = '\n'.join(gap_summary)+'\n\nThe detailed records below retain inspected paths, missing fields, acceptance checks and authorization boundaries. No remedy is automatically authorized.\n\n'+profile_capability_review.markdown(record['capability_review'])
    review_md = '# P1 profile 130 review\n\n'+disclosure_text+'Automatically reused: '+str(len(record['observations']))+' observations; '+str(len(record['evidence_supply']['supplied_observation_ids']))+' exact cached leaf observations; '+str(len(record['evidence_supply']['reviewed_bound_records']))+' compatible reviewed bindings.\n\n'+gap_md
    artifacts = {'index.html':page, 'profile-p1.md':md, 'description-p1.json':json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',
        'review-p1.json':json.dumps(review,ensure_ascii=False,indent=2)+'\n', 'review-p1.md':review_md,
        'consequential-gaps-p1.json':json.dumps(record['capability_review'],ensure_ascii=False,indent=2)+'\n',
        'consequential-gaps-p1.md':gap_md}
    out.mkdir(parents=True, exist_ok=True)
    for name, raw in artifacts.items():
        path = out/name
        if path.exists() and path.read_text()!=raw:
            raise ValueError('Immutable portability artifact differs')
        path.write_text(raw)
    return manifest, out/'index.html'
