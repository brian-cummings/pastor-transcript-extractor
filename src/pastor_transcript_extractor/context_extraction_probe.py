"""Fingerprint-bound, extraction-only 24-context probe. Execution is separate."""
from __future__ import annotations
from contextlib import contextmanager
from decimal import Decimal
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
import uuid

from pastor_transcript_extractor import context_evidence_architecture_design as design
from pastor_transcript_extractor import collector_retrieval_json_v1_1 as seals
from pastor_transcript_extractor import context_extraction_validation as validation
from pastor_transcript_extractor.config import build_paths

HERE=design.old.ROOT/'docs/review-proposals/context-extraction-probe-v1'
INPUT=HERE/'input-manifest-v1.json'
EXECUTION=HERE/'execution-authorization-v1.json'
MODEL='gpt-5.4-mini-2026-03-17'
ENDPOINT='https://api.openai.com/v1/chat/completions'


def directory(base_dir=None):return build_paths(base_dir).evaluation/'context-extraction-probe-v1'


def save(path,value,*,replace=False):
    path=Path(path);value=seals.seal(value);raw=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
    if len(raw)>8*1024*1024:raise ValueError('Artifact size ceiling exceeded')
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and not replace:
        if design.old.sealed(path)!=value:raise ValueError('Immutable artifact differs')
        return value
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.partial')
    try:
        with tmp.open('xb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
        if replace:os.replace(tmp,path)
        else:os.link(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()
    return value


@contextmanager
def exclusive(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a') as out:
        try:fcntl.flock(out,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:raise ValueError('Probe is already locked') from error
        try:yield
        finally:fcntl.flock(out,fcntl.LOCK_UN)


def tokenizer(base_dir=None):
    """Exact isolated tokenizer/cache verification BEFORE importing it; no fetch."""
    lock=design.old.sealed(HERE/'runtime-lock-v1.json');base=directory(base_dir)
    if sys.version.split()[0]!=lock['python']:raise ValueError('Tokenizer Python changed')
    for name,digest in lock['files'].items():
        if design.old.file_hash(base/name)!=digest:raise ValueError('Tokenizer runtime/cache changed: '+name)
    for name,version in lock['shared_packages'].items():
        if importlib.metadata.version(name)!=version:raise ValueError('Shared HTTP/runtime package changed')
    sys.path.insert(0,str(base/'runtime'));os.environ['TIKTOKEN_CACHE_DIR']=str(base/'tokenizer-cache')
    import tiktoken
    if not Path(tiktoken.__file__).resolve().is_relative_to((base/'runtime').resolve()):raise ValueError('Foreign tokenizer import')
    if tiktoken.__version__!='0.12.0':raise ValueError('Unexpected tokenizer')
    return tiktoken.get_encoding('o200k_base')


def request(context,family):
    state=dict(context_fingerprint=context['content_fingerprint'],task_family=family,
               source_context={k:context[k] for k in ('start','end','text','has_earlier_source','has_later_source','source_snapshot_sha256')},
               word_offsets=validation.word_map(context['text']))
    return dict(model=MODEL,messages=[dict(role='system',content=validation.PROMPT),dict(role='user',content=json.dumps(state,ensure_ascii=False,separators=(',',':')))],
                response_format=dict(type='json_schema',json_schema=dict(name='untrusted_evidence_nominations_v1',strict=True,schema=validation.SCHEMA)),
                reasoning_effort='none',temperature=0,top_p=1,n=1,max_completion_tokens=2048,stream=False,store=False,service_tier='default')


def token_account(body,encoding):
    wire=json.dumps(body,ensure_ascii=False,separators=(',',':'))
    count=len(encoding.encode(wire,disallowed_special=()))
    # Complete serialized payload includes message/schema structure; reserve a
    # further 4096 tokens for provider framing. This is a client upper reservation,
    # not an assertion that the provider exposes an exact offline token count.
    reserved=count+4096
    if reserved>16384:raise ValueError('Conservative input reservation exceeds 16384; no truncation')
    return dict(serialized_payload_tokens=count,provider_framing_reserve=4096,input_reservation=reserved,
                input_hard_experiment_ceiling=16384,output_including_reasoning_max=2048)


def validate_context(context,source):
    lo,hi=context['start'],context['end']
    if (type(lo) is not int or type(hi) is not int or not source['main_span']['start']<=lo<hi<=source['main_span']['end']
            or hi-lo>6000 or source['text'][lo:hi]!=context['text']
            or context['has_earlier_source']!=(lo>source['main_span']['start'])
            or context['has_later_source']!=(hi<source['main_span']['end'])):
        raise ValueError('Context is not exact bounded canonical source')


def validate_spec(spec,experiment,sources):
    if len(spec['cases'])!=24:raise ValueError('Fixed panel requires 24 contexts')
    by_id={c['case_id']:c for c in spec['cases']}
    for case,planned in zip(spec['cases'],experiment['cases'],strict=True):
        if any(case.get(k)!=planned.get(k) for k in ('case_id','kind','route','retired_locator','parent_case_id')):
            raise ValueError('Prospective case identity changed')
        source=sources[case['video_id']];lo,hi=case['bounds'];oracle=case['oracle']
        if not source['main_span']['start']<=lo<hi<=source['main_span']['end'] or hi-lo>6000:
            raise ValueError('Source context bound changed')
        for span in [*oracle['focal_roles'].values(),*oracle['required_source_supports']]:
            if source['text'][span['start']:span['end']]!=span['text']:raise ValueError('Source oracle literal changed')
            if case['kind']=='adequate' and not lo<=span['start']<span['end']<=hi:
                raise ValueError('Adequate context lacks required source evidence')
        if oracle['adequate_context_established']!=(case['kind']=='adequate'):raise ValueError('Adequacy unresolved')
        if case['kind']=='clipped':
            parent=by_id[case['parent_case_id']]
            if (parent['video_id']!=case['video_id'] or not parent['bounds'][0]<=lo<hi<=parent['bounds'][1]
                    or not oracle['missing_essential_context']):raise ValueError('Clipped context is not a diagnostic parent subset')
        if case['kind']=='control' and not oracle['control_rule']:raise ValueError('Control review missing')


def prepare(base_dir=None):
    """Authorized materialization only; never imports an inference client."""
    plan,experiment,manifest=design.verify();authority=design.old.sealed(HERE/'authorization-v1.json')
    if authority['proposal_packet_fingerprint']!=manifest['content_fingerprint'] or not authority['panel_materialization'] or authority['execution']:
        raise ValueError('Preparation authority changed')
    spec=design.old.sealed(HERE/'source-panel-spec-v1.json')
    from pastor_transcript_extractor import collector_retrieval_workflow_v1_1 as retired
    oldpacket=retired.verify();sources=retired.sources(oldpacket)
    validate_spec(spec,experiment,sources)
    contexts=[];oracle=[]
    for case in spec['cases']:
        source=sources[case['video_id']];lo,hi=case['bounds']
        context=seals.seal(dict(start=lo,end=hi,text=source['text'][lo:hi],source_snapshot_sha256=oldpacket['source_files'][str(case['video_id'])]['sha256'],
            has_earlier_source=lo>source['main_span']['start'],has_later_source=hi<source['main_span']['end']))
        validate_context(context,source)
        contexts.append(dict(case_id=case['case_id'],video_id=case['video_id'],family='G2' if case['route']=='G2' else 'G3',context=context))
        oracle.append(dict(case_id=case['case_id'],kind=case['kind'],route=case['route'],context_fingerprint=context['content_fingerprint'],
            **case['oracle']))
    if len(contexts)!=24 or [c['case_id'] for c in contexts]!=[c['case_id'] for c in experiment['cases']]:raise ValueError('Panel identity changed')
    out=directory(base_dir)/'preparation'
    panel=save(out/'panel-v1.json',dict(version='context-extraction-panel-v1',spec_fingerprint=spec['content_fingerprint'],source_files=oldpacket['source_files'],cases=contexts,provider_requests=0))
    # Independent source-only oracle seals BEFORE requests/outputs. This is not
    # accepted receipt-bound admission authority and is never model-visible.
    oracle=save(out/'source-oracle-v1.json',dict(version='context-extraction-source-oracle-v1',panel_fingerprint=panel['content_fingerprint'],
        authority='pre-output source review only; not accepted measurement/admission authority',cases=oracle,model_outputs_seen=False))
    encoding=tokenizer(base_dir);requests=[]
    for case in contexts:
        body=request(case['context'],case['family']);account=token_account(body,encoding)
        requests.append(seals.seal(dict(case_id=case['case_id'],context_fingerprint=case['context']['content_fingerprint'],family=case['family'],body=body,token_account=account)))
    model_lock=design.old.sealed(HERE/'model-lock-v1.json')
    packet=dict(version='context-extraction-input-v1',status='PREPARED_EXECUTION_HELD',panel_path=str(out/'panel-v1.json'),panel_fingerprint=panel['content_fingerprint'],
        oracle_path=str(out/'source-oracle-v1.json'),oracle_fingerprint=oracle['content_fingerprint'],
        model_lock_fingerprint=model_lock['content_fingerprint'],proposal_packet_fingerprint=manifest['content_fingerprint'],
        limits=experiment['proposed_limits'],primary_criterion=experiment['positive_criterion'],
        requests=requests,execution_authorized=False,provider_requests_during_preparation=0,
        review_budget=dict(preparation_charge_minutes=60,remaining_active_minutes=420,total_active_minutes_max=480,accounting='Conservative preparation budget charge, not a measured throughput claim. Future audit must log active review and HOLD if incomplete within remaining budget.'),
        token_accounting=dict(serialized_payload_tokens=sum(r['token_account']['serialized_payload_tokens'] for r in requests),
            conservative_reserved_input_tokens=sum(r['token_account']['input_reservation'] for r in requests),maximum_input_tokens=393216,maximum_output_tokens=49152,
            model_list_price_ceiling_usd=str((Decimal(393216)*Decimal('.75')+Decimal(49152)*Decimal('4.5'))/1000000)),
        pins={name:design.old.file_hash(design.old.ROOT/name) for name in spec['implementation_pin_paths']})
    return save(out/'input-v1.json',packet)


def verify(base_dir=None):
    plan,experiment,manifest=design.verify()
    pointer=design.old.sealed(INPUT);path=Path(pointer['input_path'])
    if design.old.file_hash(path)!=pointer['input_sha256']:raise ValueError('Prepared input file changed')
    packet=design.old.sealed(path)
    if pointer['input_fingerprint']!=packet['content_fingerprint']:raise ValueError('Prepared input binding changed')
    spec=design.old.sealed(HERE/'source-panel-spec-v1.json')
    if packet['limits']!=experiment['proposed_limits'] or packet['primary_criterion']!=experiment['positive_criterion'] or packet['proposal_packet_fingerprint']!=manifest['content_fingerprint']:
        raise ValueError('Approved experiment scope changed')
    for name,digest in packet['pins'].items():
        path=(design.old.ROOT/name).resolve()
        if not path.is_relative_to(design.old.ROOT) or design.old.file_hash(path)!=digest:raise ValueError('Probe implementation/source-review pin changed: '+name)
    lock=design.old.sealed(HERE/'model-lock-v1.json')
    if packet['model_lock_fingerprint']!=lock['content_fingerprint'] or lock['model']!=MODEL:raise ValueError('Single-model lock changed')
    panel=design.old.sealed(Path(packet['panel_path']))
    if panel['content_fingerprint']!=packet['panel_fingerprint'] or panel['spec_fingerprint']!=spec['content_fingerprint']:raise ValueError('Panel binding changed')
    # Hash the oracle; no model-facing path reads its expected answers.
    oracle=design.old.sealed(Path(packet['oracle_path']))
    if oracle['content_fingerprint']!=packet['oracle_fingerprint'] or oracle['panel_fingerprint']!=panel['content_fingerprint']:raise ValueError('Oracle binding changed')
    if len(panel['cases'])!=24 or len(packet['requests'])!=24:raise ValueError('Fixed request inventory changed')
    source_values={}
    for vid,info in panel['source_files'].items():
        path=Path(info['path'])
        if design.old.file_hash(path)!=info['sha256']:raise ValueError('Canonical source snapshot changed')
        source_values[int(vid)]=design.old.sealed(path)
    validate_spec(spec,experiment,source_values)
    encoding=tokenizer(base_dir)
    for case,r,expected in zip(panel['cases'],packet['requests'],spec['cases'],strict=True):
        if (case['case_id']!=expected['case_id'] or case['video_id']!=expected['video_id']
                or [case['context']['start'],case['context']['end']]!=expected['bounds']
                or case['family']!=('G2' if expected['route']=='G2' else 'G3')
                or case['context']['source_snapshot_sha256']!=panel['source_files'][str(case['video_id'])]['sha256']):raise ValueError('Source/context inventory changed')
        validate_context(case['context'],source_values[case['video_id']])
        if token_account(r['body'],encoding)!=r['token_account']:raise ValueError('Request token accounting changed')
        if r['case_id']!=case['case_id'] or r['body']!=request(case['context'],case['family']) or r['context_fingerprint']!=case['context']['content_fingerprint']:
            raise ValueError('Model state/prompt/schema changed')
        if seals.seal(case['context'])!=case['context'] or seals.seal(r)!=r:raise ValueError('Context/request seal changed')
    expected_oracle=[dict(case_id=c['case_id'],kind=c['kind'],route=c['route'],context_fingerprint=state['context']['content_fingerprint'],**c['oracle']) for c,state in zip(spec['cases'],panel['cases'],strict=True)]
    if oracle['cases']!=expected_oracle or oracle['model_outputs_seen'] is not False:raise ValueError('Prospective source review changed')
    if packet['execution_authorized'] or packet['provider_requests_during_preparation']!=0:raise ValueError('Preparation scope changed')
    return packet,panel


def require_execution(packet,approve_input):
    if approve_input!=packet['content_fingerprint']:raise ValueError('Exact extraction input fingerprint required')
    if not EXECUTION.exists():raise ValueError('Separate extractor execution authorization is absent; HELD')
    authority=design.old.sealed(EXECUTION)
    if (authority.get('status')!='AUTHORIZED' or authority.get('decision_owner')!='Brian'
            or authority.get('input_fingerprint')!=packet['content_fingerprint'] or authority.get('attempts')!=24
            or authority.get('model')!=MODEL or authority.get('limits')!=packet['limits']
            or authority.get('extractor_execution') is not True
            or any(authority.get(k) is not False for k in ('Jev','measurement_admission','fresh_sources','collection_projection','automatic_retries'))):
        raise ValueError('Extractor execution decision mismatches frozen scope')
    return authority


def transport(body):
    import httpx
    key=os.environ.get('OPENAI_API_KEY')
    if not key:raise ValueError('OPENAI_API_KEY is required for the separately authorized run')
    # No SDK retries, redirects, custom endpoint, proxies, tools or fallback.
    with httpx.Client(timeout=120,follow_redirects=False,trust_env=False,transport=httpx.HTTPTransport(retries=0)) as client:
        response=client.post(ENDPOINT,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json=body)
        return dict(status_code=response.status_code,body=response.text,provider_request_id=response.headers.get('x-request-id'))


def run(base_dir=None,approve_input=None):
    packet,panel=verify(base_dir);authority=require_execution(packet,approve_input)
    # Check key before creating any attempt reservations. Never print it.
    if not os.environ.get('OPENAI_API_KEY'):raise ValueError('OPENAI_API_KEY is required')
    encoding=tokenizer(base_dir)
    for r in packet['requests']:
        if token_account(r['body'],encoding)!=r['token_account']:raise ValueError('Tokenizer accounting changed')
    out=directory(base_dir)/packet['content_fingerprint'];started=time.monotonic()
    with exclusive(out/'execution.lock'):
        if (out/'results-v1.json').exists():
            result=design.old.sealed(out/'results-v1.json')
            if result['input_fingerprint']!=packet['content_fingerprint']:raise ValueError('Foreign existing result')
            return result
        receipts=[];halt=False
        for r,case in zip(packet['requests'],panel['cases'],strict=True):
            receipt_path=out/(r['case_id']+'.receipt.json');attempt_path=out/(r['case_id']+'.attempt.json')
            if receipt_path.exists():
                receipt=design.old.sealed(receipt_path)
                if receipt['input_fingerprint']!=packet['content_fingerprint'] or receipt['request_fingerprint']!=r['content_fingerprint'] or receipt['authority_fingerprint']!=authority['content_fingerprint']:
                    raise ValueError('Foreign existing receipt')
                receipts.append(receipt)
                if receipt['halt']:halt=True;break
                continue
            if attempt_path.exists():raise ValueError('Reserved request lacks sealed receipt; uncertain spend, no retry allowed')
            if len(list(out.glob('*.attempt.json')))>=24:raise ValueError('Attempt ceiling exhausted')
            if time.monotonic()-started>1800:raise ValueError('Run wall-time ceiling reached; completed receipts preserved')
            save(attempt_path,dict(input_fingerprint=packet['content_fingerprint'],request_fingerprint=r['content_fingerprint'],authority_fingerprint=authority['content_fingerprint'],
                reserved_input_tokens=16384,reserved_output_tokens=2048,reserved_usd='.021504'))
            try:raw=transport(r['body'])
            except Exception as error:
                # Intentionally retain uncertain-attempt reservation; never retry.
                raise ValueError('Transport did not produce a sealed response; reserved attempt requires review, no automatic retry') from error
            parsed=None;validation_result=None;failure=None;halt=True
            try:
                if raw['status_code']!=200:raise ValueError('Provider HTTP error; no retry')
                parsed=validation.strict_json(raw['body'])
                if parsed.get('model')!=MODEL:raise ValueError('Provider model snapshot differs')
                usage=parsed['usage'];a,b=usage['prompt_tokens'],usage['completion_tokens']
                if type(a) is not int or type(b) is not int or not 0<=a<=16384 or not 0<=b<=2048:raise ValueError('Provider token accounting outside caps')
                if usage.get('total_tokens')!=a+b:raise ValueError('Provider token totals inconsistent')
                halt=False
                choice=parsed['choices']
                if len(choice)!=1 or choice[0]['finish_reason']!='stop' or choice[0]['message'].get('refusal'):
                    raise ValueError('Incomplete/refused output; preserve raw response, no repair/retry')
                validation_result=validation.validate_output(choice[0]['message']['content'],case['context'],case['family'])
            except (ValueError,KeyError,TypeError,IndexError) as error:
                failure=str(error)
                # Budget/model/usage/API errors stop further calls. Literal/schema
                # errors are retained as failed nominations without any retry.
                # Remains True until API/model/usage checks have all passed.
                # A malformed choice/schema is a recorded nomination failure.
            receipt=save(receipt_path,dict(version='context-extraction-receipt-v1',input_fingerprint=packet['content_fingerprint'],request_fingerprint=r['content_fingerprint'],
                context_fingerprint=case['context']['content_fingerprint'],authority_fingerprint=authority['content_fingerprint'],raw_response=raw,
                validation=validation_result,failure=failure,halt=halt,semantic_review='PENDING',usable_evidence=False))
            receipts.append(receipt)
            if halt:break
        return save(out/'results-v1.json',dict(version='context-extraction-results-v1',input_fingerprint=packet['content_fingerprint'],
            status='HOLD_TECHNICAL' if halt else 'PENDING_COMPLETE_SOURCE_AUDIT',receipt_fingerprints=[r['content_fingerprint'] for r in receipts],
            attempted_requests=len(list(out.glob('*.attempt.json'))),provider_requests=len(list(out.glob('*.attempt.json'))),
            nomination_feasibility_verdict=None,clipped_control_numeric_gate=None,semantic_measurements=None,admitted_items=None,usable_unique_evidence=None,
            elapsed_seconds=time.monotonic()-started,next_step='Codex audits every raw output, omission and control against sealed source oracle; Brian decides. No automatic downstream action.'))
