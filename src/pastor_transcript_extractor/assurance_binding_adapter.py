"""Optional narrow G1 interpretation atop a reusable source-bound proposition.

The reviewed interpretation has its own predicate-relative polarity/adoption. Generic
adoption of an actual warning does not establish adoption of a loss-of-salvation claim.
No generic known field is copied into a narrower predicate without a reviewed mapping.
"""
from copy import deepcopy

from pastor_transcript_extractor.binding_evidence import context_digest, text_digest
from pastor_transcript_extractor.profile_binding_pilot import compile_reading


def interpret(binding, texts, reviewed_interpretation):
    if (binding['provenance']['target_sha256'] != text_digest(texts['target_text'])
            or binding['provenance']['texts_sha256'] != context_digest(texts)):
        raise ValueError('Interpretation source differs from the bound proposition')
    reviewed = deepcopy(reviewed_interpretation)
    if (reviewed['unit']['candidate_id'] != binding['binding_id']
            or reviewed['unit']['claim_span'] != binding['proposition']['span']):
        raise ValueError('A subject interpretation must map this exact bound proposition')
    # Compose from the generic literal node, retaining the original reviewed mapping.
    reviewed['unit']['claim_span'] = deepcopy(binding['proposition']['span'])
    record = compile_reading(binding['provenance']['case_id'], texts, reviewed)['g1_record']
    status = ('no_match' if 'no_match' in (record['subject_id'], record['relation']) else
              'unresolved' if 'unclear' in (record['subject_id'], record['relation']) else 'matched')
    return dict(binding_id=binding['binding_id'], contract='g1-binding-v1', test_domain='assurance',
                mapping_status=status, g1_record=record,
                interpretation_basis='Existing separately reviewed G1 decisions; unchanged predicate meanings',
                nonmatch_meaning='No match in the narrow predicate contract; the generic proposition remains available',
                profile_projection=None)
