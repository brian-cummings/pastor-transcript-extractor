"""Reader-facing synthesis over unchanged profile observations.

Counts below describe membership in the already selected sermon summaries, never
minute prevalence or ministry stability. Authored style examples are tied to exact
source windows; an unreviewed probability cannot admit a style description.
"""
from __future__ import annotations

import hashlib
import html
import json
from collections import defaultdict
from pathlib import Path

from pastor_transcript_extractor.segment_profile_view import short_title, timestamp

VERSION = 'pastor-profile-reader-v6'
EDITORIAL_PATH = Path(__file__).with_name('data') / 'profile-reader-editorial-v1.json'
REVIEWS_PATH = Path(__file__).with_name('data') / 'profile-presentation-source-reviews-v2.json'
TOPICS = {
    'god_character_action': 'God’s character and action',
    'sin_fallenness_human_need': 'sin and human need',
    'discipleship_spiritual_formation': 'discipleship and spiritual growth',
    'ethics_moral_conduct': 'moral conduct',
    'society_public_life': 'society and public life',
    'spiritual_conflict_unseen_realm': 'spiritual conflict',
}
THEMES = {
    'divine_grace_initiative': 'God’s grace and initiative',
    'faith_as_receiving_response': 'salvation received through faith',
    'sanctification_transformation': 'transformation and holiness',
    'judgment_final_destiny': 'judgment and final destiny',
    'atonement_as_basis': 'Christ’s saving work',
    'forgiveness_pardon': 'forgiveness',
    'conversion_new_birth': 'conversion and new birth',
    'justification_right_standing': 'right standing with God',
    'assurance_security': 'assurance and security of salvation',
}
STYLES = {
    'exegetical_exposition': 'explanation of biblical passages',
    'doctrinal_argument': 'reasoning about Christian belief',
    'narrative_illustration': 'storytelling and personal illustration',
    'practical_application': 'practical application',
}
GAPS = {
    'adoption': ('A complete account of the preacher’s affirmed beliefs', 'The reviewed local proposals distinguish particular statements, speakers and uses. They do not establish complete coverage of affirmed beliefs across these sermons. Some relationships between repentance, obedience and salvation remain unresolved.', 'Use the scoped local readings where available; retain broader conclusions as unknown.'),
    'scripture': ('How the preacher builds arguments across the Bible', 'Explaining a passage does not establish how often the preacher reasons across books or how central Scripture is across a ministry.', 'Use any current Scripture evidence first. A stronger conclusion needs a clear meaning and supporting passages.'),
    'pastoral': ('Characteristic appeals and relational tone', 'Practical guidance is visible in individual passages. It does not yet establish a characteristic balance of reassurance, warning or other listener appeals.', 'Describe the supported passages locally; retain the broader pastoral assessment as unknown.'),
    'style': ('A dominant preaching style', 'Examples show ways a point is developed. They do not tell us which approach predominates.', 'Review the examples as examples; do not turn them into a frequency or quality score.'),
    'sampling': ('Whether this pattern holds across the ministry', 'The selected sermons are a small development sample, not independently sampled coverage of a ministry.', 'Keep this assessment scoped to these sermons. Broader collection requires a separate decision.'),
    'identity': ('The confirmed speaker name', 'The sermon titles supply a name, but the reviewed speaker identity has not yet been labeled.', 'Use the displayed source titles for a bounded identity decision; do not silently confirm a name.'),
    'benchmark': ('Comparison with other preachers', 'A meaningful comparison method and comparable evidence have not yet been established.', 'Keep similarity percentages, rankings and nearest-preacher claims unavailable.'),
    'quotes': ('Short illustrative quotations', 'Complete source passages are available. Short quotations have not been selected.', 'Quotation selection through Ollama remains a separately authorized later step.'),
}


def phrase_list(values):
    if len(values) < 2:
        return values[0] if values else ''
    return ', '.join(values[:-1]) + (' and ' if len(values) == 2 else ', and ') + values[-1]


def load_reviews():
    return json.loads(REVIEWS_PATH.read_text())


