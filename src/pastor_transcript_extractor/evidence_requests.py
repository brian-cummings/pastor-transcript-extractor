"""One injectable, no-retry request executor with durable pre-send reservations."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from decimal import Decimal
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path

from .pastor_evidence import EvidenceArtifactStore, digest
from .context_extraction_validation import strict_json

PHASES = {
    'source_reading': ('OpenAI','gpt-5.4-mini-2026-03-17',24,16384,8192,'.75','4.50'),
    'source_verification': ('TypeSafe','jev-1.13.0',24,65536,0,'.042','0'),
    'alignment_and_interpretation': ('OpenAI','gpt-5.4-mini-2026-03-17',6,32768,4096,'.75','4.50'),
    'narratives_and_pair_report': ('OpenAI','gpt-5.4-mini-2026-03-17',3,32768,4096,'.75','4.50'),
    'downstream_verification': ('TypeSafe','jev-1.13.0',9,65536,0,'.042','0'),
}


def wire(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def reservation(phase):
    _,_,_,i,o,ip,op=PHASES[phase]
    return (Decimal(i)*Decimal(ip)+Decimal(o)*Decimal(op))/Decimal(1000000)


@dataclass(frozen=True)
class RequestSpec:
    phase: str
    body: dict
    source_identity: dict
    namespace: str = 'learning-demo-v3'
    version: str = 'evidence-request-v1'

    @property
    def fingerprint(self): return digest(asdict(self))

    def preflight(self, encoding=None):
        provider,model,_,input_cap,output_cap,_,_=PHASES[self.phase]
        if self.body.get('model') != model:
            raise ValueError('Pinned model differs; no fallback')
        serialized=wire(self.body)
        if provider=='OpenAI':
            if encoding is None: raise ValueError('Pinned local OpenAI tokenizer required')
            if (self.body.get('max_completion_tokens')!=output_cap or self.body.get('n')!=1
                or self.body.get('stream') is not False or self.body.get('reasoning_effort')!='none'):
                raise ValueError('Decoding/output limits differ')
            count=len(encoding.encode(serialized,disallowed_special=()))
            reserved=count+4096
            if reserved>input_cap: raise ValueError(f'Input token fit failure: {reserved}>{input_cap} in {self.phase}; no truncation or additional batches')
            return dict(method='serialized_o200k_plus_4096_framing',serialized_tokens=count,
                        reserved_input=reserved,cap=input_cap,output_cap=output_cap)
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
    max_usd: str = '2.00'
    source_max_usd: str = '1.50'
    downstream_max_usd: str = '.50'

    def check(self, attempts, phase):
        if self.max_attempts>66 or Decimal(self.max_usd)>2:
            raise ValueError('Cannot expand frozen budget')
        if len(attempts)>=self.max_attempts or sum(r['phase']==phase for r in attempts)>=PHASES[phase][2]:
            raise ValueError('Attempt budget exhausted')
        total=sum((Decimal(r['reserved_usd']) for r in attempts),Decimal(0))+reservation(phase)
        group='source' if phase.startswith('source_') else 'downstream'
        subtotal=sum((Decimal(r['reserved_usd']) for r in attempts
            if ('source' if r['phase'].startswith('source_') else 'downstream')==group),Decimal(0))+reservation(phase)
        cap=min(Decimal(self.source_max_usd),Decimal('1.50')) if group=='source' else min(Decimal(self.downstream_max_usd),Decimal('.50'))
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
    if provider=='OpenAI' and usage['output_tokens']>o: raise ValueError('Provider output outside cap')
    if response.get('complete') is not True: raise ValueError('Incomplete/refused response; no repair/retry')


def _post(endpoint,key,body):
    import httpx
    if not key: raise ValueError('Required provider credential absent')
    with httpx.Client(timeout=120,follow_redirects=False,trust_env=False,
                      transport=httpx.HTTPTransport(retries=0)) as client:
        response=client.post(endpoint,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json=body)
    if response.status_code!=200: raise ValueError(f'Provider HTTP {response.status_code}; no retry')
    return strict_json(response.text)


def openai_transport(spec):
    raw=_post('https://api.openai.com/v1/chat/completions',os.environ.get('OPENAI_API_KEY'),spec.body)
    choices=raw['choices']; usage=raw['usage']
    complete=len(choices)==1 and choices[0]['finish_reason']=='stop' and not choices[0]['message'].get('refusal')
    return dict(model=raw['model'],usage=dict(input_tokens=usage['prompt_tokens'],output_tokens=usage['completion_tokens']),
        complete=bool(complete),output=choices[0]['message'].get('content') if choices else None,raw=raw)


def typesafe_transport(spec):
    raw=_post('https://api.typesafe.ai/v1/systemone',os.environ.get('TYPESAFE_API_KEY'),spec.body)
    return dict(model=raw['model'],usage=raw['usage'],complete=True,output=raw['answers'],raw=raw)
