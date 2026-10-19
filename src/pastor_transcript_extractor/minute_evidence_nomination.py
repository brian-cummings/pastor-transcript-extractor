"""Untrusted nomination DTO, exact validator and BLOCKED data-only mapping."""
from __future__ import annotations
from copy import deepcopy
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal

VERSION='minute-nomination-interface-v1'


def identity(source_proof,anchor,context,family,*,provider_lock=None,question_version=VERSION,routing_identity='historical_retained_membership_diagnostic'):
    if (seal(source_proof)!=source_proof or seal(anchor)!=anchor or seal(context)!=context
            or source_proof['source_fingerprint']!=anchor['source_fingerprint']
            or context['source_fingerprint']!=anchor['source_fingerprint']
            or context['anchor_fingerprint']!=anchor['content_fingerprint']):raise ValueError('Foreign source/anchor/context identity')
    if family not in ('G2','G3') or context['status']!='prepared_context_only':raise ValueError('No eligible family/context')
    return seal(dict(version=VERSION,family=family,source_proof=source_proof['content_fingerprint'],
        source_fingerprint=anchor['source_fingerprint'],anchor_fingerprint=anchor['content_fingerprint'],
        context_fingerprint=context['content_fingerprint'],provider_lock=deepcopy(provider_lock),question_version=question_version,
        routing_identity=routing_identity,execution_authorized=False,provider_request_prepared=False,cache_reuse_authorized=False))


def fields(value,names):
    if type(value) is not dict or set(value)!=set(names):raise ValueError('Foreign or missing nomination fields')


def exact_span(span,context):
    fields(span,('start','end','text'))
    a,b=span['start'],span['end']
    if (type(a) is not int or type(b) is not int or type(span['text']) is not str
            or not context['start']<=a<b<=context['end']
            or context['text'][a-context['start']:b-context['start']]!=span['text']):
        raise ValueError('Span is not an exact canonical envelope substring')


def validate_output(value,binding,anchor,context):
    if (seal(binding)!=binding or seal(anchor)!=anchor or seal(context)!=context
            or anchor['status']!='mapped' or context['status']!='prepared_context_only'
            or binding['family'] not in ('G2','G3')
            or binding['source_fingerprint']!=anchor['source_fingerprint']
            or context['source_fingerprint']!=anchor['source_fingerprint']):raise ValueError('Unverified source/anchor/context')
    fields(value,('request_fingerprint','status','nominations'))
    if (value['request_fingerprint']!=binding['content_fingerprint'] or binding['context_fingerprint']!=context['content_fingerprint']
            or binding['anchor_fingerprint']!=anchor['content_fingerprint'] or context['anchor_fingerprint']!=anchor['content_fingerprint']):
        raise ValueError('Foreign source/anchor/request binding')
    if value['status'] not in ('proposed','none','missing_context','uncertain','saturated'):raise ValueError('Unknown nomination status')
    if type(value['nominations']) is not list or len(value['nominations'])>4:raise ValueError('Nomination ceiling is four')
    if (value['status']=='none' and value['nominations']) or (value['status']=='proposed' and not value['nominations']):raise ValueError('Inconsistent nomination status')
    results=[]
    for nomination in value['nominations']:
        fields(nomination,('roles','dependencies','provenance_hypotheses','sufficiency'))
        roles=nomination['roles'];fields(roles,('left','right','utterance'))
        needed=('left','right') if binding['family']=='G2' else ('utterance',)
        if any(roles[k] is None for k in needed) or any(roles[k] is not None for k in set(roles)-set(needed)):raise ValueError('Wrong role shape')
        targets=[roles[k] for k in needed]
        for span in targets:exact_span(span,context)
        if len(targets)==2 and targets[0]['start']<targets[1]['end'] and targets[1]['start']<targets[0]['end']:raise ValueError('Overlapping directed G2 roles')
        if not any(t['start']<r['end'] and r['start']<t['end'] for t in targets for r in anchor['center_ranges']):
            raise ValueError('Context-only nomination has no verified center evidence')
        dependencies=nomination['dependencies']
        if type(dependencies) is not list or len(dependencies)>8:raise ValueError('Invalid dependencies')
        for span in dependencies:
            exact_span(span,context)
            if not any(t['start']<=span['start']<span['end']<=t['end'] for t in targets):raise ValueError('Declared required content outside target')
        hypotheses=nomination['provenance_hypotheses']
        if type(hypotheses) is not list or len(hypotheses)>4:raise ValueError('Invalid hypotheses')
        dimensions=[]
        for hypothesis in hypotheses:
            fields(hypothesis,('dimension','value','support'));dimensions.append(hypothesis['dimension'])
            if hypothesis['dimension'] not in ('origin','voice','recipient','adoption') or type(hypothesis['value']) is not str:raise ValueError('Invalid hypothesis')
            if hypothesis['support'] is not None:exact_span(hypothesis['support'],context)
            elif hypothesis['value']!='unknown':raise ValueError('Unsupported nonunknown hypothesis')
        if len(dimensions)!=len(set(dimensions)):raise ValueError('Repeated provenance dimension')
        if nomination['sufficiency'] not in ('unknown','apparently_complete','missing_context'):raise ValueError('Invalid sufficiency hypothesis')
        geometry=seal(dict(source_fingerprint=binding['source_fingerprint'],family=binding['family'],roles=roles))
        results.append(seal(dict(version=VERSION,status='UNTRUSTED_LITERAL_VALID',geometry_fingerprint=geometry['content_fingerprint'],
            source_fingerprint=binding['source_fingerprint'],family=binding['family'],roles=deepcopy(roles),
            raw_hypotheses=deepcopy(nomination),output_status=value['status'],request_fingerprint=binding['content_fingerprint'],
            context=deepcopy(context),anchor=deepcopy(anchor),usable_evidence=False)))
    return results


