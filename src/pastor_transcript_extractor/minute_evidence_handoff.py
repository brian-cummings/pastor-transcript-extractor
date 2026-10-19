"""Read-only verifier for the minute-block handoff proposal; no materializer."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.evidence_probe_retirement import closure

ROOT=Path(__file__).resolve().parents[2]
HERE=ROOT/'docs/review-proposals/minute-evidence-handoff-v1'


def validate(proposal):
    if (proposal['status']!='IMPLEMENTATION_PROPOSAL_ONLY'
            or proposal['processing_anchor']!='existing_retained_minute_block'
            or proposal['nomination_backend']!='existing_configured_ollama'
            or proposal['semantics_changes'] is not False
            or proposal['new_implementation_authorized'] is not False
            or proposal['provider_execution_authorized'] is not False):
        raise ValueError('Proposal scope changed')
    if proposal['context_policy']!=dict(version='minute-centered-canonical-context-v1-proposed',
            temporal_padding_seconds_per_side=120,canonical_context_characters_max=6000,
            preserve_complete_anchor=True,truncate_required_target=False,
            optional_context_only_budget_trimming=True,automatic_expansion=False,
            oversized_or_ambiguous_anchor='defer'):
        raise ValueError('Bounded context proposal changed')
    if proposal['measurement_admission']['automatic_authority_transfer'] is not False:
        raise ValueError('Nomination cannot confer evidence authority')
    if {c['case_id'] for c in proposal['worked_examples']}!={'CE-03','CE-11','CE-12'}:
        raise ValueError('Traced integration examples changed')


def verify():
    path=HERE/'proposal-v1.json'
    proposal=json.loads(path.read_text())
    if seal(proposal)!=proposal:raise ValueError('Proposal seal differs')
    validate(proposal)
    decision=closure()
    if proposal['probe_supersession_fingerprint']!=decision['content_fingerprint']:
        raise ValueError('Supersession binding differs')
    packet=json.loads((HERE/'packet-v1.json').read_text())
    if seal(packet)!=packet or packet['proposal_fingerprint']!=proposal['content_fingerprint']:
        raise ValueError('Proposal packet binding differs')
    for name,expected in packet['files'].items():
        target=(ROOT/name).resolve()
        if not target.is_relative_to(ROOT) or hashlib.sha256(target.read_bytes()).hexdigest()!=expected:
            raise ValueError('Proposal review dependency changed: '+name)
    return proposal