def build_reader(record, reviews=None):
    reviews = reviews or {}
    sources = {s['video_id']: s for s in record['source_identity']}
    titles = {vid: short_title(s['title']) for vid, s in sources.items()}
    observations = {o['id']: o for o in record['observations']}
    n = len(sources)
    claims = []

    def add(key, text, refs, reason, upstream=()):
        # Each clause is a statement about this sample, with explicit underlying inputs.
        refs = list(dict.fromkeys(refs))
        if not refs or any(key not in observations for key in refs):
            raise ValueError('Reader claim lacks current evidence')
        claims.append(dict(id=key, wording=text, evidence_ids=refs, upstream_claim_ids=list(upstream),
            reason=reason, scope=dict(video_ids=sorted({observations[key]['video_id'] for key in refs}),
                meaning='Only the selected sermons; no ministry-wide tendency or adopted position.'),
            rule_version=VERSION, rule_id=key,
            interpretation_status='proposed descriptive wording; reviewable, not semantic admission'))
        return key

    # Distinct sermons, not segment counts: reproduce membership in existing summaries.
    topic_groups = defaultdict(dict)
    for claim in record['claims']:
        if claim['rule'] != 'topic':
            continue
        for key in claim['evidence_ids']:
            o = observations[key]
            topic_groups[o['field']][o['video_id']] = key
    labels = {o['field']: TOPICS.get(o['field'], o['field'].replace('_', ' ')) for o in observations.values() if o['layer'] == 'topic'}
    shared = sorted((k for k, members in topic_groups.items() if n > 1 and len(members) == n))
    recurring = sorted((k for k, members in topic_groups.items() if 1 < len(members) < n))
    topic_reason = 'These subjects appear in the existing leading-topic summary of each named sermon. This describes attention, not agreement or the whole ministry.'
    assessment = []
    emphasis_keys = []
    if shared:
        text = 'Across these sermons, '+phrase_list([labels[k] for k in shared])+' form a shared focus.'
        key = add('reader-shared-emphases', text, [ref for k in shared for ref in topic_groups[k].values()], topic_reason,
            [c['id'] for c in record['claims'] if c['rule'] == 'topic'])
        emphasis_keys.append(key)
    if recurring:
        key = add('reader-recurring-emphases', 'The sample also returns to '+(', as well as '.join(labels[k] for k in recurring) if len(recurring) == 2 else phrase_list([labels[k] for k in recurring]))+'.',
            [ref for k in recurring for ref in topic_groups[k].values()], topic_reason)
        emphasis_keys.append(key)
    variations = []
    variation_refs = []
    for vid in sources:
        unique = next((k for k, members in topic_groups.items() if set(members) == {vid}), None)
        if unique:
            variations.append(labels[unique]+' in “'+titles[vid]+'”')
            variation_refs.append(topic_groups[unique][vid])
    if variations:
        key = add('reader-range', 'The subjects vary, including '+phrase_list(variations)+'.', variation_refs, topic_reason)
        emphasis_keys.append(key)
    if not emphasis_keys and topic_groups:
        key = add('reader-emphases', 'The subjects receiving attention include '+phrase_list([labels[k] for k in topic_groups])+'.',
            [ref for members in topic_groups.values() for ref in members.values()], topic_reason)
        emphasis_keys.append(key)

    # A source inspection receipt describes an example, not automatic semantic admission.
    inspected = []
    for review in reviews.get('reviews', []):
        o = observations.get(review['evidence_id'])
        if o is None:
            continue
        expected = dict(video_id=o['video_id'], block_id=o['block_id'], dimension=o['field'],
            source_sha256=o['source_sha256'], start_seconds=o['start_seconds'], end_seconds=o['end_seconds'],
            target_sha256=hashlib.sha256(o['full_target_text'].encode()).hexdigest())
        if o['layer'] != 'treatment' or any(review.get(k) != v for k, v in expected.items()):
            continue
        inspected.append(review)
    by_style = {r['dimension']: r for r in inspected if r['dimension'] in STYLES}
    style_key = None
    if by_style:
        style_key = add('reader-style', 'The preaching includes '+phrase_list([STYLES[k] for k in STYLES if k in by_style])+'.',
            [r['evidence_id'] for r in inspected if r['dimension'] in STYLES],
            'The linked passages were read in full and described within the existing treatment meanings. They establish examples, not a dominant style or frequency.',
            ())
    # Lead with the preacher’s observed way of developing a point, when actually supported.
    if all(k in by_style for k in ('exegetical_exposition', 'doctrinal_argument', 'practical_application')):
        key = add('reader-overview', 'In this '+{1:'one', 2:'two', 3:'three'}.get(n, str(n))+'-sermon sample, there are examples of biblical passage explanation, reasoning about Christian belief and practical guidance.',
            [r['evidence_id'] for r in inspected if r['dimension'] in ('exegetical_exposition', 'doctrinal_argument', 'practical_application')],
            'Separately source-reviewed examples show these approaches within the sample; co-occurrence does not establish a connected argument. This does not rate the preacher’s quality or establish a ministry-wide pattern.')
        assessment.append([(next(c['wording'] for c in claims if c['id'] == key), key)])
    if emphasis_keys:
        assessment.append([(next(c['wording'] for c in claims if c['id'] == key), key) for key in emphasis_keys])
    if style_key:
        assessment.append([(next(c['wording'] for c in claims if c['id'] == style_key)+' A dominant style is not yet established.', style_key)])

    # Collapse repeated local relationship records into one row per theme, retaining every source.
    themes = []
    for field, label in THEMES.items():
        matched = [o for o in observations.values() if o['layer'] == 'salvation' and o['field'] == field and o['state'] == 'observed']
        if not matched:
            continue
        vids = sorted({o['video_id'] for o in matched})
        text = 'The theme of '+label+' appears in '+('all '+str(n)+' sermons' if n > 1 and len(vids) == n else phrase_list(['“'+titles[v]+'”' for v in vids]))+'.'
        key = add('reader-salvation-'+field, text, [o['id'] for o in matched],
            'The existing salvation findings identify a relationship discussed in these passages. They do not resolve whether a view is affirmed, explained, quoted or rejected.',
            [c['id'] for c in record['claims'] if c['rule'] == 'salvation' and c['evidence_ids'][0] in {o['id'] for o in matched}])
        themes.append(dict(theme=field, label=label, video_ids=vids, claim_id=key,
            seen_in='All '+str(n)+' sermons' if n > 1 and len(vids) == n else phrase_list([titles[v] for v in vids])))
    common_themes = [t for t in themes if n > 1 and len(t['video_ids']) == n]
    if common_themes:
        key = add('reader-salvation-summary', 'Salvation is discussed in all '+str(n)+' sermons in connection with '+phrase_list([t['label'] for t in common_themes])+'.',
            [key for t in common_themes for c in claims if c['id'] == t['claim_id'] for key in c['evidence_ids']],
            'Each listed theme has existing support in each selected sermon. This is a count of sermons with support, not intensity, agreement, a new doctrinal position or a stable tendency.')
        assessment.append([(next(c['wording'] for c in claims if c['id'] == key)+' The evidence identifies these themes but cannot yet reliably distinguish the preacher’s affirmed positions from views being explained or quoted.', key)])
    elif themes:
        assessment.append([(next(c['wording'] for c in claims if c['id'] == t['claim_id']), t['claim_id']) for t in themes[:3]])

    named_sources = {}
    for item in reviews.get('title_metadata', []):
        source = sources.get(item['video_id'])
        name = item['speaker_name_in_title']
        if source and source['source_sha256'] == item['source_sha256'] and name in source['title']:
            named_sources[item['video_id']] = name
    names = list(named_sources.values())
    name = names[0] if n and set(named_sources) == set(sources) and len(set(names)) == 1 else None
    accepted = record['profile'].get('display_label')
    identity = 'Source titles identify the speaker as '+name+'. The speaker name has not yet been confirmed.' if name and not accepted else 'The speaker name has not yet been confirmed.' if not accepted else 'Confirmed speaker label: '+accepted+'.'
    short_styles = dict(exegetical_exposition='Biblical explanation', doctrinal_argument='Doctrinal reasoning', narrative_illustration='Illustration', practical_application='Practical application')
    style_description = ' + '.join(short_styles[k] for k in short_styles if k in by_style)+'. No dominant mode established.' if by_style else 'Style not yet established from reviewed passages.'
    emphasis_description = phrase_list([labels[k] for k in shared+recurring]) if shared+recurring else 'See the supported subjects below; a shared emphasis is not established.'
    salvation_description = phrase_list([t['label'] for t in common_themes]) if common_themes else 'See the themes and named sermons below; a shared salvation emphasis is not established.'
    pastoral = 'Practical application is present; characteristic appeals and relational tone are not yet established.' if 'practical_application' in by_style else 'Characteristic listener appeals and relational tone are not yet established.'
    rows = [dict(label='Preaching style', description=style_description, target='dimension-style'),
        dict(label='Major emphases', description=emphasis_description, target='dimension-emphases'),
        dict(label='Salvation', description=salvation_description, target='dimension-salvation'),
        dict(label='Pastoral approach', description=pastoral, target='dimension-pastoral'),
        dict(label='Confidence', description='Preliminary — based on '+str(n)+' selected sermons. Not a ministry-wide assessment.', target='gap-sampling')]
    from pastor_transcript_extractor.profile_sample_patterns import build as build_patterns
    patterns = build_patterns(record, claims)
    for claim in claims:
        upstream = [c for c in record['claims'] if c['id'] in claim['upstream_claim_ids'] or set(c['evidence_ids']) & set(claim['evidence_ids'])]
        claim['upstream_claim_ids'] = list(dict.fromkeys(claim['upstream_claim_ids'] + [c['id'] for c in upstream]))
        claim['observation_input_ids'] = list(dict.fromkeys(claim['evidence_ids'] + [ref for c in upstream for ref in c.get('observation_input_ids', [])]))
        claim['counterevidence_ids'] = list(dict.fromkeys(ref for c in upstream for ref in c.get('counterevidence_ids', [])))
        claim['recording_support'] = {str(vid): [ref for ref in claim['evidence_ids'] if observations[ref]['video_id'] == vid] for vid in sources}
    for row in rows:
        row['claim_ids'] = (emphasis_keys if row['label'] == 'Major emphases' else [t['claim_id'] for t in themes] if row['label'] == 'Salvation' else [style_key] if style_key and row['label'] in ('Preaching style', 'Pastoral approach') else [])
    reader = dict(version=VERSION, title=accepted or 'Pastor assessment', identity_note=identity,
        sample_note=str(n)+' selected sermons · preliminary assessment', assessment=assessment,
        claims=claims, at_a_glance=rows, themes=themes, sample_patterns=patterns, titles=titles, source_reviews=inspected,
        emphasis_claim_ids=emphasis_keys, style_claim_id=style_key,
        shared_topic_membership={k: sorted(v) for k, v in topic_groups.items()},
        synthesis_rule='Distinct sermon membership in existing inventoried topic summaries and approved local salvation findings; no pooling of minutes, new cutoff, intensity score, adoption or ministry recurrence.')

    return _explain_existing_points(record, reader)

