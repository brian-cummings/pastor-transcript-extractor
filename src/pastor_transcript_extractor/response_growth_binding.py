"""Narrow response/growth extension of the existing shared source-binding producer."""
from copy import deepcopy
from dataclasses import asdict, replace
from . import source_context, learning_demo_contracts as contract, reading_diagnostics
from . import evidence_requests as requests, deepinfra_requests as hosted
from . import pastor_evidence as evidence

VERSION = 'qualified-response-growth-v1'
FACETS = ('salvation', 'personal_response', 'gradual_growth', 'reassurance', 'challenge')
PROMPT = source_context.contract_packet()['reader_prompt'] + '''
This bounded extension concerns salvation, personal response and spiritual growth.
Return at most two complete relevant points from the entire supplied window. Include
relevant contrasts and qualifications, not only reassuring material. This is selected
development evidence, not an exhaustive account. Do not infer quarantined legacy
leaf measurements. Use the existing binding fields for whose voice, preacher use,
polarity, conditions and concessions. Preserve gradual growth versus already being
perfect, mistakes versus deliberate yielding, and response versus actual uptake
where present; none of those distinctions is presumed to occur in every window.
For each binding, response_growth.requested_response describes the requested or
described response, or explicitly says it is not established. growth distinguishes
gradual_growth, immediate_perfection, not_stated and unresolved; literal evidence
is required for the first two. facets describes only this point's supported local
meaning, not a leaf classification, frequency or stable pastor trait.
reader_statement is a concise, readable local account of this binding, preserving
voice, preacher adoption, proposition polarity and every meaning-changing condition
and qualification. Describe invitations as invitations and reported examples as
reported. It must not claim that listeners actually responded. It may connect
only source-grounded relations already retained in the binding. It must be usable
unchanged as a paragraph about this selected passage. No comparative priority,
dominance, frequency or causal generalization. Do not merge unrelated propositions
to evade the two-point cap. Expose unrecovered content with status saturated.
'''


def schema():
    value = source_context.schema()
    extension = contract.obj(requested_response=contract.PROSE,
        growth=contract.enum('gradual_growth', 'immediate_perfection', 'not_stated', 'unresolved'),
        evidence=contract.array(contract.SPAN, 8),
        facets=contract.array(contract.enum(*FACETS), 5), reader_statement=contract.PROSE)
    binding = value['properties']['claims']['items']
    binding['properties']['response_growth'] = extension
    binding['required'].append('response_growth')
    return value


def request(window):
    texts, mapping = window.target()
    policy = hosted.BINDING_POLICY
    body = dict(model=policy['model'], messages=[dict(role='system', content=PROMPT),
        dict(role='user', content=requests.wire(dict(texts=texts, block_mapping=mapping,
            source_identity={k:v for k,v in asdict(window).items() if k!='blocks'})))],
        max_tokens=policy['output_cap'], response_format=dict(type='json_schema',
            json_schema=dict(name='qualified_source_reading', strict=True, schema=schema())),
        temperature=0, top_p=1, stream=False, n=1, reasoning_effort='none')
    spec = requests.RequestSpec('source_reading', body,
        dict(contract=VERSION, window_digest=evidence.digest(asdict(window))),
        namespace=hosted.BINDING_NAMESPACE, version=requests.DEEPINFRA_BINDING_VERSION,
        runtime_identity=deepcopy(policy))
    spec.preflight()
    return spec


def inspect(output, window, spec, receipt):
    try:
        reading = requests.strict_json(output) if isinstance(output, str) else deepcopy(output)
    except ValueError as error:
        return dict(errors=[dict(path='$', code='json', message=str(error))], observations=[])
    errors = reading_diagnostics.shape_errors(reading, schema())
    if errors:
        return dict(errors=errors, observations=[])
    extensions = {c['binding_id']: c.pop('response_growth') for c in reading['claims']}
    checked = source_context.inspect(reading, window, model=spec.body['model'],
        prompt_digest=evidence.digest(spec.body['messages']), raw_response_ref=str(receipt))
    if checked['errors']:
        return checked
    for row in checked['observations']:
        extension = extensions[row['binding']['binding_id']]
        try:
            located = evidence.locate_literal_spans(extension, window.target()[0])
            if len(set(extension['facets'])) != len(extension['facets']):
                raise ValueError('Duplicate response facets')
            if extension['growth'] in ('gradual_growth', 'immediate_perfection') and not extension['evidence']:
                raise ValueError('Growth judgment requires literal evidence')
            if not extension['reader_statement'].strip() or not extension['requested_response'].strip():
                raise ValueError('Response and local presentation must be explicit')
            row['response_growth'] = dict(version=VERSION, **located,
                provenance=dict(request_fingerprint=spec.fingerprint, receipt=str(receipt)))
        except ValueError as error:
            checked['errors'].append(dict(path='$.claims.'+row['binding']['binding_id']+'.response_growth',
                code='literal', message=str(error)))
    if checked['errors']:
        checked['observations'] = []
    return checked


def verification(window, observations):
    """Same Jev role and full binding checks; assess the extension independently."""
    state = dict(source=dict(texts=window.target()[0]),
        items=[dict(id=o['id'], binding=o['binding'], response_growth=o['response_growth']) for o in observations])
    spec = contract.verification_request('source_verification', state, state['items'],
        dict(contract=VERSION, window_digest=evidence.digest(asdict(window))), source=True)
    if spec is None:
        return None
    body = deepcopy(spec.body)
    for i, item in enumerate(state['items']):
        for field, instruction in dict(response_growth='The requested response, growth distinction and facets are source-supported for this exact binding; not-stated is local only.',
                reader_statement='Every substantive clause in the local reader statement is supported by this binding and full source; all meaning-changing qualifications, conditions, voice/adoption, polarity and uncertainty survive. No actual audience uptake, dominance, frequency, causal generalization or comparative priority is invented.').items():
            body['questions'][item['id']+':'+field] = dict(type='noul', instructions=dict(
                instruction=f'Read items[{i}] against the complete source.texts.target_text. '+instruction),
                criteria={'true':'Correct and fully supported at its stated local scope.',
                          'false':'Unsupported, incomplete, misattributed or unresolved.'})
    spec = replace(spec, body=body, namespace=VERSION, version=VERSION)
    spec.preflight()
    return spec


def qualify(checked, response, spec):
    findings = contract.judgments(response, spec) if spec else {}
    rows = deepcopy(checked['observations'])
    for row in rows:
        checks = findings.get(row['id'], {})
        row['field_judgments'] = {k:v for k,v in checks.items() if k in evidence.REQUIRED_CHECKS}
        row['response_growth']['checks'] = {k:v for k,v in checks.items() if k not in evidence.REQUIRED_CHECKS}
        accepted, reason = evidence.EvidencePolicy().permits(row)
        extra = row['response_growth']['checks']
        accepted = accepted and set(extra)=={'response_growth','reader_statement'} and all(v['resolved'] for v in extra.values())
        row['section_eligibility'] = dict(eligible=accepted,
            reason=None if accepted else reason or 'response_growth_or_presentation_unresolved',
            verification_request=spec.fingerprint if spec else None)
    return rows
