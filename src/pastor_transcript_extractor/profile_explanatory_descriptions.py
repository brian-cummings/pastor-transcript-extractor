"""Assemble authored explanations over compatible existing evidence, without inference.

These are presentation records, not new measurements or a transcript summarizer.
The supplied profile and its reused-binding receipts remain the analytical authority.
Every explanatory clause retains its authored evidence and local proposal status.
"""
from copy import deepcopy
import hashlib

from pastor_transcript_extractor.binding_evidence import text_digest, validate_span


VERSION = 'pastor-profile-explanatory-descriptions-v1'
PROPOSAL = 'source_reviewed_proposal_not_production_admission'
STYLE_STATUS = 'source_reviewed_description_pending_reader_acceptance'


def _identity(kind, identity):
    return 'reader-description-' + kind + '-' + hashlib.sha256(identity.encode()).hexdigest()[:16]


def _passage(observation):
    return f'passage-{observation["video_id"]}-{observation["block_id"]}'


def _source(record, observation):
    source = next((s for s in record.get('source_identity', [])
                   if s['video_id'] == observation.get('video_id')), None)
    if (source is None or source.get('source_sha256') != observation.get('source_sha256')
            or not isinstance(observation.get('full_target_text'), str)
            or not observation['full_target_text']):
        raise ValueError('The observation has no matching current source and complete target.')
    if source.get('gate', {}).get('eligible') is False:
        raise ValueError('The current recording is ineligible.')
    return dict(status='compatible', video_id=observation['video_id'],
                block_id=observation['block_id'], source_sha256=observation['source_sha256'],
                target_sha256=text_digest(observation['full_target_text']))


def _clause(role, text, evidence_id, binding_id=None, spans=()):
    return dict(role=role, text=text, evidence_ids=[evidence_id],
                reviewed_binding_ids=[binding_id] if binding_id else [], spans=deepcopy(list(spans)))


def _frame_notes(binding):
    voice = binding['voice']
    speaker = voice.get('speaker') or 'an unresolved speaker'
    if voice['occurrence'] == 'projected':
        voice_note = ('These words are presented as projected speech by ' + speaker
                      + '; they do not establish that the words were actually spoken.')
    elif voice['kind'] == 'quoted_or_reported':
        voice_note = ('The proposition is voiced in reported speech attributed to ' + speaker
                      + '; historical verification is not established.')
    elif voice['kind'] == 'preacher' and voice['occurrence'] == 'actual':
        voice_note = 'The proposition is voiced by the preacher in this passage.'
    else:
        voice_note = 'The voiced speaker or whether the words were actually spoken remains unresolved.'
    use_note = {
        'own_assertion': 'The reviewed reading treats this as the preacher’s own local assertion.',
        'adopted': 'The reviewed reading treats the preacher as endorsing this local proposition.',
        'reported_not_adopted': 'The reviewed reading reports this proposition without establishing preacher endorsement.',
        'rejected': 'The reviewed reading treats the preacher as rejecting this proposition; no opposite proposition is inferred.',
        'undetermined': 'The preacher’s use of this local proposition remains undetermined.',
    }[binding['adoption']['status']]
    return voice_note, use_note


def _target_spans(value, target):
    """Recheck literal target spans; context identities were checked by upstream reuse.

    Complete bounded context is deliberately not rediscovered/read here. Its existing
    digest and review receipt are retained, while all target evidence must still match.
    """
    if isinstance(value, dict):
        if 'source_field' in value:
            if value['source_field'] == 'target_text':
                validate_span(value, dict(target_text=target))
            elif value['source_field'] not in ('leading_context', 'trailing_context'):
                raise ValueError('Unknown reviewed evidence source field.')
        for child in value.values():
            _target_spans(child, target)
    elif isinstance(value, list):
        for child in value:
            _target_spans(child, target)


def _style(record, review, observation):
    compatibility = _source(record, observation)
    expected = dict(video_id=observation['video_id'], block_id=observation['block_id'],
                    dimension=observation.get('field'), source_sha256=observation['source_sha256'],
                    start_seconds=observation.get('start_seconds'), end_seconds=observation.get('end_seconds'),
                    target_sha256=compatibility['target_sha256'])
    if observation.get('layer') != 'treatment' or any(review.get(k) != v for k, v in expected.items()):
        raise ValueError('The style review does not match this exact treatment observation.')
    if not review.get('description', '').strip() or not review.get('scope', '').strip():
        raise ValueError('The style review lacks an authored explanation or local scope.')
    eid = observation['id']
    description = review['description']
    descriptor = review.get('descriptor') or description
    clauses = [_clause('descriptor', descriptor, eid), _clause('explanation', description, eid),
               _clause('scope', review['scope'], eid)]
    return dict(point_id=_identity('style', eid), kind='style', dimension=review['dimension'],
                descriptor=descriptor, explanation=description,
                example=observation['full_target_text'], evidence_ids=[eid], reviewed_binding_ids=[],
                video_ids=[observation['video_id']], passage_ids=[_passage(observation)],
                qualifications=[review['scope']], counterevidence_ids=[], status=STYLE_STATUS,
                source_compatibility=compatibility, clauses=clauses,
                voice_note='', use_note='', address_acts=[], frame={})


