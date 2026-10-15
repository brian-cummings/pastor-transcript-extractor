"""Small fixed V3 boundary panel, with receipts under the configured data root."""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from decimal import Decimal
import json
from pathlib import Path

from pastor_transcript_extractor import evidence_supply_collector_design as design
from pastor_transcript_extractor import evidence_supply_revision as frozen
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.sermon_g2_feasibility_review import decision
from pastor_transcript_extractor.sermon_g3_feasibility_review import ACTS

HERE=frozen.ROOT/'docs/review-proposals/evidence-supply-boundary-v3'
INPUT=HERE/'input-v3.json'
SELECTED=(('R021','same_sentence_reading_control'),('R023','same_sentence_gloss'),('R005','safe_withholding_diagnostic'),
          ('R003','six_node_G2'),('R004','six_node_G2'),('R008','five_node_G2'),
          ('R080','nonbiblical_attribution'),('R043','nonbiblical_attribution'),('R058','repaired_doubts_anchor'),
          ('R038','long_G3'),('R092','long_G3'),('R103','long_G3'),('R053','long_G3'),
          ('R078','narration_only_control'),('R018','generic_address'),('R057','generic_address'),
          ('R073','reported_address'),('R077','reported_address'),('R111','reported_or_hypothetical_address'),
          ('R114','reported_address'),('R076','God_address_control'))
MAX_REQUESTS=33
MAX_USD=Decimal('0.088704')


def seal(value):
    return {**value,'fingerprint':frozen.fp(value)}


