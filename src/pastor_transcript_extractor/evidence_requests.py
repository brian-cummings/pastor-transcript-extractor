"""One injectable, no-retry request executor with durable pre-send reservations."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from contextlib import contextmanager
import fcntl
import json
import hashlib
import os
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


def ollama_runtime_identity():
    # Inspect already-installed files only: no generation, loading, pull or download.
    from .config import build_llm_config
    config=build_llm_config()
    if config.model!=OLLAMA_MODEL:
        raise ValueError('Approved generation model is gemma3:4b; configured model differs; no substitution')
    root=Path(os.environ.get('OLLAMA_MODELS',str(Path.home()/'.ollama/models'))).expanduser().resolve()
    manifest_path=root/'manifests/registry.ollama.ai/library/gemma3/4b'
    raw=manifest_path.read_bytes();manifest=strict_json(raw.decode())
    blobs=[]
    for entry in [manifest['config'],*manifest['layers']]:
        identity=entry['digest']
        if not identity.startswith('sha256:') or len(identity)!=71 or any(c not in '0123456789abcdef' for c in identity[7:]):
            raise ValueError('Invalid installed model blob identity')
        path=root/'blobs'/identity.replace(':','-')
        if path.stat().st_size!=entry['size'] or _stream_hash(path)!=identity[7:]:
            raise ValueError('Installed Ollama model blob differs; no download or substitution')
        blobs.append(dict(path=str(path),sha256=identity[7:],size=entry['size'],media_type=entry['mediaType']))
    return dict(model=OLLAMA_MODEL,base_url=local_ollama_url(config.base_url),
        manifest_path=str(manifest_path),manifest_sha256=hashlib.sha256(raw).hexdigest(),
        blobs=blobs,num_ctx=OLLAMA_CONTEXT,input_cap=OLLAMA_INPUT_CAP,
        token_accounting='utf8_byte_upper_bound_plus_4096_template_and_schema_framing',
        context_policy='round_up_required_input_plus_output_to_1024_max_131072',
        limitation='Conservative upper bound, not a Gemma tokenizer count. No context truncation permitted.')


def wire(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def ollama_context_for(body):
    # Conservative deterministic reservation; allocate only the context this body
    # needs, rounded to 1024, never silently relying on Ollama's 4096 default.
    normalized={**body,'options':{**body['options'],'num_ctx':OLLAMA_CONTEXT}}
    needed=len(wire(normalized).encode())+4096+body['options']['num_predict']
    return min(OLLAMA_CONTEXT,max(4096,((needed+1023)//1024)*1024))


def reservation(phase, phases=PHASES):
    _,_,_,i,o,ip,op=phases[phase]
    return (Decimal(i)*Decimal(ip)+Decimal(o)*Decimal(op))/Decimal(1000000)


@dataclass(frozen=True)
class RequestSpec:
    phase: str
    body: dict
    source_identity: dict
    namespace: str = 'learning-demo-v3'
    version: str = 'evidence-request-ollama-v1'
    runtime_identity: dict = field(default_factory=dict)

    @property
    def fingerprint(self): return digest(asdict(self))

    def preflight(self, encoding=None):
        provider,model,_,input_cap,output_cap,_,_=PHASES[self.phase]
        if self.body.get('model') != model:
            raise ValueError('Pinned model differs; no fallback')
        serialized=wire(self.body)
        if provider=='Ollama':
            options=self.body.get('options',{})
            if (options!={'num_ctx':ollama_context_for(self.body),'num_predict':output_cap,'temperature':0,'seed':0,'top_k':1,'top_p':1}
                or self.body.get('stream') is not False or not isinstance(self.body.get('format'),dict)
                or set(self.body)!={'model','messages','format','options','stream','keep_alive'}):
                raise ValueError('Ollama decoding/context/output limits differ')
            if self.runtime_identity:
                if self.runtime_identity['model']!=model: raise ValueError('Runtime model identity differs')
                local_ollama_url(self.runtime_identity['base_url'])
            reserved=len(serialized.encode())+4096
            if reserved>input_cap or reserved+output_cap>options['num_ctx']:
                raise ValueError(f'Input token fit failure: byte upper bound {reserved}>{input_cap} in {self.phase}; no truncation or additional batches')
            return dict(method='utf8_byte_upper_bound_plus_4096_template_and_schema_framing',
                request_upper_bound=reserved,reserved_input=reserved,cap=input_cap,
                output_cap=output_cap,num_ctx=options['num_ctx'],exact_token_count_known=False)
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


def execute(spec, ledger, store, transport, *, encoding=None):
    """Transport is supplied explicitly. A lost response consumes its reservation forever."""
    account=spec.preflight(encoding)
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
        store.write_immutable('attempts/'+key+'.json',dict(request_fingerprint=key,
            phase=spec.phase,reserved_usd=str(reservation(spec.phase)),namespace=spec.namespace))
        # Any exception leaves durable uncertain-spend reservation; caller cannot retry.
        response=transport(spec)
        halt=None
        try: validate_response(spec,response)
        except (ValueError,KeyError,TypeError) as error: halt=str(error)
        store.write_immutable('receipts/'+key+'.json',dict(request=asdict(spec),token_account=account,
            response=response,response_digest=digest(response),halt=halt))
        if halt: raise ValueError(halt)
        return response


def validate_response(spec,response):
    provider,model,_,i,o,_,_=PHASES[spec.phase]
    if response['model']!=model: raise ValueError('Resolved model differs')
    usage=response['usage']
    if type(usage['input_tokens']) is not int or not 0<=usage['input_tokens']<=i:
        raise ValueError('Provider input usage outside reservation')
    if type(usage['output_tokens']) is not int or usage['output_tokens']<0:
        raise ValueError('Invalid provider output usage')
    if provider=='Ollama' and usage['output_tokens']>o: raise ValueError('Provider output outside cap')
    if response.get('complete') is not True: raise ValueError('Incomplete/refused response; no repair/retry')


def _post(endpoint,key,body):
    import httpx
    if not key: raise ValueError('Required provider credential absent')
    with httpx.Client(timeout=120,follow_redirects=False,trust_env=False,
                      transport=httpx.HTTPTransport(retries=0)) as client:
        response=client.post(endpoint,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json=body)
    if response.status_code!=200: raise ValueError(f'Provider HTTP {response.status_code}; no retry')
    return strict_json(response.text)


def ollama_transport(spec):
    import httpx
    runtime=spec.runtime_identity
    if runtime.get('model')!=OLLAMA_MODEL: raise ValueError('Frozen Ollama runtime identity required')
    if _stream_hash(Path(runtime['manifest_path']))!=runtime['manifest_sha256']:
        raise ValueError('Ollama tag changed after freeze; no substitution')
    endpoint=local_ollama_url(runtime['base_url'])+'/api/chat'
    # Local only, no API key, proxy, redirects, auto-pull, retry or OpenAI fallback.
    with httpx.Client(timeout=600,follow_redirects=False,trust_env=False,
                      transport=httpx.HTTPTransport(retries=0)) as client:
        response=client.post(endpoint,json=spec.body)
    if response.status_code!=200: raise ValueError(f'Ollama HTTP {response.status_code}; no retry')
    raw=strict_json(response.text)
    return dict(model=raw['model'],usage=dict(input_tokens=raw['prompt_eval_count'],output_tokens=raw['eval_count']),
        complete=raw.get('done') is True and raw.get('done_reason')=='stop',output=raw['message']['content'],raw=raw)


def typesafe_transport(spec):
    raw=_post('https://api.typesafe.ai/v1/systemone',os.environ.get('TYPESAFE_API_KEY'),spec.body)
    return dict(model=raw['model'],usage=raw['usage'],complete=True,output=raw['answers'],raw=raw)
