"""One injectable, no-retry request executor with durable pre-send reservations."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field, replace
from copy import deepcopy
from decimal import Decimal
from contextlib import contextmanager
import fcntl
import json
import hashlib
import os
import re
import math
from pathlib import Path

from .pastor_evidence import EvidenceArtifactStore, digest
from .context_extraction_validation import strict_json

V3_PHASES = {
    'source_reading': ('OpenAI','gpt-5.4-mini-2026-03-17',24,16384,8192,'.75','4.50'),
    'source_verification': ('TypeSafe','jev-1.13.0',24,65536,0,'.042','0'),
    'alignment_and_interpretation': ('OpenAI','gpt-5.4-mini-2026-03-17',6,32768,4096,'.75','4.50'),
    'narratives_and_pair_report': ('OpenAI','gpt-5.4-mini-2026-03-17',3,32768,4096,'.75','4.50'),
    'downstream_verification': ('TypeSafe','jev-1.13.0',9,65536,0,'.042','0'),
}


OLLAMA_MODEL = 'gemma3:4b'
OLLAMA_CONTEXT = 131072
OLLAMA_INPUT_CAP = 122880
THINKING_CHECK_VERSION = 'evidence-request-thinking-check-v1'
THINKING_CHECK_NAMESPACE = 'learning-demo-thinking-check-v1'
DEEPINFRA_VERSION = 'evidence-request-deepinfra-fit-v1'
DEEPINFRA_EXPANDED_VERSION = 'evidence-request-deepinfra-expanded-v1'
DEEPINFRA_DIRECT_VERSION = 'evidence-request-deepinfra-direct-v1'
DEEPINFRA_CORRECTION_VERSION = 'evidence-request-deepinfra-correction-v1'
DEEPINFRA_BINDING_VERSION = 'evidence-request-deepinfra-binding-retry-v1'
DEEPINFRA_ENUM_VERSION = 'evidence-request-deepinfra-enum-check-v1'
DEEPINFRA_GUIDED_VERSION = 'evidence-request-deepinfra-guided-source-v1'
DEEPINFRA_QWEN_VERIFY_VERSION = 'evidence-request-qwen-instant-verifier-v1'
DEEPINFRA_PROFILE_SUPPORT_VERSION = 'final-profile-support-v1'
DEEPINFRA_ANALYSIS_SUPPORT_VERSIONS = tuple(f'profile-analysis-support-{cap}-v1' for cap in (16384,32768,65536,131072))
DEEPINFRA_HOLDOUT_VERSIONS = ('qualifier-holdout-qwen35-v1','qualifier-holdout-qwen38-v1','qualifier-holdout-flash1017-v1')
DEEPINFRA_QWEN_STREAM_VERSIONS = tuple(v+'-stream-v1' for v in (DEEPINFRA_QWEN_VERIFY_VERSION,DEEPINFRA_PROFILE_SUPPORT_VERSION,*DEEPINFRA_ANALYSIS_SUPPORT_VERSIONS,*DEEPINFRA_HOLDOUT_VERSIONS[:2]))
THINKING_CHECK_POLICY = dict(thinking=True, output_cap=4096,
    timeout_policy='input-output-budget-v1', startup_seconds=120,
    input_tokens_per_second=100, output_tokens_per_second=8, maximum_seconds=1800)
# User-approved provider revision. The original V3 proposal remains immutable.
PHASES = {key: (('Ollama', OLLAMA_MODEL, value[2], OLLAMA_INPUT_CAP, value[4], '0', '0')
                if value[0]=='OpenAI' else value) for key,value in V3_PHASES.items()}


def local_ollama_url(value):
    from urllib.parse import urlsplit
    parsed=urlsplit(value)
    if (parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1')
        or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment):
        raise ValueError('Ollama generation requires a local loopback HTTP endpoint; no cloud/fallback')
    return value.rstrip('/')


def _stream_hash(path):
    sha=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''): sha.update(chunk)
    return sha.hexdigest()


def ollama_model_name(value):
    """Resolve an explicit local tag without remote registry lookup or downloads."""
    if not isinstance(value,str) or not re.fullmatch(
        r'[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)?(?::[A-Za-z0-9][A-Za-z0-9._-]*)?',value):
        raise ValueError('Use an installed Ollama name[:tag] or namespace/name[:tag]')
    return value if ':' in value else value+':latest'


def ollama_model_metadata(base_url,model):
    """Metadata only: /api/show neither loads nor generates with a model."""
    import httpx
    with httpx.Client(timeout=15,follow_redirects=False,trust_env=False,
                      transport=httpx.HTTPTransport(retries=0)) as client:
        response=client.post(local_ollama_url(base_url)+'/api/show',json={'model':model})
    if response.status_code!=200: raise ValueError(f'Ollama model metadata HTTP {response.status_code}; no pull/fallback')
    raw=strict_json(response.text)
    architecture=raw['model_info']['general.architecture']
    context=raw['model_info'][architecture+'.context_length']
    capabilities=raw['capabilities']
    if type(context) is not int or context<8192 or 'completion' not in capabilities:
        raise ValueError('Selected model lacks supported completion/context metadata')
    return dict(architecture=architecture,native_context=context,capabilities=sorted(capabilities),
                quantization=raw['details']['quantization_level'])


def ollama_runtime_identity(model=None):
    # Read installed files and local metadata only: no generation, loading or pull.
    from .config import build_llm_config
    config=build_llm_config();model=ollama_model_name(config.model if model is None else model)
    base_url=local_ollama_url(config.base_url)
    root=Path(os.environ.get('OLLAMA_MODELS',str(Path.home()/'.ollama/models'))).expanduser().resolve()
    name,tag=model.rsplit(':',1)
    if '/' in name: namespace,name=name.split('/')
    else: namespace='library'
    manifest_path=(root/'manifests/registry.ollama.ai'/namespace/name/tag).resolve()
    if not manifest_path.is_relative_to(root): raise ValueError('Model manifest escapes installed model directory')
    try: raw=manifest_path.read_bytes()
    except FileNotFoundError as error: raise ValueError(f'Selected Ollama model is not installed: {model}; no pull/fallback') from error
    manifest=strict_json(raw.decode())
    blobs=[]
    for entry in [manifest['config'],*manifest['layers']]:
        identity=entry['digest']
        if not identity.startswith('sha256:') or len(identity)!=71 or any(c not in '0123456789abcdef' for c in identity[7:]):
            raise ValueError('Invalid installed model blob identity')
        path=root/'blobs'/identity.replace(':','-')
        if path.stat().st_size!=entry['size'] or _stream_hash(path)!=identity[7:]:
            raise ValueError('Installed Ollama model blob differs; no download or substitution')
        blobs.append(dict(path=str(path),sha256=identity[7:],size=entry['size'],media_type=entry['mediaType']))
    metadata=ollama_model_metadata(base_url,model)
    if manifest_path.read_bytes()!=raw: raise ValueError('Ollama tag changed during model inspection')
    context=min(OLLAMA_CONTEXT,metadata['native_context'])
    return dict(model=model,base_url=base_url,metadata=metadata,
        manifest_path=str(manifest_path),manifest_sha256=hashlib.sha256(raw).hexdigest(),
        blobs=blobs,num_ctx=context,input_cap=min(OLLAMA_INPUT_CAP,context-8192),
        thinking_supported='thinking' in metadata['capabilities'],thinking=False,
        token_accounting='utf8_byte_upper_bound_plus_4096_template_and_schema_framing',
        context_policy='round_up_required_input_plus_output_to_1024_max_native_or_131072',
        limitation='Conservative upper bound, not a model tokenizer count. No context truncation permitted.')


def request_model(spec):
    """The request's frozen selection, independent of mutable process defaults."""
    if request_provider(spec)=='DeepInfra':
        from .deepinfra_requests import policy_for
        return policy_for(spec.version)['model']
    provider,default,*_=PHASES[spec.phase]
    if provider!='Ollama': return default
    return ollama_model_name(spec.runtime_identity.get('model',default))