def build_packet():
    accepted=json.loads((design.HERE/'acceptance-decision-v3.json').read_text())
    if accepted['content_fingerprint']!=frozen.fp({k:v for k,v in accepted.items() if k!='content_fingerprint'}) or accepted['status']!='ACCEPTED' or not accepted['closed']:
        raise ValueError('Requires accepted V3 representation design')
    design_path=design.HERE/'design-v3.json'
    if frozen.v1.file_hash(design_path)!=accepted['design_file_sha256']:raise ValueError('Accepted design changed')
    original=json.loads((frozen.HERE/'input-v2.json').read_text());frozen.validate_packet(original,reproduce=False)
    refs={r['reference_id']:r for r in json.loads((frozen.HERE/'references-v2.json').read_text())['rows']}
    forward=json.loads((design.HERE/'check-design-v3.json').read_text())['rows']
    sources={v:json.loads((frozen.HERE/'sources'/f'{v}.json').read_text()) for v in original['source_ids']}
    cases=[];requests=[]
    for rid,kind in SELECTED:
        ref=refs[rid];check=ref['checks'][0]
        proposal=next((r for r in forward if r['parent_frozen_check_id']==check['check_id']),None)
        endpoints={k:check[k] for k in ('left','right','circumstance','utterance') if k in check}
        expected=check['expected'];lineage='frozen_V2_diagnostic'
        if proposal and rid in {'R021','R080','R043','R058','R078','R111'}:
            endpoints=proposal['endpoints'];expected=proposal['proposed_expected'];lineage=proposal['proposed_check_id']
        expected={**expected}
        if rid=='R005':
            expected={'explains_text':['not_linked','unclear']};lineage='new_boundary_scope_control_original_V2_unclear_check_unchanged'
        if rid=='R092':expected.update(challenge=['observed'],voice=['quoted_or_reported'],addressee=['reported_person'],recipient_circumstance_binding=['bound_in_target','bound_context_resolved'])
        if rid=='R076':expected.update(**{act:['not_observed','unclear'] for act in ACTS},voice=['quoted_or_reported','unclear'])
        candidate=design.represent(sources[ref['video_id']],ref['capability'],endpoints)
        if candidate['status']!='represented':raise ValueError('Prepared panel case is not representable')
        shapes=design.request_shapes(candidate);case_id=f'B3-{rid}'
        case=dict(case_id=case_id,parent_reference_id=rid,kind=kind,video_id=ref['video_id'],capability=ref['capability'],candidate=candidate,
                  source_check_lineage=lineage,expected=expected,parent_frozen_check=check,request_keys=[],
                  audit_scope='Every positive and every source/recipient/stance/act/boundary failure, including unscored fields. Check full source as well as supplied state; missing context is a boundary finding.')
        for shape in shapes:
            request=dict(case_id=case_id,capability=ref['capability'],phase=shape['phase'],model=frozen.MODEL,
                         state=shape['state'],questions=shape['questions'],question_version=shape['question_version'])
            request['request_key']=frozen.fp(request)
            wire=dict(model=request['model'],state=request['state'],questions={k:dict(type='choice',**v) for k,v in request['questions'].items()})
            if len(json.dumps(wire,ensure_ascii=False).encode())>60000:raise ValueError('Panel request exceeds byte guard')
            requests.append(request);case['request_keys'].append(request['request_key'])
        cases.append(case)
    if len(requests)!=MAX_REQUESTS:raise ValueError('Fixed small-panel request ceiling changed')
    pins={**original['source_files'],str(design_path.relative_to(frozen.ROOT)):accepted['design_file_sha256']}
    for path in (Path(design.__file__),Path(__file__),design.HERE/'acceptance-decision-v3.json',design.HERE/'check-design-v3.json',HERE/'CRITERIA.md'):
        pins[str(path.relative_to(frozen.ROOT))]=frozen.v1.file_hash(path)
    packet=dict(version='semantic-boundary-panel-v3',status='prepared_authorized_small_panel_only',model=frozen.MODEL,provider_requests_during_preparation=0,
                accepted_design_fingerprint=accepted['design_fingerprint'],source_ids=original['source_ids'],cases=cases,requests=requests,input_hashes=pins,
                budget=dict(maximum_attempts=MAX_REQUESTS,maximum_input_tokens=MAX_REQUESTS*frozen.CONTEXT_TOKENS,maximum_list_price_usd=str(MAX_USD),
                            automatic_retries=0,per_attempt_reserved_tokens=frozen.CONTEXT_TOKENS,input_usd_per_million='0.042',output_usd_per_million='0',pricing_checked_on='2026-10-15',price_source='https://docs.typesafe.ai/models'),
                authorization=dict(decision_owner='Brian',date='2026-10-15',scope='Prepared small boundary/geometry panel only; Brian executes the fixed pte command.',small_panel_authorized=True,full_source_rerun_authorized=False,ranker_optimization_authorized=False,construct_tuning_authorized=False,collection_projection_scoring_authorized=False),
                holds=['No G1 requests or G1/G2/G3 contract changes','No ranker changes or discovery claim','No whole-source provider rerun','No collection/projection/comparison/scoring','No reuse of V2 answers for changed request states'],
                source_audit_and_Brian_decision_required=True)
    packet['content_fingerprint']=frozen.fp(packet)
    return packet


def validate_packet(packet,reproduce=True):
    if packet['content_fingerprint']!=frozen.fp({k:v for k,v in packet.items() if k!='content_fingerprint'}):raise ValueError('Boundary packet fingerprint mismatch')
    for name,digest in packet['input_hashes'].items():
        path=(frozen.ROOT/name).resolve()
        if not path.is_relative_to(frozen.ROOT.resolve()) or frozen.v1.file_hash(path)!=digest:raise ValueError(f'Pinned boundary input changed: {name}')
    if packet['budget']['maximum_attempts']!=MAX_REQUESTS or len(packet['requests'])!=MAX_REQUESTS or Decimal(packet['budget']['maximum_list_price_usd'])!=MAX_USD or packet['budget']['maximum_input_tokens']!=MAX_REQUESTS*frozen.CONTEXT_TOKENS or packet['budget']['automatic_retries']!=0:
        raise ValueError('Small-panel budget changed')
    keys=[]
    for r in packet['requests']:
        if r['request_key']!=frozen.fp({k:v for k,v in r.items() if k!='request_key'}):raise ValueError('Boundary request identity mismatch')
        keys.append(r['request_key'])
    if len(set(keys))!=len(keys):raise ValueError('Duplicate boundary requests')
    if reproduce and build_packet()!=packet:raise ValueError('Boundary panel no longer reproduces')