def _binding(record, item, observation):
    compatibility = _source(record, observation)
    binding = item['binding']
    if item.get('status') != PROPOSAL or item.get('original_g1_record_unchanged') is not True:
        raise ValueError('The reused binding lacks the reviewed proposal and unchanged-interpretation receipt.')
    provenance = binding['provenance']
    expected = dict(video_id=observation['video_id'], block_id=observation['block_id'],
                    source_sha256=observation['source_sha256'], target_sha256=compatibility['target_sha256'],
                    source_inventory_fingerprint=record['inventory_fingerprint'],
                    membership_fingerprint=record['profile']['membership_fingerprint'])
    if any(provenance.get(key) != value for key, value in expected.items()):
        raise ValueError('The reviewed binding source, target or profile scope is incompatible.')
    if not provenance.get('texts_sha256'):
        raise ValueError('The reviewed binding has no previously checked context identity.')
    supplied_context = observation.get('context')
    if supplied_context and all(k in supplied_context for k in ('target_text', 'leading_context', 'trailing_context')):
        from pastor_transcript_extractor.binding_evidence import context_digest
        texts = {k: supplied_context[k] for k in ('target_text', 'leading_context', 'trailing_context')}
        if texts['target_text'] != observation['full_target_text'] or context_digest(texts) != provenance['texts_sha256']:
            raise ValueError('The current supplied bounded context differs from the reviewed binding.')
    _target_spans(binding, observation['full_target_text'])
    span = binding['proposition']['span']
    if span['source_field'] != 'target_text':
        raise ValueError('A reviewed description cannot derive its proposition from context.')
    if not binding['title'].strip() or not binding['proposition']['reading'].strip():
        raise ValueError('The reviewed binding has no authored title or explanation.')
    eid, bid = observation['id'], binding['binding_id']
    from pastor_transcript_extractor.profile_proposition_review import fields
    clauses = [_clause('descriptor', binding['title'], eid, bid, [span])]
    clauses.extend(_clause(label, reading, eid, bid, spans) for label, reading, spans in fields(binding))
    voice_note, use_note = _frame_notes(binding)
    clauses += [_clause('voice_note', voice_note, eid, bid, binding['voice']['evidence']),
                _clause('use_note', use_note, eid, bid, binding['adoption']['evidence'])]
    clauses.extend(_clause('unknown', text, eid, bid) for text in binding['unknowns'])
    qualifications = [binding['scope']['reading'], voice_note, use_note,
                      binding['voice']['rationale'], binding['adoption']['rationale'],
                      binding['polarity']['rationale'], binding['expression']['rationale'],
                      binding['epistemic_status']['rationale']]
    qualifications += [q['reading'] for q in binding['qualifications']]
    qualifications += [c['rationale'] for c in binding['conditions']]
    qualifications += binding['unknowns']
    compatibility.update(reviewed_context_sha256=provenance['texts_sha256'],
                         context_check='upstream_exact_scope_receipt; target spans rechecked here',
                         inventory_fingerprint=record['inventory_fingerprint'],
                         membership_fingerprint=record['profile']['membership_fingerprint'])
    frame = {k: deepcopy(binding[k]) for k in ('voice', 'adoption', 'polarity', 'expression',
             'epistemic_status', 'conditions', 'scope', 'qualifications', 'development_relations', 'unknowns')}
    return dict(point_id=_identity('reviewed_binding', bid), kind='reviewed_binding',
                descriptor=binding['title'], explanation=binding['proposition']['reading'],
                example=span['text'], evidence_ids=[eid], reviewed_binding_ids=[bid],
                video_ids=[observation['video_id']], passage_ids=[_passage(observation)],
                qualifications=list(dict.fromkeys(qualifications)), counterevidence_ids=[], status=PROPOSAL,
                source_compatibility=compatibility, clauses=clauses, voice_note=voice_note,
                use_note=use_note, address_acts=deepcopy(binding['address_acts']), frame=frame)


def build(record, reader):
    """Pure generic assembly from exact reviews, never probabilities or transcript guesses.

    Incompatible/missing authored records are withheld independently: one stale review
    cannot remove other supported descriptions or promote a nearby source instead.
    """
    observations = {o['id']: o for o in record.get('observations', [])}
    result = dict(version=VERSION, points=[], withheld=[], by_recording={})
    seen = set()
    inputs = [('style', item, item.get('evidence_id')) for item in reader.get('source_reviews', [])]
    inputs += [('reviewed_binding', item, item.get('evidence_id'))
               for item in record.get('evidence_supply', {}).get('reviewed_bound_records', [])]
    for kind, item, eid in inputs:
        identity = eid if kind == 'style' else item.get('binding', {}).get('binding_id')
        try:
            if eid not in observations:
                raise ValueError('The reviewed point has no observation in this profile.')
            point = (_style(record, item, observations[eid]) if kind == 'style'
                     else _binding(record, item, observations[eid]))
            if point['point_id'] in seen:
                # Duplicate identities cannot manufacture extra examples or frequency.
                continue
            for key in item.get('counterevidence_ids', []):
                if key not in observations:
                    raise ValueError('The reviewed point references unavailable counterevidence.')
                point['counterevidence_ids'].append(key)
            seen.add(point['point_id'])
            result['points'].append(point)
            for vid in point['video_ids']:
                result['by_recording'].setdefault(str(vid), []).append(point['point_id'])
        except (KeyError, TypeError, ValueError) as error:
            result['withheld'].append(dict(kind=kind, identity=identity, evidence_id=eid,
                                            reason=str(error), status='withheld_incompatible_review'))
    return result