def request_provider(spec):
    return 'DeepInfra' if spec.version in (DEEPINFRA_VERSION,DEEPINFRA_EXPANDED_VERSION,DEEPINFRA_DIRECT_VERSION,DEEPINFRA_CORRECTION_VERSION,DEEPINFRA_BINDING_VERSION,DEEPINFRA_ENUM_VERSION,DEEPINFRA_GUIDED_VERSION,DEEPINFRA_QWEN_VERIFY_VERSION,DEEPINFRA_PROFILE_SUPPORT_VERSION,*DEEPINFRA_ANALYSIS_SUPPORT_VERSIONS,*DEEPINFRA_HOLDOUT_VERSIONS,*DEEPINFRA_QWEN_STREAM_VERSIONS) else PHASES[spec.phase][0]


def request_reservation(spec):
    if request_provider(spec)=='DeepInfra':
        from .deepinfra_requests import reserved_usd
        return reserved_usd(spec.version)
    return reservation(spec.phase)


def corrective_request(original,output,errors,template):
    """Preserve the original prefix and append model output plus mechanical feedback.

    Shared with the bounded extraction experiments. This constructs a new request,
    never edits an answer or relaxes its contract; caller owns retry authorization.
    """
    content=output if isinstance(output,str) else wire(output)
    messages=deepcopy(original.body['messages'])+[
        dict(role='assistant',content=content),dict(role='user',content=template+wire(errors))]
    spec=replace(original,body={**deepcopy(original.body),'messages':messages},
        source_identity={**original.source_identity,'correction_of':original.fingerprint,
            'failed_output_digest':digest(content),'diagnostics_digest':digest(errors)})
    spec.preflight()
    return spec