def output_directory(base_dir=None):
    base=build_paths(base_dir).root.resolve()
    if base.is_relative_to(frozen.ROOT.resolve()):raise ValueError('Runtime receipts/results must be under the configured data base, outside the repository')
    directory=(base/'evaluation'/'evidence-supply-boundary-v3').resolve()
    if directory.is_relative_to(frozen.ROOT.resolve()):raise ValueError('Runtime directory resolves into the repository')
    return directory


@contextmanager
def execution_lock(directory):
    import fcntl
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/'execution.lock').open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Boundary panel is already running; do not start a second process')
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def read_cache(packet,directory):
    path=directory/'request-ledger.json'
    if path.exists():
        ledger=json.loads(path.read_text());frozen._verify_seal(ledger)
        if ledger['input_fingerprint']!=packet['content_fingerprint'] or ledger['maximum_attempts']!=MAX_REQUESTS:raise ValueError('Ledger belongs to a different boundary panel')
    else:ledger=dict(input_fingerprint=packet['content_fingerprint'],approval_key=packet['content_fingerprint'],authorization_scope='Fixed 21-case boundary panel only',maximum_attempts=MAX_REQUESTS,attempts=[])
    attempts={a['request_key']:a for a in ledger['attempts']};keys={r['request_key'] for r in packet['requests']}
    if len(attempts)!=len(ledger['attempts']) or not set(attempts)<=keys:raise ValueError('Duplicate/unknown charged attempts')
    if ledger.get('approval_key')!=packet['content_fingerprint'] or any(a['reserved_input_tokens']!=frozen.CONTEXT_TOKENS or Decimal(a['reserved_usd'])!=frozen.PRICE*frozen.CONTEXT_TOKENS for a in ledger['attempts']):raise ValueError('Attempt reservation/authorization drift')
    if sum(Decimal(a['reserved_usd']) for a in ledger['attempts'])>MAX_USD:raise ValueError('Charged ceiling exceeded')
    reused={}
    for request in packet['requests']:
        key=request['request_key'];receipt=directory/'receipts'/(key+'.json')
        if key in attempts:
            if not receipt.exists() or attempts[key]['status'] not in {'attempted','validated'}:raise ValueError('Failed/interrupted charged attempt needs a separate recovery decision; no automatic replacement')
            value=json.loads(receipt.read_text());frozen._verify_seal(value)
            if value['request_key']!=key or value['input_fingerprint']!=packet['content_fingerprint']:raise ValueError('Receipt belongs to another request')
            reused[key]=frozen.validate_response(value['response'],request)
            attempts[key].update(status='validated',usage=reused[key]['usage'])
        elif receipt.exists():raise ValueError('Orphan receipt without charged attempt')
    if len(ledger['attempts'])+len(keys)-len(reused)>MAX_REQUESTS:raise ValueError('Insufficient remaining attempt budget')
    if (directory/'receipts').exists() and {p.stem for p in (directory/'receipts').glob('*.json')}-keys:raise ValueError('Foreign receipts in boundary cache')
    return ledger,reused


