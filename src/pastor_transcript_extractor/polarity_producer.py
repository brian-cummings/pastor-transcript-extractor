"""Offline materialization of saved direct decisions through the shared producer."""
from copy import deepcopy
from pathlib import Path
import json

from . import polarity_decisions as producer
from . import polarity_choice_check as check
from . import learning_demo as demo
from . import evidence_requests as requests
from .pastor_evidence import EvidenceArtifactStore,EvidencePolicy,SourceWindow,digest

SAVED='b420dad65301f19301fd9ad57703542b736118fbaf7c163ba24fb9e12c71f6a9'

# Existing V3 responsibilities, not a new measurement inventory or permission to collect.
DECISIONS=[
 dict(stage='Source eligibility and sample',question='Whose speech is this, what is eligible, and what recordings/opportunities are actually covered?',
      owner='Existing source/identity gates, SampleSpec and code; use existing reviewed metadata, never guess missing independence.',reuse='profile_evidence_supply; source windows; existing identity/content safeguards',status='Existing dependency; no admission change'),
 dict(stage='Proposition recovery',question='What qualified point is actually expressed, with which referents, modality and quantifiers?',
      owner='DeepSeek proposes candidate readings/spans; focused semantic checks assess them.',reuse='Existing category/leaf evidence first; theological_binding and binding_evidence',status='Implemented experimental candidate reader; recall/completeness unvalidated'),
 dict(stage='Voice and adoption',question='Who voices the point, is the speech actual/projected, and does the preacher adopt, report or reject it?',
      owner='Direct source-based structured decisions over proposed frames; keep these decisions separate.',reuse='Existing voice/adoption contracts, G1/G2/G3 bindings',status='Existing fields/checks; next priority for direct-decision validation'),
 dict(stage='Polarity',question='Is the exact qualified proposition affirmed, denied, explicitly unsettled, or not recoverable from evidence?',
      owner='TypeSafe direct Choice; code records a new proposed value with provenance and unknowns.',reuse='Shared polarity_decisions producer, literal compiler and EvidencePolicy',status='Direct diagnostic tested; experimental shadow producer integrated; no release validation'),
 dict(stage='Conditions, qualifications and scope',question='Which condition/exception/concession applies to which proposition, consequence, recipient and time?',
      owner='DeepSeek proposes nodes and links; typed semantic decisions assess attachment and justified absence.',reuse='Existing conditions, scope and qualifications checks; G1/G2',status='Current focused checks exist; direct attachment decisions not validated'),
 dict(stage='Relations and pastoral address',question='Does one point support/explain/qualify/apply another, and what act is addressed to whom in what circumstance?',
      owner='Candidate graph plus source-based edge/act decisions; distinguish reported acts and actual listener address.',reuse='G2 relations; G3 acts; compatible H/L/P/M leaf evidence',status='Existing representations/checks; not established by the polarity result'),
 dict(stage='Canonical alignment and hierarchy',question='Are these fully qualified meanings equivalent, merely related or different, and which dimension paths apply?',
      owner='AI proposes alignment/paths with unknown/unmapped outcomes; validate qualified equivalence; code freezes IDs.',reuse='learning_demo alignment contract; pastor_fingerprint; existing T/H/S/L/P/M meanings',status='Implemented experimental contract; no real comparison executed here'),
 dict(stage='Emphasis, aggregation and comparison',question='What attention is measured, which independent occurrences count, and what can be compared with explicit coverage?',
      owner='Reuse compatible topic measurements; deterministic deduplication, masks, numerators and denominators in code.',reuse='sermon_topics projections; pastor_fingerprint; pastor_similarity',status='Shared mathematical kernels exist; do not ask a model to invent scores or treat missing as neutral'),
 dict(stage='Interpretation and explanation',question='Does a proposed connection follow from supported premises, with alternatives, counterevidence and exact sample scope?',
      owner='DeepSeek proposes hypotheses/prose; semantic checks assess warrants; code enforces premise/source references.',reuse='generated hypotheses/narrative contracts; profile_explanatory_descriptions; profile_presentation',status='Implemented experimental seams; fingerprint/profile is not another source extractor')]


