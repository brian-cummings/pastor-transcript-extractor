"""Provider-free descriptive presentation of reviewed, source-bound observations.

No profile scores, prevalence estimates, stance inference, or semantic admission.
All selection rules describe the cached answers, not a new pastor measurement.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import html
import json
from pathlib import Path

from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor import segment_profile_view as evidence_view
from pastor_transcript_extractor import segment_cache_inventory as cache_inventory
from pastor_transcript_extractor import sermon_salvation_relationships as salvation
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.sermon_topics import resolve_topic_analysis_artifact, resolve_topic_block_context
from pastor_transcript_extractor.sermon_semantic_dimensions import SEMANTIC_ANALYSIS_QUESTION_VERSION, SEMANTIC_DIMENSIONS

VERSION = 'pastor-profile-description-v1'
RULE_VERSION = 'cached-observation-wording-v1'
FAMILIES = ('Preaching style', 'Theological emphasis', 'Theological orientation', 'Pastoral/rhetorical orientation')
RULES = {
    'topic': dict(inputs='Existing per-sermon developed_emphasis_probability and representative eligible blocks',
        selection='Reuse the inventoried four highest per-sermon attention measurements, in stored order. No new cutoff or pooling.',
        wording='Among the highest stored topic-attention measurements; never doctrine, belief, agreement or ministry priorities.',
        missing='Withhold if no eligible representative exists; do not substitute an adjacent topic.'),
    'treatment': dict(inputs='Compatible local treatment probabilities for eligible segments',
        selection='One maximum-probability candidate per dimension per recording; ties use earliest time, then block ID. No positive threshold.',
        wording='Candidate for source inspection only. Maximum is not admission, frequency, predominance or quality.',
        missing='Mark unmeasured; a low maximum remains a candidate with its raw probability, never a negative trait.'),
    'salvation': dict(inputs='Compatible routed local nine-leaf probabilities and frozen observation thresholds',
        selection='List leaves with existing admitted local observations; retain every measured block, including below-threshold states.',
        wording='Cached segments register local observations of the named relationship. No adoption, polarity or opposing scale inferred.',
        missing='Separate unrouted, missing compatible routed result, below threshold, and unresolved leaf. None is doctrinal denial.'),
}


TOPIC_DISPLAY = {
    'god_character_action': 'God’s character, will and action',
    'jesus_person_work': 'the person and work of Jesus Christ',
    'holy_spirit_person_work': 'the person and work of the Holy Spirit',
}
SALVATION_DISPLAY = {
    'divine_grace_initiative': 'God’s unearned grace supplying salvation',
    'atonement_as_basis': 'Christ’s saving work as the basis of salvation',
    'forgiveness_pardon': 'divine forgiveness as a saving benefit',
    'justification_right_standing': 'justification and right standing with God',
    'conversion_new_birth': 'entry into saving life through conversion or new birth',
    'sanctification_transformation': 'transformation as part of God’s saving work',
    'assurance_security': 'assurance and security concerning salvation',
    'judgment_final_destiny': 'judgment and final saving destiny',
    'faith_as_receiving_response': 'faith as the response receiving a saving benefit',
}


def prose_list(values):
    return ', '.join(values[:-1])+', and '+values[-1] if len(values) > 1 else values[0]


@dataclass(frozen=True)
class Claim:
    id: str
    wording: str
    family: str
    scope: dict
    support_state: str
    rule: str
    evidence_ids: list[str]
    uncertainty: str
    observation_input_ids: list[str] = field(default_factory=list)
    counterevidence_ids: list[str] = field(default_factory=list)
    code_responsibility: str = 'profile_description.build: deterministic selection and source-linked wording'
    interpretation_status: str = 'proposed descriptive rule; reviewable, not semantic admission'
    rule_version: str = RULE_VERSION


@dataclass(frozen=True)
class Gap:
    id: str
    priority: int
    family: str
    withheld: str
    cause: str
    reuse: str
    remedy: str
    work_kind: str
    reader_impact: str


def gap_ledger():
    return [asdict(g) for g in (
        Gap('adoption', 1, FAMILIES[2], 'Affirmed theological positions and relationships between obedience, repentance and salvation',
            'Topic attention and local relationship judgments do not bind proposition, voice, polarity and adoption; three leaves are unresolved.',
            'Reuse the nine admitted local salvation leaves, preserving their meanings. Existing G1/G2/G3/A1 contracts retain their historical scopes.',
            'Review compatible proposition/voice/polarity evidence for a specific desired claim; separately authorize any missing semantic measurement. Keep unresolved leaves withheld.',
            'semantic distinction / separate authorization', 'Prevents turning discussion, reported views or low probabilities into the pastor’s beliefs.'),
        Gap('scripture', 1, FAMILIES[0], 'Strongly Bible-centered; frequent cross-book reasoning',
            'Local exposition probabilities do not establish frequency or the relationship between passages.',
            'Check exact-current persisted sermon-basics Scripture runs before new work; reference mentions and text alignments have narrower meanings than cross-book reasoning.',
            'Expose compatible references/alignments if available. Any cross-book argument or frequency conclusion needs its own justified interpretation, not a count proxy.',
            'existing evidence exposure / interpretation', 'Distinguishes explaining a text from merely mentioning many references.'),
        Gap('pastoral', 1, FAMILIES[3], 'Reassurance versus warning, characteristic appeals, certainty, individual versus communal orientation',
            'Application treatment does not supply listener/act/proposition bindings in these materialized sources.',
            'Reuse practical_application locally. Full-pack cache misses do not rule out individual-leaf or composed answers. Legacy migration supports role/treatment only; leaf composition requires identical questions, context and model.',
            'Inspect exact compatible leaf identities for the chosen claim before any refill; compose only compatible existing answers through a separately reviewed integration. Do not run cache assess or a provider.',
            'evidence integration / semantic distinction', 'Avoids labeling relational posture from an application proxy.'),
        Gap('style', 2, FAMILIES[0], 'Predominant style or High/Moderate/Low traits',
            'Local probabilities and selected maxima are not prevalence, quality, or pastor scores.',
            'All compatible local treatment observations are retained, including lower values.',
            'Review candidate source windows; separately justify any descriptive prevalence rule with missingness, duration and dependence handling.',
            'interpretation / held aggregation', 'The reader can inspect examples without an invented summary scale.'),
        Gap('sampling', 1, 'All families', 'Stable ministry tendencies or comprehensive theology',
            'This bounded development sample does not establish independence across series, periods or settings.',
            'Preserve reviewed membership, titles, dates where available and exact sample coverage.',
            'Keep the sample scope. Additional independent coverage requires a separate collection decision.',
            'sampling / separate authorization', 'Prevents selected, potentially correlated recordings from standing for a ministry.'),
        Gap('identity', 2, 'Identity', 'Accepted pastor display name',
            'Reviewed profile lacks a display label; recording titles are unaccepted identity metadata.',
            'Expose reviewed membership and source titles as provenance, without converting titles into accepted identity.',
            'Brian can approve a bounded metadata label using the displayed provenance; no automatic attribution rule.',
            'metadata decision', 'Makes the profile recognizable without silently accepting a new identity.'),
        Gap('benchmark', 2, 'Benchmark', 'Nearest benchmark, similarity percentage or ranking',
            'No compatible benchmark inputs, dimensional comparison method, coverage rules or calibrated meaning.',
            'Preserve supported dimensional descriptions and unknowns; none is a comparison input by default.',
            'Design and validate comparison separately, declaring overlap and exclusions. Keep comparison unavailable now.',
            'comparability / separate authorization', 'Avoids a persuasive but uninterpretable rank or percentage.'),
        Gap('quotes', 3, 'Presentation', 'Illustrative quotation',
            'No downstream quote selection or literal-location verification has been executed.',
            'Complete eligible source segments already support inspection; no minimal utterance extraction is needed.',
            'Only after separate authorization, use configured Ollama with real BEFORE/CENTER/AFTER blocks and deterministic contiguous-text verification.',
            'presentation / held Ollama execution', 'Quotations could improve readability but cannot create analytical authority.'),
    )]


def build(inventory, sources, reuse_checks=None):
    """Pure assembly. Recheck layer identity so saved presentation cannot admit stale data."""
    if seal(inventory) != inventory:
        raise ValueError('Invalid inventory seal')
    lower = evidence_view.build_view(inventory, sources)
    observations = []
    claims = []
    candidates = []
    states = []
    sample_ids = [s['video_id'] for s in inventory['sermons']]
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError('Duplicate recording')
    for sermon in inventory['sermons']:
        vid = sermon['video_id']
        classification = sources[vid]['classification']
        analysis = resolve_topic_analysis_artifact(classification)
        layers = cache_inventory.compatible_layers(classification, analysis, sermon['eligible_block_ids'])
        for key in ('treatment', 'salvation'):
            if layers[key] != sermon[key]:
                raise ValueError('Inventoried layer differs from current source')
        blocks = layers['eligible']
        if set(sermon['eligible_block_ids']) != set(analysis['sermon_projection']['eligible_block_ids']):
            raise ValueError('Inventoried eligibility differs from source projection')
        ordered = sorted(blocks.values(), key=lambda b: (b['start_seconds'], b['block_id']))
        if len(set(sermon['eligible_block_ids'])) != len(sermon['eligible_block_ids']):
            raise ValueError('Duplicate eligible block')
        if any(a['end_seconds'] > b['start_seconds'] for a, b in zip(ordered, ordered[1:])):
            raise ValueError('Overlapping eligible segments; resolve source geometry before describing')
        for b in ordered:
            if b['start_seconds'] >= b['end_seconds']:
                raise ValueError('Invalid segment bounds')
        scope = dict(video_ids=[vid], meaning='Only eligible segments of this recording')

        def observe(block_id, layer, field, value, state, metadata):
            block = blocks[block_id]
            identifier = f'e-{vid}-{block_id}-{layer}-{field}'
            observations.append(dict(id=identifier, video_id=vid, block_id=block_id,
                source_path=sermon['source_path'], source_sha256=sermon['source_sha256'],
                start_seconds=block['start_seconds'], end_seconds=block['end_seconds'],
                segment_indexes=block['segment_indexes'], full_target_text=resolve_topic_block_context(block)['target_text'],
                watch_url=evidence_view.source_url(sermon['url'], block['start_seconds']),
                layer=layer, field=field, value=value, state=state,
                cached_field=f'classification.search.{dict(topic="topic_analysis", treatment="semantic_analysis", salvation="salvation_relationship_analysis")[layer]}.blocks[block_id={block_id}].'+('scores.' if layer == 'topic' else 'probabilities.')+field, **metadata))
            return identifier

        topic_ids = []
        labels = []
        topic_inputs = []
        counter_ids = []
        for example in sermon['topic_examples']:
            # Inventory measurements are already from the source projection; compare via its existing decoder.
            current = cache_inventory.topics_projection._projection_measurements(analysis['sermon_projection'])[example['topic']]
            if current != example['existing_sermon_measurement']:
                raise ValueError('Inventoried topic measurement differs')
            labels.append(TOPIC_DISPLAY.get(example['topic'], example['label'].lower().replace('&', 'and')))
            for block in ordered:
                identifier = observe(block['block_id'], 'topic', example['topic'], block['scores'][example['topic']], 'measured',
                dict(question_version=analysis['question_pack_version'], question_digest=analysis['question_pack_digest'],
                     model=sermon['model'], measurement=current,
                     meaning='Per-sermon mean P(topic at least supporting), with representative source window; attention, not stance.'))
                topic_inputs.append(identifier)
                if block['block_id'] == example['block_id']:
                    topic_ids.append(identifier)
                if any(c['block_id'] == block['block_id'] for c in current['counterevidence_blocks']):
                    counter_ids.append(identifier)
        if topic_ids:
            claims.append(asdict(Claim(f'c-topic-{vid}',
                f'“{evidence_view.short_title(sermon["title"])}” (recording {vid}) gives attention to '+prose_list(labels)+
                '. These subjects appear among its highest stored measures of topical attention. They do not establish agreement with every view discussed.',
                FAMILIES[1], scope, 'supported_cached_description', 'topic', topic_ids,
                'The representative windows illustrate the stored summaries, not every minute. Topic attention cannot distinguish a quoted view from an adopted one.',
                observation_input_ids=topic_inputs, counterevidence_ids=counter_ids)))

        treatments = {b['block_id']: b for b in layers['treatment']}
        for dimension, meaning in SEMANTIC_DIMENSIONS.items():
            refs = []
            for block in sorted(treatments.values(), key=lambda b: b['block_id']):
                refs.append(observe(block['block_id'], 'treatment', dimension, block['probabilities'][dimension], 'measured',
                    dict(question_version=SEMANTIC_ANALYSIS_QUESTION_VERSION, model=block['model'], meaning=meaning)))
            if refs:
                best = min((o for o in observations if o['id'] in set(refs)),
                    key=lambda o: (-o['value'], o['start_seconds'], o['block_id']))
                candidates.append(dict(video_id=vid, dimension=dimension, evidence_id=best['id'],
                    status='inspection_candidate_only', wording='Candidate for '+dimension.replace('_', ' ')+
                    '; no positive threshold, predominance or frequency inferred.'))
        measured = {b['block_id'] for b in layers['salvation']}
        for block_id in blocks:
            routed = salvation.salvation_route_decision(blocks[block_id])['route']
            states.append(dict(video_id=vid, block_id=block_id,
                state='measured' if block_id in measured else 'missing_compatible_routed_result' if routed else 'unrouted_unmeasured'))
        positive = {}
        for block in layers['salvation']:
            for leaf, probability in block['probabilities'].items():
                threshold = salvation.SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS[leaf]
                state = 'observed' if probability >= threshold else 'measured_below_threshold'
                identifier = observe(block['block_id'], 'salvation', leaf, probability, state,
                    dict(model=block['model'], question_version=salvation.SALVATION_RELATIONSHIPS_PACK_VERSION,
                        question_digest=salvation.salvation_relationship_pack_digest(),
                        observation_policy=salvation.SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
                        threshold=threshold, route_policy=salvation.SALVATION_ROUTE_POLICY_VERSION,
                        route_threshold=salvation.SALVATION_ROUTE_THRESHOLD,
                        meaning=salvation.SALVATION_RELATIONSHIP_SPECS[leaf].description))
                if state == 'observed':
                    positive.setdefault(leaf, []).append(identifier)
        for leaf, refs in positive.items():
            claims.append(asdict(Claim(f'c-salvation-{vid}-{leaf}',
                f'Recording {vid} has cached local observations of '+salvation.SALVATION_RELATIONSHIP_SPECS[leaf].description+'.',
                FAMILIES[2], scope, 'supported_local_observation', 'salvation', refs,
                'Local observation only: no automatic adopted position, polarity, frequency or ministry-level tendency. Below-threshold blocks are retained in the evidence ledger.')))
    gaps = sorted([g for g in gap_ledger() if g['id'] != 'identity' or not inventory['selected_profile'].get('display_label')], key=lambda g: (g['priority'], g['id']))
    dimensions = []
    for family in FAMILIES:
        ids = [c['id'] for c in claims if c['family'] == family]
        has_local = bool(ids) or (bool(candidates) if family == FAMILIES[0] else any(c['dimension'] == 'practical_application' for c in candidates) if family == FAMILIES[3] else False)
        dimensions.append(dict(family=family, status=('measured_per_recording_attention' if ids else 'unmeasured') if family == FAMILIES[1] else ('measured_local_only' if has_local else 'unmeasured'),
            description={FAMILIES[0]: 'Inspect candidate windows for exposition, doctrinal argument, narrative illustration and practical application. Predominant style remains unknown.',
                FAMILIES[1]: 'The named recordings have different topic-attention summaries; read the assessment for each recording.',
                FAMILIES[2]: 'Local salvation relationships are inspectable; adopted positions and unresolved relationships remain unknown.',
                FAMILIES[3]: 'Local practical-application probabilities are available. Relational posture and characteristic listener appeals remain unknown.'}[family],
            claim_ids=ids, candidate_ids=[c['evidence_id'] for c in candidates if family == FAMILIES[0] or (family == FAMILIES[3] and c['dimension'] == 'practical_application')],
            gap_ids=[g['id'] for g in gaps if g['family'] in (family, 'All families')]))
    return seal(dict(version=VERSION, rule_version=RULE_VERSION, rules=RULES, profile=inventory['selected_profile'],
        inventory_fingerprint=inventory['content_fingerprint'], coverage=inventory['coverage'],
        source_identity=[dict(video_id=s['video_id'], title=s['title'], source_sha256=s['source_sha256'], source_path=s['source_path'], gate=s['gate']) for s in inventory['sermons']],
        scope=f'{len(sample_ids)} selected development recordings, not a representative ministry sample.',
        source_audit_of_all_raw_judgments=False, interpretation_status='proposed descriptive rules for human review',
        assessment_claim_ids=[c['id'] for c in claims if c['rule'] == 'topic'], claims=claims,
        dimensions=dimensions, treatment_candidates=candidates, observations=observations,
        salvation_block_states=states, unresolved_leaves=inventory['coverage']['unresolved_salvation_leaves'],
        benchmark=dict(status='unavailable', reason='Comparison not yet established; no compatible benchmark method or calibration.'),
        gaps=gaps, reuse_checks=reuse_checks or [], evidence_view=lower,
        provider_requests=0, database_writes=0, new_measurements=False, profile_scores=False, quote_execution=False))


def load(base_dir=None):
    inventory, sources = evidence_view.load(base_dir)
    # Read-only lookup of exact-current Scripture runs; no detector, alignment or aggregation execution.
    from pastor_transcript_extractor.sermon_analysis import prepare_sermon_analysis
    from pastor_transcript_extractor.storage import Database
    database = Database(build_paths(base_dir).database, readonly=True)
    checks = []
    for sermon in inventory['sermons']:
        try:
            prepared = prepare_sermon_analysis(database, database.get_video_by_id(sermon['video_id']))
            run = database.get_sermon_analysis_run_by_fingerprint(prepared.input_fingerprint)
            checks.append(dict(video_id=sermon['video_id'], path='exact-current sermon-basics input fingerprint',
                state='compatible_persisted_run_available_not_yet_exposed' if run else 'no_exact_current_persisted_run',
                run_id=run.id if run else None, input_fingerprint=prepared.input_fingerprint,
                limit='No inference of cross-book reasoning or frequency; no assertion that older artifacts are absent.'))
        except ValueError as error:
            checks.append(dict(video_id=sermon['video_id'], state='current_scripture_input_unavailable', reason=str(error)))
    checks.extend(leaf_reuse_checks(inventory, sources))
    return build(inventory, sources, checks)


def leaf_reuse_checks(inventory, sources):
    """Bounded exact-path reads of all registered leaf packs, including refinements.

    Never call assess, hydrate or compose: those interfaces can write or infer.
    Full-pack, individual-leaf and previously composed packs share this identity
    path; role/treatment-only legacy hydration cannot supply new leaf semantics.
    """
    from pastor_transcript_extractor.sermon_classifier_typesafe import TypeSafeBlockCache
    from pastor_transcript_extractor.sermon_classification import TranscriptBlock
    from pastor_transcript_extractor.sermon_leaf_packs import LEAF_PACKS
    from pastor_transcript_extractor.sermon_topics import TopicBlockContext
    checks = []
    for sermon in inventory['sermons']:
        cache = TypeSafeBlockCache(Path(sermon['source_path']).parent / 'inference-cache', model=sermon['model'])
        totals = {pack: dict(checked=0, compatible=0, incompatible=0) for pack in LEAF_PACKS}
        matches = []
        analysis = resolve_topic_analysis_artifact(sources[sermon['video_id']]['classification'])
        eligible = set(sermon['eligible_block_ids'])
        for raw in analysis['blocks']:
            if raw['block_id'] not in eligible:
                continue
            context = resolve_topic_block_context(raw)
            block = TranscriptBlock(block_id=raw['block_id'], start_seconds=raw['start_seconds'],
                end_seconds=raw['end_seconds'], segment_indexes=raw['segment_indexes'], text=context['target_text'])
            target = TopicBlockContext(leading_context=context['leading_context'], target_text=context['target_text'],
                trailing_context=context['trailing_context'], diagnostics=context['diagnostics'])
            for pack in LEAF_PACKS:
                identity = cache._pack_identity({}, block, pack=pack, role_context=None, topic_context=target)
                path = cache._pack_path(pack, identity)
                totals[pack]['checked'] += 1
                if not path.exists():
                    continue
                try:
                    payload = json.loads(path.read_text())
                    answer = payload['answer']
                    compatible = (payload['identity'] == identity and cache._pack_payload_is_valid(pack, answer)
                        and answer.get('resolved_model_id') == sermon['model'])
                except (OSError, ValueError, KeyError, TypeError):
                    compatible = False
                totals[pack]['compatible' if compatible else 'incompatible'] += 1
                if compatible:
                    matches.append(dict(block_id=block.block_id, pack=pack, path=str(path), sha256=trace.digest(path)))
        checks.append(dict(video_id=sermon['video_id'], path=str(cache.root),
            state='bounded_exact_registered_leaf_cache_check', packs=totals, matches=matches,
            limit='Includes historical refinements and any composed answers at exact registered identities; not a global cache census. No cache writes or refill. Legacy migration only supplies role/treatment, already present here. Compatible leaf answers require separate integration within their admitted semantics.'))
    return checks


def assessment(record):
    """Paragraphs of claim-linked text; no independent, unlinked narrative assertions."""
    by_id = {c['id']: c for c in record['claims']}
    paragraphs = [[(by_id[key]['wording'], key)] for key in record['assessment_claim_ids']]
    leaves = {}
    for claim in record['claims']:
        if claim['rule'] == 'salvation':
            field = next(o['field'] for o in record['observations'] if o['id'] == claim['evidence_ids'][0])
            leaves.setdefault(field, []).append(claim['id'])
    if record['treatment_candidates']:
        selected = {}
        for candidate in record['treatment_candidates']:
            selected.setdefault(candidate['dimension'], candidate['evidence_id'])
        paragraphs.append([(('For preaching style, the available evidence consists of local judgments about ' if index == 0 else '')+dimension.replace('_', ' ')+('.' if index == len(selected)-1 else ';'), key) for index, (dimension, key) in enumerate(selected.items())]+[('These links open candidate source windows for inspecting how a point is developed. A strongest cached candidate is not a measure of frequency or predominance; the sample’s predominant style remains unknown.', 'gap-style')])
    if leaves:
        paragraphs.append([(('In the routed segments, cached local salvation observations concern ' if index == 0 else '')+
            SALVATION_DISPLAY[leaf]+('.' if index == len(leaves)-1 else ';'), ids[0]) for index, (leaf, ids) in enumerate(sorted(leaves.items()))])
    return paragraphs


def render(record):
    e = lambda value: html.escape(str(value), quote=True)
    link = lambda key, label: f'<a href="#{e(key)}">{e(label)}</a>'
    shell = evidence_view.render(record['evidence_view'])
    head = shell.split('<body>')[0].replace('Segment evidence · profile 318', f'Pastor profile · {record["profile"]["id"]}')
    script = shell[shell.index('<script>'):]
    paragraphs = ''.join('<p class="lead">'+' '.join(e(text)+' '+link(key, 'evidence ↗') for text, key in paragraph)+'</p>' for paragraph in assessment(record))
    rows = ''.join('<tr><th>'+e(d['family'])+'</th><td>'+e(d['description'])+' '+
        link('family-'+str(FAMILIES.index(d['family'])), 'Inspect this dimension')+'</td><td>'+e(d['status'].replace('_', ' '))+'</td></tr>' for d in record['dimensions'])
    claim_cards = []
    for claim in record['claims']:
        refs = ' '.join(link(key, key) for key in claim['evidence_ids'])
        inputs = ' '.join(link(key, key) for key in claim['observation_input_ids'])
        contrary = ' '.join(link(key, key) for key in claim['counterevidence_ids'])
        claim_cards.append(f'<details id="{e(claim["id"])}"><summary>{e(claim["wording"])}</summary>'
            f'<p>Scope: {e(claim["scope"])} · Support: {e(claim["support_state"])}</p>'
            f'<p>{e(claim["uncertainty"])}</p><p>Rule: {e(claim["rule"])} / {e(claim["rule_version"])}. '
            f'{e(claim["interpretation_status"])}</p><p>Supporting observations: {refs}</p></details>')
    family_sections = []
    for d in record['dimensions']:
        family_sections.append('<section class="sermon" id="family-'+str(FAMILIES.index(d['family']))+'"><h2>'+e(d['family'])+'</h2><p>'+e(d['description'])+'</p>'+
            ''.join('<p>'+link(c['evidence_id'], f'Recording {c["video_id"]}: {c["wording"]}')+'</p>' for c in record['treatment_candidates'] if c['evidence_id'] in d['candidate_ids'])+
            ('<details><summary>Read the supported local claims</summary>'+''.join('<p>'+link(key, next(c['wording'] for c in record['claims'] if c['id'] == key))+'</p>' for key in d['claim_ids'])+'</details>' if d['claim_ids'] else '')+
            '<p>Unknowns: '+' · '.join(link('gap-'+key, key) for key in d['gap_ids'])+'</p></section>')
    gap_cards = ''.join(f'<article id="gap-{e(g["id"])}"><h3>Priority {g["priority"]}: {e(g["withheld"])}</h3>'
        f'<p>{e(g["cause"])}</p><p>Why it matters: {e(g["reader_impact"])}</p><p>Reuse: {e(g["reuse"])}</p>'
        f'<p>Smallest remedy: {e(g["remedy"])}</p><p class="sub">{e(g["work_kind"])}</p></article>' for g in record['gaps'])
    reverse = {}
    for c in record['claims']:
        for key in set(c['evidence_ids'] + c['observation_input_ids'] + c['counterevidence_ids']):
            reverse.setdefault(key, []).append(c['id'])
    windows = {}
    for o in record['observations']:
        windows.setdefault((o['video_id'], o['block_id']), []).append(o)
    source_sections = []
    for s in record['source_identity']:
        windows_html = []
        for (vid, block_id), values in windows.items():
            if vid != s['video_id']:
                continue
            first = values[0]
            measures = []
            for o in values:
                metadata = {k: v for k, v in o.items() if k not in ('id', 'video_id', 'block_id', 'full_target_text', 'source_path', 'source_sha256', 'watch_url', 'segment_indexes', 'start_seconds', 'end_seconds')}
                back = ' '.join(link(key, 'supports claim') for key in reverse.get(o['id'], []))
                candidate = any(c['evidence_id'] == o['id'] for c in record['treatment_candidates'])
                measures.append(f'<details id="{e(o["id"])}"><summary>{e(o["field"].replace("_", " "))} · {e(o["state"].replace("_", " "))}'+
                    (' · inspection candidate' if candidate else '')+f'</summary><p>{back or "No narrative claim admitted from this observation."}</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{e(json.dumps(metadata, ensure_ascii=False, indent=2))}</pre></details>')
            windows_html.append(f'<article class="salblock"><h3>Block {e(block_id)} · {e(evidence_view.timestamp(first["start_seconds"]))}–{e(evidence_view.timestamp(first["end_seconds"]))}</h3>'
                f'<p><a href="{e(first["watch_url"])}" target="_blank" rel="noopener noreferrer">Open recording at segment</a></p>'
                f'<details><summary>Full eligible transcript window and measurements</summary><div class="source">{e(first["full_target_text"])}</div>'+''.join(measures)+'</details></article>')
        source_sections.append(f'<section class="sermon" data-video="{s["video_id"]}"><h2>Recording {s["video_id"]}: {e(s["title"])}</h2>'
            f'<details><summary>Source identity and eligibility</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{e(json.dumps(s, ensure_ascii=False, indent=2))}</pre></details>'+''.join(windows_html)+'</section>')
    filters = ''.join(f'<button type="button" data-filter="{s["video_id"]}">Recording {s["video_id"]}</button>' for s in record['source_identity'])
    # Anchor navigation opens all containing disclosures and reveals filtered recordings.
    navigation = '''<script>
function revealEvidence(){const target=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(!target)return;
document.querySelectorAll('.sermon[data-video]').forEach(s=>s.hidden=false);
document.querySelectorAll('button[data-filter]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.filter==='all'?'true':'false'));
let p=target;while(p){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}target.scrollIntoView();}
window.addEventListener('hashchange',revealEvidence);window.addEventListener('load',revealEvidence);
</script>'''
    return (head+'<body><main><span class="eyebrow">PASTOR TRANSCRIPT EXTRACTOR · READABLE PROFILE</span>'+
        f'<h1>Pastor profile {e(record["profile"]["id"])}</h1><p class="notice">{e(record["scope"])} '
        f'Reviewed display label: {e(record["profile"].get("display_label") or "not yet accepted")}. Recording titles are source metadata. '
        'This describes cached attention and local observations; it does not establish adopted positions or stable ministry tendencies.</p>'+
        '<h2>Assessment of this sample</h2>'+ (paragraphs or '<p>No supported descriptive claims are available.</p>')+
        '<h2>Pastor at a glance</h2><div class="tablewrap"><table><tr><th>Family</th><th>Sample description</th><th>Coverage</th></tr>'+rows+'</table></div>'+
        '<section class="sermon"><h2>Benchmark comparison</h2><p>'+e(record['benchmark']['reason'])+'</p></section>'+
        '<h2>Dimensional analysis</h2>'+''.join(family_sections)+
        '<section class="sermon"><h2>Why PTE says this · claim ledger</h2>'+''.join(claim_cards)+
        '<details><summary>Interpretation rules and coverage</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+e(json.dumps(dict(rules=record['rules'], coverage=record['coverage'],
            salvation_block_states=record['salvation_block_states'], unresolved_leaves=record['unresolved_leaves']), indent=2))+'</pre></details></section>'+
        '<section class="sermon"><h2>Consequential gaps and code map</h2>'+gap_cards+
        '<details><summary>Existing evidence reuse checks</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+e(json.dumps(record['reuse_checks'], indent=2))+'</pre></details></section>'+
        '<h2>Sermons and full source segments</h2><p>Filters apply to the source browser; the assessment always describes the complete declared sample. '
        'Below threshold is a measured state, not denial. Unrouted means unmeasured; unresolved leaves are unavailable.</p>'+
        '<nav aria-label="Filter recordings"><button type="button" data-filter="all" aria-pressed="true">All recordings</button>'+filters+'</nav>'+''.join(source_sections)+
        '<footer>No new model calls, database writes, measurements, scores or quotations. Raw compatibility does not certify each judgment. '
        'Inventory '+e(record['inventory_fingerprint'])+' · Description '+e(record['content_fingerprint'])+'</footer></main>'+navigation+script)


def markdown(record):
    lines = [f'# Pastor profile {record["profile"]["id"]}', '', record['scope'], '',
        'Display label: '+str(record['profile'].get('display_label') or 'not yet accepted; titles remain metadata')+'.', '', '## Assessment', '']
    for paragraph in assessment(record):
        lines += [' '.join(text+f' [Evidence](index.html#{key})' for text, key in paragraph), '']
    lines += ['## At a glance', '', '| Family | Sample description | State |', '|---|---|---|']
    lines += [f'| {d["family"]} | {d["description"]} | {d["status"]} |' for d in record['dimensions']]
    lines += ['', '## Benchmark comparison', '', record['benchmark']['reason'], '', '## Claim ledger', '']
    for c in record['claims']:
        lines += [f'### {c["id"]}', '', c['wording'], '', f'Rule: {c["rule"]} / {c["rule_version"]}. Scope: {c["scope"]}.', '', c['uncertainty'], '',
            ' '.join(f'[Observation {key}](index.html#{key})' for key in c['evidence_ids']), '']
    lines += ['## Consequential gaps / code map', '']
    for g in record['gaps']:
        lines += [f'### P{g["priority"]}: {g["withheld"]}', '', g['cause'], '', 'Reader impact: '+g['reader_impact'], '',
            'Reuse: '+g['reuse'], '', 'Smallest remedy: '+g['remedy'], '', 'Work kind: '+g['work_kind'], '']
    lines += ['## Reproducibility', '', 'The companion description-v1.json contains every observation, its full source window, question/model/version and applicable threshold. HTML links work in both directions.', '',
        'Provider requests: 0. Database writes: 0. New measurements: none. Quotations: none.', '', '```json', json.dumps(dict(reuse_checks=record['reuse_checks'], rules=record['rules'], coverage=record['coverage']), indent=2), '```', '']
    return '\n'.join(lines)


def prepare(base_dir=None):
    record = load(base_dir)
    manifest = seal(dict(version=VERSION, description=record, implementation_files={
        str(Path(__file__)): trace.digest(__file__),
        str(Path(evidence_view.__file__)): trace.digest(evidence_view.__file__)}, provider_requests=0, database_writes=0))
    out = build_paths(base_dir).evaluation / VERSION / manifest['content_fingerprint']
    out.mkdir(parents=True, exist_ok=True)
    review = seal(dict(version=VERSION+'-review', status='READY_FOR_HUMAN_REVIEW',
        description_fingerprint=record['content_fingerprint'], manifest_fingerprint=manifest['content_fingerprint'],
        claim_count=len(record['claims']), observation_count=len(record['observations']), gap_count=len(record['gaps']),
        coverage=record['coverage'], provider_requests=0, database_writes=0, new_measurements=False,
        source_audit_of_all_raw_judgments=False, interpretation_status=record['interpretation_status'],
        check_command='pte analysis structure-readiness --segment-view --description --check-only --json',
        review_command='pte analysis structure-readiness --segment-view --description --json',
        held=['providers/models', 'broader collection', 'new semantic measurements', 'scoring/ranking/comparison', 'production activation', 'ministry stability', 'Ollama quotations']))
    artifacts = {'review-v1.json': json.dumps(review, ensure_ascii=False, indent=2)+'\n',
        'description-v1.json': json.dumps(manifest, ensure_ascii=False, indent=2)+'\n',
        'profile-v1.md': markdown(record), 'index.html': render(record)}
    for name, raw in artifacts.items():
        path = out / name
        if path.exists() and path.read_text() != raw:
            raise ValueError('Immutable description artifact differs')
        path.write_text(raw)
    return manifest, out / 'index.html'