def wire(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def ollama_context_for(body,context_limit=OLLAMA_CONTEXT):
    # Conservative deterministic reservation; allocate only the context this body
    # needs, rounded to 1024, never silently relying on Ollama's 4096 default.
    normalized={**body,'options':{**body['options'],'num_ctx':OLLAMA_CONTEXT}}
    needed=len(wire(normalized).encode())+4096+body['options']['num_predict']
    return min(context_limit,max(4096,((needed+1023)//1024)*1024))


def local_execution_settings(spec):
    """Explicit opt-in diagnostic policy; historical request behavior is unchanged."""
    policy=spec.runtime_identity.get('local_request_policy')
    if spec.version!=THINKING_CHECK_VERSION:
        if policy is not None: raise ValueError('Local diagnostic policy requires its pinned request version')
        return dict(thinking=False,output_cap=PHASES[spec.phase][4],timeout_seconds=600)
    if (spec.namespace!=THINKING_CHECK_NAMESPACE or spec.phase!='source_reading'
        or policy!=THINKING_CHECK_POLICY or not spec.runtime_identity.get('thinking_supported')
        or spec.runtime_identity.get('thinking') is not True):
        raise ValueError('Thinking check policy or scope differs')
    input_bound=len(wire(spec.body).encode())+4096
    seconds=policy['startup_seconds']+input_bound/policy['input_tokens_per_second']+policy['output_cap']/policy['output_tokens_per_second']
    timeout=max(300,math.ceil(seconds/60)*60)
    if timeout>policy['maximum_seconds']: raise ValueError('Required timeout exceeds diagnostic ceiling')
    return dict(thinking=True,output_cap=policy['output_cap'],timeout_seconds=timeout)


def reservation(phase, phases=PHASES):
    _,_,_,i,o,ip,op=phases[phase]
    return (Decimal(i)*Decimal(ip)+Decimal(o)*Decimal(op))/Decimal(1000000)


@dataclass(frozen=True)
class RequestSpec:
    phase: str
    body: dict
    source_identity: dict
    namespace: str = 'learning-demo-v3'
    version: str = 'evidence-request-model-selection-v2'
    runtime_identity: dict = field(default_factory=dict)

    @property
    def fingerprint(self): return digest(asdict(self))

    def preflight(self, encoding=None):
        if request_provider(self)=='DeepInfra':
            from .deepinfra_requests import preflight
            return preflight(self)
        provider,_,_,input_cap,output_cap,_,_=PHASES[self.phase]
        model=request_model(self)
        if self.body.get('model') != model:
            raise ValueError('Pinned model differs; no fallback')
        serialized=wire(self.body)
        if provider=='Ollama':
            settings=local_execution_settings(self)
            output_cap=settings['output_cap']
            options=self.body.get('options',{})
            runtime=self.runtime_identity
            context_limit=min(OLLAMA_CONTEXT,runtime.get('num_ctx',OLLAMA_CONTEXT))
            input_cap=min(input_cap,runtime.get('input_cap',input_cap))
            fields={'model','messages','format','options','stream','keep_alive'}
            if runtime.get('thinking_supported'): fields.add('think')
            if (options!={'num_ctx':ollama_context_for(self.body,context_limit),'num_predict':output_cap,'temperature':0,'seed':0,'top_k':1,'top_p':1}
                or self.body.get('stream') is not False or not isinstance(self.body.get('format'),dict)
                or set(self.body)!=fields or ('think' in fields and self.body.get('think') is not settings['thinking'])
                or runtime.get('thinking',False) is not settings['thinking']):
                raise ValueError('Ollama decoding/context/output limits differ')
            if self.runtime_identity:
                if self.runtime_identity['model']!=model: raise ValueError('Runtime model identity differs')
                local_ollama_url(self.runtime_identity['base_url'])
            reserved=len(serialized.encode())+4096
            if reserved>input_cap or reserved+output_cap>options['num_ctx']:
                raise ValueError(f'Input token fit failure: byte upper bound {reserved}>{input_cap} in {self.phase}; no truncation or additional batches')
            account=dict(method='utf8_byte_upper_bound_plus_4096_template_and_schema_framing',
                request_upper_bound=reserved,reserved_input=reserved,cap=input_cap,
                output_cap=output_cap,num_ctx=options['num_ctx'],exact_token_count_known=False)
            if self.version==THINKING_CHECK_VERSION: account['execution_policy']=settings
            return account
        # Conservative byte upper bound; no tokenizer/API call and no long-context opt-in.
        state=wire(self.body['state']).encode()
        sizes={key:len(state)+len(wire(q).encode())+1024 for key,q in self.body['questions'].items()}
        if any(size>32000 for size in sizes.values()) or len(serialized.encode())+4096>64000:
            raise ValueError('Verifier per-question/request fit failure; no truncation or extra batches')
        return dict(method='utf8_byte_upper_bound_plus_framing',question_upper_bounds=sizes,
            request_upper_bound=len(serialized.encode())+4096,reserved_input=input_cap,
            per_question_limit=32000,request_limit=64000,output_charge_tokens=0)


@dataclass(frozen=True)
class BudgetLedger:
    max_attempts: int = 66
    max_usd: str = '.10'
    source_max_usd: str = '.07'
    downstream_max_usd: str = '.03'

    def check(self, attempts, phase):
        if self.max_attempts>66 or Decimal(self.max_usd)>Decimal('.10'):
            raise ValueError('Cannot expand frozen budget')
        if len(attempts)>=self.max_attempts or sum(r['phase']==phase for r in attempts)>=PHASES[phase][2]:
            raise ValueError('Attempt budget exhausted')
        total=sum((Decimal(r['reserved_usd']) for r in attempts),Decimal(0))+reservation(phase)
        group='source' if phase.startswith('source_') else 'downstream'
        subtotal=sum((Decimal(r['reserved_usd']) for r in attempts
            if ('source' if r['phase'].startswith('source_') else 'downstream')==group),Decimal(0))+reservation(phase)
        cap=min(Decimal(self.source_max_usd),Decimal('.07')) if group=='source' else min(Decimal(self.downstream_max_usd),Decimal('.03'))
        if total>Decimal(self.max_usd) or subtotal>cap: raise ValueError('Dollar reservation ceiling exceeded')


class ReceiptStore(EvidenceArtifactStore):
    @contextmanager
    def exclusive(self):
        self.root.mkdir(parents=True,exist_ok=True)
        with (self.root/'executor.lock').open('a') as stream:
            try: fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as error: raise ValueError('Executor already active') from error
            try: yield
            finally: fcntl.flock(stream,fcntl.LOCK_UN)

    def attempts(self):
        return [strict_json(p.read_text()) for p in sorted(self.root.glob('attempts/*.json'))]


@dataclass(frozen=True)
class WireResponse:
    """HTTP result without credentials, persisted before provider decoding."""
    status_code: int
    text: str


def decode_response(spec, response):
    provider=request_provider(spec)
    if response.status_code!=200:
        raise ValueError(f'{provider} HTTP {response.status_code}; no retry')
    raw=strict_json(response.text)
    if not isinstance(raw,dict): raise ValueError('Provider response must be an object')
    if provider=='DeepInfra':
        from .deepinfra_requests import decode
        return decode(raw,spec)
    if provider=='Ollama':
        if raw.get('done') is not True or raw.get('done_reason')!='stop':
            raise ValueError(f"Incomplete Ollama response (done={raw.get('done')!r}, done_reason={raw.get('done_reason')!r}); no repair/retry")
        for name in ('prompt_eval_count','eval_count'):
            if name not in raw: raise ValueError(f'Completed Ollama response missing {name}; no retry')
        settings=local_execution_settings(spec)
        if spec.runtime_identity.get('thinking_supported') and not settings['thinking'] and raw.get('message',{}).get('thinking'):
            raise ValueError('Provider emitted thinking despite frozen disabled policy; no retry')
        return dict(model=raw['model'],usage=dict(input_tokens=raw['prompt_eval_count'],output_tokens=raw['eval_count']),
            complete=True,output=raw['message']['content'],raw=raw)
    return dict(model=raw['model'],usage=raw['usage'],complete=True,output=raw['answers'],raw=raw)


def execute(spec, ledger, store, transport, *, encoding=None):
    """Transport is supplied explicitly. A lost response consumes its reservation forever."""
    account=spec.preflight(encoding)
    if request_provider(spec)=='DeepInfra':
        from .deepinfra_requests import OneRequestLedger
        if not isinstance(ledger,OneRequestLedger) or ledger.request_version!=spec.version:
            raise ValueError('DeepInfra requires its explicit paid reservation ledger')
    key=spec.fingerprint
    with store.exclusive():
        attempts=store.attempts()
        if any(a['namespace']!=spec.namespace for a in attempts):
            raise ValueError('Receipt store namespace mismatch')
        # Stop the entire run after uncertain spend or an unrecoverable receipt.
        for attempt in attempts:
            path=store._path('receipts/'+attempt['request_fingerprint']+'.json')
            if not path.exists(): raise ValueError('Attempted request lacks receipt; uncertain spend, no retry')
            prior=strict_json(path.read_text())
            if prior.get('halt'): raise ValueError('Prior receipt halted this run')
        cached=store._path('receipts/'+key+'.json')
        if cached.exists():
            receipt=strict_json(cached.read_text())
            if receipt['request']!=asdict(spec) or receipt['token_account']!=account:
                raise ValueError('Foreign cache receipt')
            if receipt['response_digest']!=digest(receipt['response']): raise ValueError('Corrupt cached response')
            return receipt['response']
        ledger.check(attempts,spec.phase)
        attempt=dict(request_fingerprint=key,phase=spec.phase,
                     reserved_usd=str(request_reservation(spec)),namespace=spec.namespace)
        if request_provider(spec)=='DeepInfra': attempt['provider']='DeepInfra'
        store.write_immutable('attempts/'+key+'.json',attempt)
        # Any exception leaves durable uncertain-spend reservation; caller cannot retry.
        if request_provider(spec)=='DeepInfra' and getattr(transport,'supports_stream_callbacks',False):
            maximum=account.get('stream_recovery',{}).get('maximum_attempts',1)
            started=[]
            def before_stream(index):
                if index!=len(started)+1 or index>maximum:raise ValueError('Streaming attempts exceed frozen reservation')
                from .deepinfra_requests import reserved_usd
                base=spec.version.removesuffix('-stream-v1') if spec.version in DEEPINFRA_QWEN_STREAM_VERSIONS else spec.version
                store.write_immutable(f'stream-attempts/{key}/{index}/reservation.json',dict(request_fingerprint=key,attempt=index,request_version=spec.version,reserved_usd=str(reserved_usd(base))))
                started.append(index)
            def after_stream(index,raw,record):
                record['wire_digest']=digest(asdict(raw))
                store.write_immutable(f'stream-attempts/{key}/{index}/wire.json',asdict(raw))
                store.write_immutable(f'stream-attempts/{key}/{index}/telemetry.json',record)
            response=transport(spec,before_attempt=before_stream,after_attempt=after_stream,maximum_attempts=maximum)
        else:response=transport(spec)
        halt=None
        wire_response=None
        if isinstance(response,WireResponse):
            wire_response=asdict(response)
            store.write_immutable('wire-responses/'+key+'.json',wire_response)
            response=None
        try:
            if wire_response is not None: response=decode_response(spec,WireResponse(**wire_response))
            validate_response(spec,response)
        except (ValueError,KeyError,TypeError) as error: halt=str(error)
        store.write_immutable('receipts/'+key+'.json',dict(request=asdict(spec),token_account=account,
            response=response,response_digest=digest(response),wire_response_digest=(digest(wire_response) if wire_response is not None else None),halt=halt))
        if halt: raise ValueError(halt)
        return response


def validate_response(spec,response):
    if request_provider(spec)=='DeepInfra':
        from .deepinfra_requests import validate
        return validate(response,spec)
    provider,_,_,i,o,_,_=PHASES[spec.phase]
    model=request_model(spec)
    if provider=='Ollama':
        i=min(i,spec.runtime_identity.get('input_cap',i))
        o=local_execution_settings(spec)['output_cap']
    if response['model']!=model: raise ValueError('Resolved model differs')
    if response.get('complete') is not True: raise ValueError('Incomplete/refused response; no repair/retry')
    usage=response['usage']
    if type(usage['input_tokens']) is not int or not 0<=usage['input_tokens']<=i:
        raise ValueError('Provider input usage outside reservation')
    if type(usage['output_tokens']) is not int or usage['output_tokens']<0:
        raise ValueError('Invalid provider output usage')
    if provider=='Ollama' and usage['output_tokens']>o: raise ValueError('Provider output outside cap')


def _post(endpoint,key,body):
    import httpx
    if not key: raise ValueError('Required provider credential absent')
    with httpx.Client(timeout=120,follow_redirects=False,trust_env=False,
                      transport=httpx.HTTPTransport(retries=0)) as client:
        response=client.post(endpoint,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json=body)
    return WireResponse(response.status_code,response.text)


def ollama_transport(spec):
    import httpx
    runtime=spec.runtime_identity
    if not runtime or runtime.get('model')!=spec.body.get('model'):
        raise ValueError('Frozen Ollama runtime identity required')
    spec.preflight()
    if _stream_hash(Path(runtime['manifest_path']))!=runtime['manifest_sha256']:
        raise ValueError('Ollama tag changed after freeze; no substitution')
    endpoint=local_ollama_url(runtime['base_url'])+'/api/chat'
    # Local only, no API key, proxy, redirects, auto-pull, retry or OpenAI fallback.
    with httpx.Client(timeout=local_execution_settings(spec)['timeout_seconds'],follow_redirects=False,trust_env=False,
                      transport=httpx.HTTPTransport(retries=0)) as client:
        response=client.post(endpoint,json=spec.body)
    return WireResponse(response.status_code,response.text)


def typesafe_transport(spec):
    return _post('https://api.typesafe.ai/v1/systemone',os.environ.get('TYPESAFE_API_KEY'),spec.body)