def _explain_existing_points(record, reader):
    """Render existing authored explanations, never interpret an unreviewed passage."""
    from pastor_transcript_extractor.profile_explanatory_descriptions import build
    descriptions = build(record, reader)
    reader['explanatory_descriptions'] = descriptions
    points = descriptions['points']
    observations = {o['id']: o for o in record['observations']}
    existing = list(reader['claims'])
    for point in points:
        local = point['kind'] == 'reviewed_binding'
        wording = point['explanation']
        if local:
            wording = 'Reviewed local proposal: ' + wording
        claim = dict(id=point['point_id'], wording=wording,
            evidence_ids=list(point['evidence_ids']), reviewed_binding_ids=list(point['reviewed_binding_ids']),
            description_point_id=point['point_id'], analytical_basis='source_reviewed_local_proposal' if local else 'source_reviewed_style_example',
            reason='This explanation reuses the existing authored reading of the linked passage. '+('It remains a local proposal, not a production finding.' if local else 'It describes this example, not the prevalence or quality of a preaching method.'),
            scope=dict(video_ids=point['video_ids'], meaning='Selected source-reviewed passages only.'),
            rule_version=VERSION, rule_id='existing-authored-description',
            interpretation_status=point['status'], qualifications=list(point['qualifications']),
            upstream_claim_ids=list(dict.fromkeys(c['id'] for c in existing if set(c['evidence_ids']) & set(point['evidence_ids']))),
            observation_input_ids=list(point['evidence_ids']), counterevidence_ids=list(point['counterevidence_ids']),
            recording_support={str(vid): [key for key in point['evidence_ids'] if observations[key]['video_id'] == vid] for vid in reader['titles']})
        point['claim_id'] = claim['id']
        reader['claims'].append(claim)
    style = [p for p in points if p['kind'] == 'style']
    local = [p for p in points if p['kind'] == 'reviewed_binding']
    if points:
        # Representative existing accounts, not a new ranking or inferred sermon outline.
        overview = []
        if style:
            methods = [(p['explanation'], p['claim_id']) for p in style if p.get('dimension') != 'practical_application']
            if methods:
                overview.append(methods)
            practical = [p for p in style if p.get('dimension') == 'practical_application']
            if practical:
                overview.append([(p['explanation'], p['claim_id']) for p in practical])
        represented = set()
        for point in local:
            if any(vid not in represented for vid in point['video_ids']):
                overview.append([(local_account(point), point['claim_id'])])
                represented.update(point['video_ids'])
        # Broad topic/theme membership remains below, alongside these concrete accounts.
        if overview:
            reader['assessment'] = overview
        for row in reader['at_a_glance']:
            chosen = []
            if row['label'] == 'Preaching style':
                chosen = [p for p in style if p.get('dimension') != 'practical_application'][:1]
            elif row['label'] == 'Salvation':
                chosen = local[:1]
            elif row['label'] == 'Pastoral approach':
                chosen = [p for p in style if p.get('dimension') == 'practical_application']
            if chosen:
                row['description'] = ' '.join(('Reviewed local proposal: ' if p['kind'] == 'reviewed_binding' else '')+p['descriptor'] for p in chosen)
                row['claim_ids'] = [p['claim_id'] for p in chosen]
                row['target'] = chosen[0]['claim_id']
    return _apply_reviewed_editorial(reader)