def execute(packet,approval_key,base_dir=None,provider_factory=frozen.HTTPProvider,progress=print):
    validate_packet(packet)
    if approval_key!=packet['content_fingerprint']:raise ValueError('Requires exact --approve-paid-packet fingerprint')
    directory=output_directory(base_dir)
    with execution_lock(directory):
        if (directory/'acceptance-decision.json').exists():raise ValueError('Boundary gate already closed; no new execution')
        ledger,reused=read_cache(packet,directory);provider=None;rows=[]
        try:
            for index,request in enumerate(packet['requests'],1):
                key=request['request_key'];progress(f'[{index}/{MAX_REQUESTS}] {request["case_id"]} {request["phase"]}: '+('cached' if key in reused else 'requesting'),flush=True)
                if key in reused:raw=reused[key]
                else:
                    if len(ledger['attempts'])>=MAX_REQUESTS:raise ValueError('Attempt ceiling reached')
                    if provider is None:provider=provider_factory()
                    attempt=dict(request_key=key,status='attempted',reserved_input_tokens=frozen.CONTEXT_TOKENS,reserved_usd=str(frozen.PRICE*frozen.CONTEXT_TOKENS))
                    ledger['attempts'].append(attempt);frozen.dump(directory/'request-ledger.json',seal(ledger))
                    response=provider.assess(request)
                    frozen.dump(directory/'receipts'/(key+'.json'),seal(dict(request_key=key,input_fingerprint=packet['content_fingerprint'],response=response)))
                    raw=frozen.validate_response(response,request)
                    attempt.update(status='validated',usage=raw['usage']);frozen.dump(directory/'request-ledger.json',seal(ledger))
                rows.append(dict(request_key=key,case_id=request['case_id'],phase=request['phase'],raw_answers=raw['answers'],usage=raw['usage'],resolved_model=raw['model']))
                progress(f'[{index}/{MAX_REQUESTS}] validated; input_tokens={raw["usage"]["input_tokens"]}',flush=True)
        finally:
            if provider is not None:provider.close()
        frozen.dump(directory/'request-ledger.json',seal(ledger))
        report=interpret(packet,rows);frozen.dump(directory/'results-v3.json',report)
        (directory/'results-v3.md').write_text(render_results(report))
        return report


def interpret(packet,rows):
    bykey={r['request_key']:r for r in rows}
    if len(bykey)!=len(rows) or set(bykey)!={r['request_key'] for r in packet['requests']}:raise ValueError('Incomplete boundary result inventory')
    observations=[]
    for case in packet['cases']:
        phases=[];decisions={}
        for key in case['request_keys']:
            row=bykey[key];selected={k.removeprefix('p0_'):decision(v) for k,v in row['raw_answers'].items()}
            if set(decisions)&set(selected):raise ValueError('Phase decisions conflict; no overwriting')
            decisions.update(selected);phases.append(dict(phase=row['phase'],decisions=selected,raw_answers=row['raw_answers'],request_key=key))
        differences=[dict(field=k,expected=allowed,actual=decisions.get(k)) for k,allowed in case['expected'].items() if decisions.get(k) not in allowed]
        critical=[]
        if case['kind']=='narration_only_control' and any(decisions.get(act)=='observed' for act in ACTS):critical.append('narration_or_neighbor_promoted_to_addressed_act')
        if case['kind']=='God_address_control' and any(decisions.get(act)=='observed' for act in ACTS):critical.append('prayer_promoted_to_person_directed_act')
        if case['kind']=='nonbiblical_attribution' and (decisions.get('explains_text')=='linked' or decisions.get('left_voice')=='preacher'):critical.append('nonbiblical_text_anchor_or_wrong_source_voice')
        if case['capability']=='G3' and case['candidate']['endpoints']['circumstance'] is None and decisions.get('recipient_circumstance_binding') in {'bound_in_target','bound_context_resolved'}:critical.append('incompatible_null_circumstance_binding')
        if case['kind'] in {'long_G3','reported_address','reported_or_hypothetical_address','God_address_control'} and case['expected'].get('voice') and 'preacher' not in case['expected']['voice'] and decisions.get('voice')=='preacher':critical.append('wrong_reported_source_voice')
        if case['kind'] in {'reported_address','reported_or_hypothetical_address'} and (decisions.get('addressee')=='direct_current_listener' or decisions.get('adoption')=='own_or_adopted'):critical.append('unsupported_reported_to_current_adoption_transfer')
        if case['capability']=='G3':
            combined=design.combine_address_phases(case['candidate'],dict(utterance=case['candidate']['endpoints']['utterance'],target=case['candidate']['act_target'],decisions=phases[0]['decisions']),dict(utterance=case['candidate']['endpoints']['utterance'],target=case['candidate']['binding_target'],decisions=phases[1]['decisions']))
        else:combined=None
        observations.append(dict(case_id=case['case_id'],phases=phases,decisions=decisions,prepared_field_differences=differences,automatic_critical_flags=critical,
                                 guarded_local_payload=combined,source_audit='pending_every_positive_and_unscored_field_failure',pastor_credit=False))
    usage=dict(attempts=len(rows),input_tokens=sum(r['usage']['input_tokens'] for r in rows),output_tokens=sum(r['usage']['output_tokens'] for r in rows))
    report=dict(version='semantic-boundary-panel-v3-results',input_fingerprint=packet['content_fingerprint'],status='pending_Codex_source_audit_and_Brian_decision',
                usage=usage,actual_list_price_usd=str(Decimal(usage['input_tokens'])*frozen.PRICE),raw_rows=rows,observations=observations,
                usable_evidence_items=None,discovery_readiness=None,pastor_projection=None,quality_score=None)
    report['content_fingerprint']=frozen.fp(report)
    return report