def deduplicate(records):
    groups={}
    for record in records:
        if seal(record)!=record or record['status']!='UNTRUSTED_LITERAL_VALID' or record['usable_evidence'] is not False:raise ValueError('Untrusted record seal/status differs')
        geometry=seal(dict(source_fingerprint=record['source_fingerprint'],family=record['family'],roles=record['roles']))
        if geometry['content_fingerprint']!=record['geometry_fingerprint']:raise ValueError('Foreign geometry')
        groups.setdefault(record['geometry_fingerprint'],[]).append(record)
    results=[]
    for geometry,items in sorted(groups.items()):
        unique={r['content_fingerprint']:r for r in items};items=sorted(unique.values(),key=lambda r:r['content_fingerprint'])
        claims={seal(dict(hypotheses=sorted(r['raw_hypotheses']['provenance_hypotheses'],key=lambda h:h['dimension'])))['content_fingerprint'] for r in items}
        owner=min(items,key=lambda r:(r['anchor']['start_seconds'],r['anchor']['content_fingerprint']))['anchor']['content_fingerprint']
        results.append(seal(dict(geometry_fingerprint=geometry,status='UNTRUSTED_DEDUPLICATED',origins=items,
                                canonical_owner=owner,provenance_conflict=len(claims)>1,usable_evidence=False)))
    return results


def measurement_mapping(record):
    """No interpreter, question execution, witness, Measurement or LocalEvidence."""
    if seal(record)!=record or record['status']!='UNTRUSTED_LITERAL_VALID':raise ValueError('Invalid nominee')
    return seal(dict(version='prospective-measurement-data-v1',status='BLOCKED_ADAPTER_AND_REVIEW_REQUIRED',
        source_fingerprint=record['source_fingerprint'],family=record['family'],roles=deepcopy(record['roles']),
        source_envelope={k:deepcopy(record['context'][k]) for k in ('start','end','text','source_text_sha256')},
        nomination_fingerprint=record['content_fingerprint'],request_fingerprint=record['request_fingerprint'],
        extractor_hypotheses_forwarded=False,measurement_authority=None,admission_authority=None,usable_evidence=False))