def _apply_reviewed_editorial(reader, entries=None):
    """Use authored wording only for an exact unchanged reviewed point.

    The full point pins evidence, frame, qualifications, unknowns and source identity.
    No point is reinterpreted or admitted; unmatched inputs keep the fuller wording.
    """
    entries = json.loads(EDITORIAL_PATH.read_text())['entries'] if entries is None else entries
    by_id = {item['point_id']: item for item in entries}
    points = reader['explanatory_descriptions']['points']
    accepted = {}
    withheld = []
    for point in points:
        item = by_id.get(point['point_id'])
        if item is None:
            continue
        original = {k:v for k,v in point.items() if k != 'claim_id'}
        fingerprint = hashlib.sha256(json.dumps(original,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        if fingerprint != item['expected_point_sha256'] or not item['text'].strip():
            withheld.append(dict(point_id=point['point_id'],reason='Exact reviewed point differs; retain full wording.'))
            continue
        accepted[point['point_id']] = item['text']
    reader['editorial_review'] = dict(version='profile-reader-editorial-v1',
        applied_point_ids=list(accepted),withheld=withheld,semantic_admission=False)
    if not accepted:
        return reader
    # One method paragraph, then local accounts grouped by their actual recording.
    overview = []
    style = [point for point in points if point['kind'] == 'style']
    if style:
        overview.append([(accepted.get(p['point_id'],p['explanation']),p['claim_id']) for p in style])
    for vid,title in reader['titles'].items():
        local = [p for p in points if p['kind'] == 'reviewed_binding' and int(vid) in p['video_ids']]
        paragraph = [(accepted.get(p['point_id'],local_account(p)),p['claim_id']) for p in local]
        if paragraph:
            text,key = paragraph[0]
            paragraph[0] = ('In “'+title+'”: '+text,key)
            overview.append(paragraph)
    reader['assessment'] = overview
    reader['assessment_scope'] = ('These descriptions draw on reviewed passages in the selected sermons. '
        'The local readings below are proposals, not a complete account of affirmed beliefs. '
        'Examples establish neither a dominant style nor a ministry-wide pattern.')
    for row in reader['at_a_glance']:
        ids = row.get('claim_ids',[])
        selected = [p for p in points if p['claim_id'] in ids and p['point_id'] in accepted]
        if selected:
            row['description'] = ' '.join(accepted[p['point_id']] for p in selected)
            if any(p['kind'] == 'reviewed_binding' for p in selected):
                row['description'] = 'Local reviewed proposal: '+row['description']
    return reader


def local_account(point):
    """Keep voice, use and qualifications attached to an authored proposition."""
    frame = point.get('frame', {})
    notes = []
    if frame.get('voice', {}).get('occurrence') == 'projected':
        notes.append('These words are offered for someone to say; no actual response is established.')
    if frame.get('adoption', {}).get('status') in ('rejected', 'reported_not_adopted', 'undetermined'):
        notes.append(point.get('use_note', ''))
    notes += [q['reading'] for q in frame.get('qualifications', [])]
    notes += [q['rationale'] for q in frame.get('conditions', [])]
    notes = list(dict.fromkeys(note for note in notes if note))
    return 'Reviewed local proposal: '+point['explanation'] + (' '+ ' '.join(notes) if notes else '')


def recording_comparison(reader):
    """Plain summaries plus links; absence from a support set is never denial."""
    result = []
    patterns = reader.get('sample_patterns', {})
    titles = {int(key): value for key, value in reader['titles'].items()}
    for local in patterns.get('recordings', []):
        vid = local['video_id']
        groups = [p for p in patterns['patterns'] if vid in p['video_ids']]
        topics = [TOPICS.get(p['field'], p['field'].replace('_', ' ')) for p in groups if p['layer'] == 'topic']
        themes = [THEMES.get(p['field'], p['field'].replace('_', ' ')) for p in groups if p['layer'] == 'salvation']
        statements = []
        if topics:
            statements.append('Leading subjects: '+phrase_list(topics)+'.')
        if themes:
            statements.append('Salvation themes discussed: '+phrase_list(themes)+'.')
        accounts = [point for point in reader.get('explanatory_descriptions', {}).get('points', []) if vid in point['video_ids']]
        if accounts:
            statements = [local_account(point) if point['kind'] == 'reviewed_binding' else point['explanation'] for point in accounts]
        if not statements:
            statements.append('No supported topic or salvation-theme summary is available here.')
        limits = []
        states = {item['state'] for item in local['salvation_block_states']}
        if 'unrouted_unmeasured' in states:
            limits.append('Some passages were not selected for salvation analysis.')
        if 'missing_compatible_routed_result' in states:
            limits.append('Some selected passages have no compatible saved salvation result.')
        if 'measured_below_threshold' in local['observation_states']:
            limits.append('Other measured relationships do not support a theme description.')
        if local['unresolved_leaves']:
            limits.append('Some salvation relationships remain unresolved.')
        result.append(dict(video_id=vid, title=titles[vid], description=' '.join(statements), accounts=[dict(point_id=p['point_id'], claim_id=p['claim_id'], descriptor=p['descriptor'], text=local_account(p) if p['kind'] == 'reviewed_binding' else p['explanation']) for p in accounts], limits=' '.join(limits), claim_ids=list(dict.fromkeys([point['claim_id'] for point in accounts] + local['reader_claim_ids']))))
    return result


REVIEWED_READING_WARNING = ('These are source-reviewed local proposals, not production-admitted measurements or pastor-wide positions. '
    'They supply local proposed interpretations in this assessment; they do not change the original assurance interpretation. Adoption describes the exact local proposition only.')


def reviewed_local_readings(record):
    """Expose existing reviewed fields without deriving additional profile claims."""
    from pastor_transcript_extractor.profile_proposition_review import fields
    observations = {o['id']: o for o in record['observations']}
    result = []
    for item in record.get('evidence_supply', {}).get('reviewed_bound_records', []):
        observation = observations.get(item['evidence_id'])
        if observation is None:
            continue  # Cannot display a source link outside this current profile.
        binding = item['binding']
        result.append(dict(title=binding['title'],
            fields=[dict(label=label, reading=reading) for label, reading, spans in fields(binding)],
            unknowns=list(binding['unknowns']),
            passage_id=f'passage-{observation["video_id"]}-{observation["block_id"]}'))
    return result


STYLE = '''
:root{--ink:#20332f;--muted:#61716b;--line:#d9e2dc;--accent:#28634e;--paper:#fffefb}*{box-sizing:border-box}body{margin:0;background:#f4f5ef;color:var(--ink);font:16px/1.65 system-ui,sans-serif}main{max-width:1060px;padding:48px 28px 80px;margin:auto}h1,h2{font-family:Georgia,serif;font-weight:500;line-height:1.2}h1{font-size:clamp(32px,5vw,50px);margin:10px 0}h2{font-size:27px;margin:30px 0 16px}h3{font-size:18px;margin:12px 0}p{margin:12px 0}.eyebrow{font-size:12px;font-weight:700;letter-spacing:.12em;color:var(--accent)}.scope,.muted{color:var(--muted);font-size:14px}.assessment{max-width:850px;font-size:18px}.claimref{color:var(--accent);font-size:12px;vertical-align:super;white-space:nowrap;text-decoration:none;border-bottom:1px solid #b8cdbf}.claimref:hover{color:var(--accent)}a{color:var(--accent)}.panel,.sermon{background:var(--paper);border:1px solid var(--line);padding:22px;border-radius:12px;margin:20px 0}.note{border-left:3px solid var(--accent);padding:8px 18px;background:#eaf0e7}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.grid .panel{margin:0}table{border-collapse:collapse;width:100%}td,th{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:12px 10px}th{font-weight:600}th:first-child{width:24%}.tablewrap{overflow-x:auto}summary{cursor:pointer;font-weight:600;color:var(--accent);padding:10px 0}details[open]>summary{margin-bottom:8px}details.claim{border-top:1px solid var(--line);padding:8px 0}.source{white-space:pre-wrap;border-left:2px solid var(--line);padding:12px 18px;background:#f6f7f1;font:17px/1.7 Georgia,serif;overflow-wrap:anywhere}.technical{font-size:14px;color:var(--muted);border-top:1px solid var(--line);margin-top:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}nav{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}button{font:inherit;font-size:14px;padding:7px 14px;border:1px solid var(--line);border-radius:20px;background:var(--paper);cursor:pointer}button[aria-pressed=true]{background:var(--accent);color:white}a:focus-visible,summary:focus-visible,button:focus-visible{outline:3px solid #bb8d3e;outline-offset:4px}:target{scroll-margin-top:20px}footer{color:var(--muted);font-size:13px;padding-top:24px}[hidden]{display:none!important}.passage{border-top:1px solid var(--line)}.evidence-links{display:grid;gap:8px;margin:12px 0}.gap{border-top:1px solid var(--line);padding-top:12px;margin-top:16px}@media(max-width:720px){main{padding:28px 18px 50px}.grid{grid-template-columns:1fr}.panel,.sermon{padding:18px}th:first-child{width:30%}td,th{padding:10px 6px}}
'''
SCRIPT = '''
function revealEvidence(){let key;try{key=decodeURIComponent(location.hash.slice(1));}catch{return;}const target=document.getElementById(key);if(!target)return;
document.querySelectorAll('.sermon[data-video]').forEach(s=>s.hidden=false);
document.querySelectorAll('button[data-filter]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.filter==='all'?'true':'false'));
let p=target;while(p){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}target.scrollIntoView();}
document.querySelectorAll('button[data-filter]').forEach(button=>button.addEventListener('click',()=>{
document.querySelectorAll('button[data-filter]').forEach(b=>b.setAttribute('aria-pressed',b===button?'true':'false'));
document.querySelectorAll('.sermon[data-video]').forEach(s=>s.hidden=button.dataset.filter!=='all'&&s.dataset.video!==button.dataset.filter);}));
window.addEventListener('hashchange',revealEvidence);window.addEventListener('load',revealEvidence);
'''


def render(record):
    reader = record['reader']
    e = lambda value: html.escape(str(value), quote=True)
    titles = {int(key): value for key, value in reader['titles'].items()}
    link = lambda key, label: f'<a href="#{e(key)}">{e(label)}</a>'
    obs = {o['id']: o for o in record['observations']}
    claims = {c['id']: c for c in reader['claims']}

    def passage_id(o):
        return f'passage-{o["video_id"]}-{o["block_id"]}'

    def supporting(refs):
        unique = list(dict.fromkeys(passage_id(obs[key]) for key in refs))
        by_passage = {passage_id(o): o for o in obs.values()}
        links = [link(key, 'View supporting passage · '+titles[by_passage[key]['video_id']]+' · '+timestamp(by_passage[key]['start_seconds'])) for key in unique]
        text = '<div class="evidence-links">'+''.join('<span>'+l+'</span>' for l in links[:4])+'</div>'
        if len(links) > 4:
            text += '<details><summary>More supporting passages</summary><div class="evidence-links">'+''.join('<span>'+l+'</span>' for l in links[4:])+'</div></details>'
        return text

    assessment = ''.join('<p>'+' '.join(e(text)+f' <a class="claimref" href="#{e(key)}" aria-label="View evidence for this description">evidence</a>' for text, key in paragraph)+'</p>' for paragraph in reader['assessment'])
    rows = ''.join('<tr><th>'+e(row['label'])+'</th><td>'+e(row['description'])+' '+link(row['target'], 'View evidence' if row['label'] != 'Confidence' else 'Read limits')+'</td></tr>' for row in reader['at_a_glance'])
    theme_rows = ''.join('<tr><th>'+e(t['label'])+'</th><td>'+e(t['seen_in'])+'</td><td>'+link(t['claim_id'], 'View evidence')+'</td></tr>' for t in reader['themes'])
    theme_table = '<div class="tablewrap"><table><thead><tr><th>Theme</th><th>Seen in</th><th>Support</th></tr></thead><tbody>'+theme_rows+'</tbody></table></div>' if theme_rows else '<p>There is not enough supporting evidence here to describe salvation themes.</p>'
    style_examples = ''.join('<p>'+link('account-'+point['point_id'], point['descriptor'])+'</p>' for point in reader.get('explanatory_descriptions', {}).get('points', []) if point['kind'] == 'style' and point.get('dimension') != 'practical_application')
    topic_rows = []
    for topic, vids in reader['shared_topic_membership'].items():
        refs = [key for claim in record['claims'] if claim['rule'] == 'topic' for key in claim['evidence_ids'] if obs[key]['field'] == topic]
        seen_in = 'All '+str(len(titles))+' sermons' if len(vids) == len(titles) and len(titles) > 1 else phrase_list([titles[vid] for vid in vids])
        topic_rows.append('<tr><th>'+e(TOPICS.get(topic, topic.replace('_', ' ')))+'</th><td>'+e(seen_in)+'</td><td>'+supporting(refs)+'</td></tr>')
    emphases = '<p>Compare the passages to see how these subjects are developed in the named sermons. Attention to a subject does not establish agreement with every view discussed.</p><div class="tablewrap"><table><thead><tr><th>Subject</th><th>Seen in</th><th>Supporting passages</th></tr></thead><tbody>'+''.join(topic_rows)+'</tbody></table></div>'
    comparison = ''.join('<tr><th>'+e(item['title'])+'</th><td>'+(''.join('<p>'+link('account-'+account['point_id'], account['descriptor'])+'</p>' for account in item['accounts']) if item['accounts'] else e(item['description']))+'<p class="muted">'+e(item['limits'])+'</p>'+ ' '.join(link(key, 'View evidence') for key in item['claim_ids'])+'</td></tr>' for item in recording_comparison(reader))
    comparison = '<section class="panel" id="recording-comparison"><h2>How the recordings compare</h2><p>Accounts describe selected reviewed passages, not the complete argument or balance of a sermon. Missing support does not establish absence or disagreement.</p><div class="tablewrap"><table><thead><tr><th>Recording</th><th>Supported observations and limits</th></tr></thead><tbody>'+comparison+'</tbody></table></div></section>'
    explanatory_cards = []
    for point in reader.get('explanatory_descriptions', {}).get('points', []):
        frame = point.get('frame', {})
        notes = list(dict.fromkeys([point.get('voice_note', ''), point.get('use_note', ''), frame.get('scope', {}).get('reading', '')] + [q['reading'] for q in frame.get('qualifications', [])] + [q['rationale'] for q in frame.get('conditions', [])]))
        unknowns = '<p><strong>Unknown or withheld</strong></p><ul>'+''.join('<li>'+e(value)+'</li>' for value in frame.get('unknowns', []))+'</ul>' if frame.get('unknowns') else ''
        explanatory_cards.append((point['video_ids'][0], '<article class="gap" id="account-'+e(point['point_id'])+'"><h4>'+e(point['descriptor'])+'</h4><p>'+e(point['explanation'])+'</p>'+('<p class="note">Reviewed local proposal · selected passage only.</p>' if point['kind'] == 'reviewed_binding' else '')+''.join('<p class="muted">'+e(note)+'</p>' for note in notes if note)+unknowns+supporting(point['evidence_ids'])+'<p>'+link(point['claim_id'], 'How this description is supported')+'</p></article>'))
    explanatory_section = '<section class="panel" id="concrete-descriptions"><h2>What the selected passages show</h2><p>These are separate local examples, not complete sermon summaries.</p>'+''.join('<section><h3>'+e(title)+'</h3>'+''.join(card for source,card in explanatory_cards if source == vid)+'</section>' for vid,title in titles.items() if any(source == vid for source,_ in explanatory_cards))+'</section>' if explanatory_cards else ''
    selections = {item['claim_id']: item for item in record.get('supporting_examples', [])}
    cards = []
    for c in reader['claims']:
        selection = selections.get(c['id'], {})
        examples = ''.join('<p>'+link(block['passage_id'], 'Selected full-block example · '+titles[block['video_id']])+' '+e(block['support_reason'])+'</p>' for block in selection.get('selected_blocks', []))
        examples += ''.join('<p class="muted">'+e(note)+'</p>' for note in selection.get('qualifications', []))
        cards.append('<details class="claim" id="'+e(c['id'])+'"><summary>'+e(c['wording'])+'</summary><p>'+e(c['reason'])+'</p>'+examples+supporting(c['evidence_ids'])+
            '<details class="technical"><summary>Technical details</summary><pre>'+e(json.dumps(c, ensure_ascii=False, indent=2))+'</pre></details></details>')
    reviewed = reviewed_local_readings(record)
    reviewed_cards = ''.join('<article><h3>'+e(item['title'])+'</h3><dl>'+''.join('<dt><strong>'+e(field['label'])+'</strong></dt><dd>'+e(field['reading'])+'</dd>' for field in item['fields'])+'</dl><p><strong>Unknown or withheld</strong></p><ul>'+''.join('<li>'+e(value)+'</li>' for value in item['unknowns'])+'</ul><p>'+link(item['passage_id'], 'Inspect the current supporting passage')+'</p></article>' for item in reviewed)
    reviewed_section = '<section class="panel" id="reviewed-local-readings"><h2>Reviewed local readings · proposals</h2><p class="muted">'+e(REVIEWED_READING_WARNING)+'</p><details><summary>Inspect the existing source-reviewed local readings</summary>'+reviewed_cards+'</details></section>' if reviewed else ''
    gap_cards = []
    for gap in record['gaps']:
        title, explanation, next_step = GAPS[gap['id']]
        gap_cards.append('<article class="gap" id="gap-'+e(gap['id'])+'"><h3>'+e(title)+'</h3><p>'+e(explanation)+'</p><p class="muted">Next useful step: '+e(next_step)+'</p>'+
            '<details class="technical"><summary>Technical details and implementation remedy</summary><pre>'+e(json.dumps(gap, ensure_ascii=False, indent=2))+'</pre></details></article>')
    reverse = defaultdict(list)
    for c in reader['claims']:
        for key in c['evidence_ids']:
            if c['id'] not in reverse[passage_id(obs[key])]:
                reverse[passage_id(obs[key])].append(c['id'])
    windows = defaultdict(list)
    for o in obs.values():
        windows[(o['video_id'], o['block_id'])].append(o)
    source_sections = []
    for s in record['source_identity']:
        vid = s['video_id']
        passages = []
        for (source, block), values in sorted(windows.items(), key=lambda item: (item[0][0], item[1][0]['start_seconds'])):
            if source != vid:
                continue
            first = values[0]
            pid = passage_id(first)
            technical_observations = []
            for o in values:
                metadata = {key: value for key, value in o.items() if key != 'full_target_text'}
                technical_observations.append('<details id="'+e(o['id'])+'"><summary>'+e(o['field'])+' · '+e(o['state'])+'</summary><pre>'+e(json.dumps(metadata, ensure_ascii=False, indent=2))+'</pre></details>')
            back = ''.join('<p>'+link(key, 'Back to description: '+claims[key]['wording'])+'</p>' for key in reverse[pid])
            passages.append('<details class="passage" id="'+e(pid)+'"><summary>'+e(timestamp(first['start_seconds']))+'–'+e(timestamp(first['end_seconds']))+'</summary>'+
                '<p><a href="'+e(first['watch_url'])+'" target="_blank" rel="noopener noreferrer">Watch this passage</a></p><div class="source">'+e(first['full_target_text'])+'</div>'+back+
                '<details class="technical"><summary>Technical details</summary>'+''.join(technical_observations)+'</details></details>')
        source_sections.append('<details class="sermon" data-video="'+str(vid)+'"><summary>'+e(titles[vid])+'</summary><p class="muted">Original source title: '+e(s['title'])+'</p>'+
            '<details class="technical"><summary>Technical source details</summary><pre>'+e(json.dumps(s, ensure_ascii=False, indent=2))+'</pre></details>'+''.join(passages)+'</details>')
    raw_claims = []
    for c in record['claims']:
        inputs = list(dict.fromkeys(c['evidence_ids']+c['observation_input_ids']+c['counterevidence_ids']))
        raw_claims.append('<details id="'+e(c['id'])+'"><summary>'+e(c['wording'])+'</summary><pre>'+e(json.dumps(c, ensure_ascii=False, indent=2))+'</pre>'+supporting(inputs)+
            '<details><summary>All observation inputs and counterevidence</summary>'+''.join('<p>'+link(key, 'Inspect observation')+'</p>' for key in inputs)+'</details></details>')
    technical = ('<details class="technical" id="technical-provenance"><summary>Technical details · provenance, interpretation rules and complete evidence ledger</summary><p>Below-threshold findings, unmeasured passages and unresolved relationships remain distinct. None establishes a negative theological position.</p>'+
        '<pre>'+e(json.dumps(dict(version=record['version'], profile=record['profile'], inventory_fingerprint=record['inventory_fingerprint'], description_fingerprint=record['content_fingerprint'],
            rules=record['rules'], reader_rule=reader['synthesis_rule'], coverage=record['coverage'], salvation_block_states=record['salvation_block_states'], unresolved_leaves=record['unresolved_leaves'], reuse_checks=record['reuse_checks'], sample_patterns=reader.get('sample_patterns'), evidence_supply=record.get('evidence_supply'), supporting_examples=record.get('supporting_examples')), ensure_ascii=False, indent=2))+'</pre>'+
        '<details><summary>Underlying per-sermon claim ledger</summary>'+''.join(raw_claims)+'</details></details>')
    filters = ''.join('<button type="button" data-filter="'+str(vid)+'" aria-pressed="false">'+e(title)+'</button>' for vid, title in titles.items())
    style_text = 'The passages below show different ways the preacher develops a point. Examples establish the presence of an approach, not how often it is used.' if reader['source_reviews'] else 'No source-reviewed style examples are available for this sample.'
    pastoral_review = next((review for review in reader['source_reviews'] if review['dimension'] == 'practical_application'), None)
    pastoral_text = pastoral_review['description'] if pastoral_review else reader['at_a_glance'][3]['description']
    packet = record.get('capability_review', {})
    next_capability = ''
    if packet.get('recommendation'):
        prepared = ''.join('<article><h3>'+e(case['title'])+'</h3><p>'+e(case['review_question'])+'</p><p>'+e(case['caution'])+'</p>'+link(f'passage-{case["video_id"]}-{case["block_id"]}', 'View prepared passage · '+case['sermon_title'])+'</article>' for case in packet.get('cases', []))
        next_capability = '<section class="panel" id="next-capability"><h2>What would most improve this assessment?</h2><p>'+e(packet['recommendation'])+'</p><p>'+e(packet['reader_value'])+'</p><details id="next-capability-review"><summary>Read the prepared next-step proposal</summary><p>'+e(packet['why_first'])+'</p><p>'+e(packet['decision'])+'</p><p>Historical prepared cases remain inspectable; they do not confer new measurement or execution authority.</p>'+prepared+'<p><a href="next-capability-v2.md">Read the complete decision brief</a></p></details></section>'
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+e(reader['title'])+'</title><style>'+STYLE+'</style></head><body><main>'+
        '<span class="eyebrow">PASTOR TRANSCRIPT EXTRACTOR</span><h1>'+e(reader['title'])+'</h1><p class="scope">'+e(reader['sample_note'])+'</p><p class="muted">'+e(reader['identity_note'])+'</p>'+
        '<section class="assessment"><h2>Assessment of this sample</h2>'+('<p class="scope">'+e(reader['assessment_scope'])+'</p>' if reader.get('assessment_scope') else '')+(assessment or '<p>There is not enough supported evidence to describe this sample.</p>')+'</section>'+
        '<p class="muted">Select a description to inspect its supporting passages.</p>'+
        '<section id="at-a-glance"><h2>Pastor at a glance</h2><div class="tablewrap"><table><thead><tr><th>Dimension</th><th>What these sermons suggest</th></tr></thead><tbody>'+rows+'</tbody></table></div></section>'+
        '<section class="panel" id="sample-limits"><h2>How to read this sample</h2><p>These selected recordings and reviewed passages give a preliminary picture. Examples do not establish a dominant method, a usual sermon structure or a ministry-wide pattern. Subject attention does not establish agreement. Local proposals retain their voice, use and qualifications; they are not production-admitted measurements. Repeated source content does not add independent teaching occasions.</p></section>'+
        '<section class="panel"><h2>Benchmark comparison</h2><p>Comparison with other preachers is not yet established.</p></section>'+
        comparison+explanatory_section+'<h2>A closer look</h2><section class="panel" id="dimension-style"><h2>Preaching style</h2><p>'+e(style_text)+'</p>'+style_examples+'</section>'+
        '<section class="panel" id="dimension-emphases"><h2>Major theological emphases</h2>'+emphases+'</section>'+
        '<section class="panel" id="dimension-salvation"><h2>Salvation themes in these sermons</h2>'+theme_table+
        '<p class="note">This table records themes discussed. The local proposals above preserve more specific reviewed readings; neither establishes a complete doctrinal position.</p></section>'+
        '<section class="panel" id="dimension-pastoral"><h2>Pastoral approach</h2><p>'+e(pastoral_text)+'</p>'+(''+link(passage_id(obs[r['evidence_id']]), 'View supporting passage · '+titles[r['video_id']]) if (r := next((r for r in reader['source_reviews'] if r['dimension'] == 'practical_application'), None)) else '')+'</section>'+
        '<section class="panel" id="why"><h2>Why PTE says this</h2>'+''.join(cards)+'</section>'+
        reviewed_section+next_capability+'<section class="panel"><h2>What this sample cannot tell us</h2>'+''.join(gap_cards)+'</section>'+
        '<h2>Sermons and supporting passages</h2><p class="muted">Choose a sermon or follow a description directly to its complete source passage. Filtering this section does not change the assessment above.</p>'+
        '<nav aria-label="Filter recordings"><button type="button" data-filter="all" aria-pressed="true">All sermons</button>'+filters+'</nav>'+''.join(source_sections)+technical+
        '<footer>This draft awaits review. Supporting passages are full transcript windows, not selected illustrative quotations.</footer></main><script>'+SCRIPT+'</script></body></html>')


def markdown(record):
    reader = record['reader']
    obs = {o['id']: o for o in record['observations']}
    titles = {int(key): value for key, value in reader['titles'].items()}
    lines = ['# '+reader['title'], '', reader['sample_note'], '', reader['identity_note'], '', '## Assessment', '']
    if reader.get('assessment_scope'):
        lines += [reader['assessment_scope'], '']
    for paragraph in reader['assessment']:
        lines += [' '.join(text+f' [View evidence](index.html#{key})' for text, key in paragraph), '']
    lines += ['## Pastor at a glance', '', '| Dimension | What these sermons suggest |', '|---|---|']
    lines += ['| '+row['label']+' | '+row['description'].replace('|', '/')+' |' for row in reader['at_a_glance']]
    lines += ['', '## How to read this sample', '', 'These selected recordings and reviewed passages give a preliminary picture. Local examples do not establish a dominant method, usual sermon structure or ministry-wide pattern. Subject attention does not establish agreement. Local proposals retain their original voice, use and qualifications and remain separate from production findings.', '']
    lines += ['', '## How the recordings compare', '']
    for item in recording_comparison(reader):
        lines += ['### '+item['title'], '']
        if item['accounts']:
            for account in item['accounts']:
                lines += ['- ['+html.escape(account['descriptor'])+'](index.html#account-'+account['point_id']+')', '']
        else:
            lines += [item['description'], '']
        lines += [item['limits'], '', ' '.join(f'[View evidence](index.html#{key})' for key in item['claim_ids']), '']
    points = reader.get('explanatory_descriptions', {}).get('points', [])
    if points:
        lines += ['## What the selected passages show', '', 'Separate local examples, not complete sermon summaries.', '']
        for vid,title in titles.items():
            local_points = [point for point in points if vid in point['video_ids']]
            if not local_points:
                continue
            lines += ['### '+html.escape(title), '']
            for point in local_points:
                lines += ['#### '+html.escape(point['descriptor']), '', html.escape(local_account(point) if point['kind'] == 'reviewed_binding' else point['explanation']), '']
                for unknown in point.get('frame', {}).get('unknowns', []):
                    lines += ['- Unknown or withheld: '+html.escape(unknown)]
                lines += ['']
                if point['kind'] == 'style':
                    lines += [note for note in point.get('qualifications', [])] + ['']
                lines += ['[How this description is supported](index.html#'+point['claim_id']+')', '']
    lines += ['', '## Benchmark comparison', '', 'Comparison with other preachers is not yet established.', '', '## Salvation themes in these sermons', '', '| Theme | Seen in | Support |', '|---|---|---|']
    lines += ['| '+theme['label']+' | '+theme['seen_in'].replace('|', '/')+f' | [View evidence](index.html#{theme["claim_id"]}) |' for theme in reader['themes']]
    lines += ['', 'This table records discussed themes. The local proposals above preserve more specific reviewed readings; neither establishes a complete doctrinal position.', '', '## Preaching style: source examples', '']
    for review in reader['source_reviews']:
        o = obs[review['evidence_id']]
        lines += [review.get('descriptor', review['description'])+f' [View supporting passage: {titles[o["video_id"]]}](index.html#passage-{o["video_id"]}-{o["block_id"]})', '']
    lines += ['## Why PTE says this', '']
    for c in reader['claims']:
        lines += ['### '+c['wording'], '', c['reason'], '']
        seen = set()
        for ref in c['evidence_ids']:
            o = obs[ref]
            key = (o['video_id'], o['block_id'])
            if key in seen:
                continue
            seen.add(key)
            lines += [f'- [View supporting passage · {titles[o["video_id"]]} · {timestamp(o["start_seconds"])}](index.html#passage-{o["video_id"]}-{o["block_id"]})']
        lines += ['']
    reviewed = reviewed_local_readings(record)
    if reviewed:
        lines += ['## Reviewed local readings · proposals', '', REVIEWED_READING_WARNING, '', '<details><summary>Inspect the existing source-reviewed local readings</summary>', '']
        for item in reviewed:
            lines += ['### '+html.escape(item['title']), '']
            for field in item['fields']:
                lines += ['**'+html.escape(field['label'])+':** '+html.escape(field['reading']), '']
            lines += ['**Unknown or withheld:**', ''] + ['- '+html.escape(value) for value in item['unknowns']]
            lines += ['', '[Inspect the current supporting passage](index.html#'+item['passage_id']+')', '']
        lines += ['</details>', '']
    if record.get('capability_review', {}).get('recommendation'):
        lines += ['## Recommended next capability', '', record['capability_review']['recommendation'], '', record['capability_review']['reader_value'], '', '[Read the prepared next-step decision brief](next-capability-v2.md). Historical cases do not confer new execution authority.', '']
    lines += ['## What this sample cannot tell us', '']
    for gap in record['gaps']:
        title, cause, remedy = GAPS[gap['id']]
        lines += ['### '+title, '', cause, '', 'Next useful step: '+remedy, '']
    lines += ['<details><summary>Technical details</summary>', '',
        'The [complete description record](description-v6.json) preserves every original observation, source hash, question/model/version, threshold, missing state, source-review receipt and claim link. The [review receipt](review-v6.json) records the scope and execution boundaries.', '',
        'Source-review descriptions are authored presentation inputs for individual passages, pending Brian’s acceptance. No raw probability, threshold, adopted position or frequency rule is changed.', '', '</details>', '']
    return '\n'.join(lines)