def materialize(base_dir=None):
    path=check.directory(base_dir,SAVED)/'input.json';packet=check.trial.frozen(path);root=path.parent/'execution'
    for name,sha in packet['history']['preserved_files'].items():
        if demo.file_hash(Path(name))!=sha: raise ValueError('Saved source history changed')
    spec=requests.RequestSpec(**packet['request']);receipt_path=root/'receipts'/f'{spec.fingerprint}.json'
    receipt=json.loads(receipt_path.read_text());result=json.loads((root/'results.json').read_text())
    if receipt['request']!=packet['request'] or receipt['halt'] or receipt['response_digest']!=digest(receipt['response']):
        raise ValueError('Saved direct decision receipt changed')
    requests.validate_response(spec,receipt['response'])
    if (result['input_fingerprint']!=SAVED or result['halt'] or result['accounting']['attempts']!=1
        or result['accounting']['unknown_usage_attempts'] or result['accounting']['cumulative_paid_attempts']!=62
        or check.decisions(receipt['response'],spec,packet['audit_index'])!=result['decisions']):
        raise ValueError('Saved direct decisions no longer match their receipt')
    usage=demo.usage_account(requests.ReceiptStore(root))
    if any(result['accounting'].get(k)!=v for k,v in usage.items()): raise ValueError('Saved decision accounting changed')
    # The historical manifest is validated against its own hashes, not re-executed
    # under a new implementation. Materialization consumes only existing model evidence.
    source_path=Path(packet['history']['prior_input']);source=check.trial.frozen(source_path)
    parents={};windows={};refs=[path,receipt_path,root/'results.json',source_path]
    if len(source['cases'])!=len(packet['source_receipts']): raise ValueError('Source receipt inventory changed')
    for case,reader_ref in zip(source['cases'],packet['source_receipts'],strict=True):
        reader_path=Path(reader_ref);raw=json.loads(reader_path.read_text());reader=requests.RequestSpec(**raw['request'])
        if raw['halt'] or raw['response_digest']!=digest(raw['response']): raise ValueError('Candidate reader receipt changed')
        requests.validate_response(reader,raw['response']);window=SourceWindow(**case['window']);windows[case['case_id']]=window
        relative=str(reader_path.relative_to(source_path.parent/'execution'/case['case_id']))
        checked=check.trial.context.inspect(raw['response']['output'],window,model=reader.body['model'],
            prompt_digest=digest(reader.body['messages']),raw_response_ref=relative)
        if checked['errors']: raise ValueError('Candidate is no longer literally bound')
        for parent in checked['observations']: parents[(case['case_id'],parent['binding']['binding_id'])]=parent
        refs.append(reader_path)
    derived=[];index=[]
    for question_id,audit in packet['audit_index'].items():
        if audit['origin']!='saved_claim': continue
        parent=parents.pop((audit['case_id'],audit['binding_id']));window=windows[audit['case_id']]
        row=producer.derive(parent,window,spec,receipt['response'],question_id,receipt_ref=str(receipt_path))
        derived.append(row);decision=row['producer']['polarity_decision']
        index.append(dict(case_id=audit['case_id'],binding_id=audit['binding_id'],parent_id=parent['id'],derived_id=row['id'],
            candidate_polarity=parent['binding']['polarity']['value'],proposed_polarity=decision['decision']['choice'],
            effective_polarity=row['binding']['polarity']['value'],decision_resolved=decision['decision']['diagnostically_resolved'],
            evidence_policy=EvidencePolicy().permits(row)))
    if parents or len(derived)!=6: raise ValueError('Candidate/decision coverage differs')
    manifest=dict(version=producer.VERSION,origin_input=str(path),source_input=str(source_path),
        inputs={str(p):demo.file_hash(p) for p in refs},
        code_identity={m.__name__.rsplit('.',1)[-1]:demo.file_hash(Path(m.__file__)) for m in (producer,check,check.trial.context)},
        adapter_sha256=demo.file_hash(Path(__file__)),policy='Shadow derivation only; no inherited verification, correctness-probability substitution or production admission.')
    fp=digest(manifest);out=demo.build_paths(base_dir).evaluation/'polarity-producer'/fp
    if out.resolve().is_relative_to(Path(__file__).parents[2].resolve()): raise ValueError('Artifacts must be outside repository')
    store=EvidenceArtifactStore(out);store.write_immutable('input.json',dict(**manifest,materialization_fingerprint=fp))
    store.write_immutable('observations.json',dict(version=producer.VERSION,observations=derived,index=index,production_admission=False))
    store.write_immutable('decision-map.json',dict(goal='Automatic qualified theological/pastoral fingerprints, hierarchical multidimensional comparisons and traceable interpretation; no human-authored runtime fingerprints or warrants.',
        decisions=DECISIONS,production_admission=False,generation_calls=0,paid_calls=0))
    report=dict(status='MATERIALIZED_EXPERIMENTAL_PENDING_VERIFICATION',materialization_fingerprint=fp,observations=len(derived),
        direct_decisions_resolved=sum(r['decision_resolved'] for r in index),eligible_observations=0,
        index=index,generation_calls=0,paid_calls=0,production_admission=False)
    store.write_immutable('results.json',report)
    lines=['# Direct polarity producer integration','',
        'Six new shadow observations were derived from the existing DeepSeek candidates and TypeSafe Choice receipt. Original observations and decisions are immutable.',
        'Three decisions meet the diagnostic gate; three effective values remain unresolved. Every derived observation is pending verification and unadmitted.',
        'Candidate generation and direct polarity models have separate provenance. The literal anchor is candidate-supplied, not a TypeSafe-selected warrant. No source explanation is invented.',
        'Choice probability/confidence are retained as decision uncertainty; they are not copied into field-verification correctness probabilities. Old checks are retained for audit only.',
        '', '| Stage | Decision | Existing responsibility / status |','| --- | --- | --- |']
    lines.extend('| '+r['stage']+' | '+r['question']+' | '+r['owner']+' '+r['status']+' |' for r in DECISIONS)
    lines+=['','Next validation priorities: voice/adoption, then condition/qualification attachment, then source-stated relations/address. Reuse existing leaf answers and contracts before new collection.',
        'Only polarity is newly integrated. Other direct decision families remain proposals. No new provider calls, experiment expansion, comparisons, rankings or production changes were made.']
    (out/'review.md').write_text('\n\n'.join(lines[:6])+'\n'+'\n'.join(lines[6:])+'\n')
    return report|dict(results=str(out/'results.json'),observations_file=str(out/'observations.json'),review=str(out/'review.md'),decision_map=str(out/'decision-map.json'))
