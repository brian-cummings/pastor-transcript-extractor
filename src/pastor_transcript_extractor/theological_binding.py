"""Reusable, source-reviewed proposition bindings, independent of predicate contracts.

This compiler checks authored evidence, not theological truth or automatic accuracy.
G2 evidence nodes/relations and G3 address acts are reused as local review structures;
no G2/G3 production admission or measurement authority is conferred by serialization.
"""
from copy import deepcopy

from pastor_transcript_extractor.binding_evidence import context_digest, target_span, text_digest, validate_span

VERSION = 'theological-proposition-binding-v1'
NODE_ROLES = {'text_anchor', 'teaching_statement', 'reason', 'alternative', 'qualification',
              'implication', 'listener_response', 'guidance', 'obstacle'}
RELATIONS = {'explains_text', 'reason_supports_claim', 'distinguishes_concepts',
             'addresses_alternative', 'qualifies_claim', 'works_out_implication',
             'grounds_response', 'specifies_response_step', 'addresses_response_obstacle'}
ADOPTION = {'own_assertion', 'adopted', 'reported_not_adopted', 'rejected', 'undetermined'}


def bind(texts, authored, provenance):
    """Compile one reviewed utterance; no subject/relation vocabulary is required.

    'actual' means presented as spoken in the sermon/report, not historical verification.
    Polarity concerns the exact proposition, retaining its internal negations. Adoption
    concerns the preacher's use of that proposition, independently of its voiced speaker.
    Empty conditions mean none bound here, not an unconditional theological rule.
    """
    row = deepcopy(authored)
    if provenance['target_sha256'] != text_digest(texts['target_text']) or provenance['texts_sha256'] != context_digest(texts):
        raise ValueError('Binding source/context identity changed')
    if not row['binding_id'] or not row['proposition']['reading'].strip():
        raise ValueError('A binding needs an identity and a readable proposition')
    target_span(row['proposition']['span'], texts)
    if row['voice']['kind'] not in {'preacher', 'quoted_or_reported', 'unresolved'}:
        raise ValueError('Unknown source voice')
    if row['voice']['occurrence'] not in {'actual', 'projected', 'unresolved'}:
        raise ValueError('Unknown utterance occurrence')
    if row['voice']['kind'] != 'unresolved' and not row['voice']['speaker']:
        raise ValueError('A resolved voice needs its speaker')
    if row['adoption']['status'] not in ADOPTION:
        raise ValueError('Unknown adoption status')
    basis = row['adoption']['basis']
    if basis not in {'own_speech', 'explicit_endorsement', 'discourse_use', 'explicit_rejection', 'quotation_only', 'unresolved'}:
        raise ValueError('Unknown adoption evidence basis')
    if row['adoption']['status'] == 'own_assertion' and (row['voice']['kind'] != 'preacher' or row['voice']['occurrence'] != 'actual' or basis != 'own_speech'):
        raise ValueError('Own assertion requires actual preacher speech')
    if row['adoption']['status'] == 'adopted' and basis not in {'explicit_endorsement', 'discourse_use'}:
        raise ValueError('Quotation alone cannot establish adoption')
    if row['polarity']['value'] not in {'affirmed', 'denied', 'unsettled', 'unresolved'}:
        raise ValueError('Unknown proposition polarity')
    if row['expression']['value'] not in {'assertion', 'question', 'open_issue', 'unresolved'}:
        raise ValueError('Unknown surface expression')
    if row['epistemic_status']['value'] not in {'expressed_uncertainty', 'not_stated', 'unresolved'}:
        raise ValueError('Unknown expressed uncertainty status')
    for field in ('voice', 'adoption', 'polarity', 'expression', 'epistemic_status'):
        finding = row[field]
        if not finding['rationale'].strip():
            raise ValueError('Every source decision needs a review rationale')
        resolved = finding.get('status', finding.get('value', finding.get('kind'))) not in {'undetermined', 'unresolved'}
        if resolved and not finding['evidence']:
            raise ValueError('A supported decision needs exact evidence')
        for span in finding['evidence']:
            target_span(span, texts)
    # An endorsement must have discourse evidence beyond the quoted words alone.
    if row['adoption']['status'] == 'adopted':
        claim = row['proposition']['span']
        if all(s['start'] >= claim['start'] and s['end'] <= claim['end'] for s in row['adoption']['evidence']):
            raise ValueError('Adoption needs an endorsement/use frame beyond quotation alone')
    for condition in row['conditions']:
        if condition['kind'] not in {'condition', 'exception'} or not condition['rationale'].strip():
            raise ValueError('Conditions cannot be widened to rationale/concession')
        target_span(condition['span'], texts)
    for span in row['scope']['evidence']:
        validate_span(span, texts)  # context may resolve identity/scope, never a missing assertion
    if not row['scope']['reading'].strip() or not row['unknowns']:
        raise ValueError('Scope and explicit limits must remain visible')
    nodes = row['evidence_nodes']
    by_id = {n['node_id']: n for n in nodes}
    if len(by_id) != len(nodes) or row['proposition']['node_id'] not in by_id:
        raise ValueError('Duplicate or missing evidence node')
    if by_id[row['proposition']['node_id']]['span'] != row['proposition']['span']:
        raise ValueError('Proposition node must identify the literal claim')
    by_id[row['proposition']['node_id']].update(voice=row['voice']['kind'], adoption=row['adoption']['status'])
    for node in nodes:
        target_span(node['span'], texts)
        if node['role'] not in NODE_ROLES or node['adoption'] not in ADOPTION or node['voice'] not in {'preacher', 'quoted_or_reported', 'unresolved'}:
            raise ValueError('Unknown G2 evidence-node role/attribution')
        if not node['reference_status']:
            raise ValueError('External reference verification must remain explicit')
    relation_ids = set()
    for relation in row['development_relations']:
        if relation['relation_id'] in relation_ids or relation['kind'] not in RELATIONS:
            raise ValueError('Duplicate or unknown G2 development relation')
        relation_ids.add(relation['relation_id'])
        if relation['from_node'] not in by_id or relation['to_node'] not in by_id:
            raise ValueError('A development relation needs both source-grounded endpoints')
        if relation['status'] not in {'supported_observation', 'unresolved'}:
            raise ValueError('Unknown relation review status')
        if not relation['rationale'] or (relation['status'] == 'supported_observation' and not relation['evidence']):
            raise ValueError('Co-occurrence alone cannot establish a relation')
        if relation['voice'] not in {'preacher', 'quoted_or_reported', 'unresolved'} or relation['adoption'] not in ADOPTION or not relation['scope']:
            raise ValueError('Development relation attribution/scope must be explicit')
        for span in relation['stated_qualifications']:
            target_span(span, texts)
        for span in relation['evidence']:
            target_span(span, texts)
    for qualification in row['qualifications']:
        if qualification['node_id'] not in by_id or by_id[qualification['node_id']]['role'] != 'qualification' or qualification['applies_to'] != row['proposition']['node_id'] or not qualification['reading']:
            raise ValueError('A qualification needs its node, proposition and reviewed meaning')
        # Free text preserves a concession without broadening G2 qualifies_claim or G1 conditions.
    for act in row['address_acts']:
        if act['type'] not in {'acknowledgment', 'perspective_taking', 'reassurance', 'challenge', 'warning', 'invitation', 'care_offer'}:
            raise ValueError('Unknown G3 address act')
        if act['voice'] not in {'preacher', 'quoted_or_reported', 'unresolved'} or act['adoption'] not in ADOPTION:
            raise ValueError('Address voice and adoption must remain separate')
        target_span(act['utterance_span'], texts)
        if act['proposition_node'] != row['proposition']['node_id'] or not act['rationale'] or not act['link_evidence']:
            raise ValueError('Address act needs an evidenced link to this proposition')
        if act['addressee']['kind'] not in {'God_in_prayer', 'no_address', 'direct_current_listener', 'applied_we', 'general_hypothetical', 'reported_person', 'unresolved'}:
            raise ValueError('Unknown G3 addressee distinction')
        for span in act['link_evidence'] + act['addressee']['evidence']:
            target_span(span, texts)
    row.update(version=VERSION, provenance=deepcopy(provenance), authorship='Codex source-reviewed proposal; human acceptance pending',
               conditions_scope='Only conditions bound to this proposition in this target; not an unconditional doctrine',
               automatic_binding=False, semantic_validation='literal integrity only; source interpretation remains proposed')
    return row