def render_results(report):
    return '\n'.join(['# Small V3 semantic boundary validation','', '**Execution complete; Codex source audit and Brian decision pending. No automatic PASS.**','',
                      f'Requests: {report["usage"]["attempts"]}; input tokens: {report["usage"]["input_tokens"]}; list-price cost: ${report["actual_list_price_usd"]}.','',
                      '| Case | Prepared field differences | Automatic critical flags |','| --- | ---: | --- |',
                      *[f'| {r["case_id"]} | {len(r["prepared_field_differences"])} | {", ".join(r["automatic_critical_flags"]) or "none automatically flagged; audit pending"} |' for r in report['observations']], '',
                      'All positive fields and unscored failures require source audit against supplied states and the full source. Guarded/quarantined errors still count. No discovery, collection or projection approval.',''])


def write_packet(packet):
    HERE.mkdir(parents=True,exist_ok=True);frozen.dump(INPUT,packet)
    body_sizes=[len(json.dumps(dict(model=r['model'],state=r['state'],questions={k:dict(type='choice',**v) for k,v in r['questions'].items()}),ensure_ascii=False).encode()) for r in packet['requests']]
    lines=['# V3 small semantic boundary panel','', '**Brian authorizes this fixed panel only; Brian executes the CLI command. No full-source rerun.**','',
           f'{len(packet["cases"])} prepared cases, {len(packet["requests"])} maximum paid attempts, zero retries, `{packet["model"]}`. Public-list-price ceiling **${MAX_USD}** from 33 × 64,000 reserved input tokens. Actual usage is not the reservation. Output is free at the frozen $0.042/M input price ([official pricing](https://docs.typesafe.ai/models), checked 2026-10-15).', '',
           f'Actual serialized request bodies: {min(body_sizes):,}–{max(body_sizes):,} UTF-8 bytes; total {sum(body_sizes):,} bytes. This is payload measurement, not a tokenizer or actual charge estimate.', '',
           'The accepted representation, source endpoints and canonical questions are reused. No ranker or G1 calls. Proposed forward controls are versioned here; V2 expectations/results stay unchanged. The repaired R058 anchor is explicitly new. All source-only search/recall limitations remain held.', '',
           '## Cases', '', '| Case | Source | Boundary class | Requests |', '| --- | ---: | --- | ---: |',
           *[f'| {c["case_id"]} | {c["video_id"]} | {c["kind"]} | {len(c["request_keys"])} |' for c in packet['cases']], '',
           '## Run', '', '```sh','pte analysis evidence-supply-boundary-validation --paid-run-preflight',
           'pte analysis evidence-supply-boundary-validation --execute \\',f'  --approve-paid-packet {packet["content_fingerprint"]}','```','',
           'Runtime receipts, ledger and results go under `<configured-base-dir>/evaluation/evidence-supply-boundary-v3/`, outside the repository. `--base-dir` overrides the application base directory. Progress prints before/after each request. Valid same-packet receipts replay without calls; failed/lost replies retain their reservation and stop for a separate recovery decision. A process lock prevents concurrent execution. V2 answers are never reused.', '',
           'Read `CRITERIA.md` and `input-v3.json` for source-linked inputs, prepared expectations and the frozen decision rules. Codex audits every positive/unscored failure after Brian provides results. PASS permits preparing a separate discovery-readiness decision only; no collection or projection is activated.','']
    (HERE/'REVIEW.md').write_text('\n'.join(lines))
