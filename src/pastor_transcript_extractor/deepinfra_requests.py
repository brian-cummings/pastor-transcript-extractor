"""Explicit hosted diagnostic policy over the shared immutable request executor."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import os

from .evidence_requests import DEEPINFRA_VERSION, DEEPINFRA_EXPANDED_VERSION, DEEPINFRA_DIRECT_VERSION, DEEPINFRA_CORRECTION_VERSION, DEEPINFRA_BINDING_VERSION, DEEPINFRA_BINDING_HEADROOM_VERSION, DEEPINFRA_BINDING_FEEDBACK_VERSION, DEEPINFRA_BINDING_REASONING_VERSION, DEEPINFRA_BINDING_REASONING_TEXT_VERSION, DEEPINFRA_ENUM_VERSION, DEEPINFRA_GUIDED_VERSION, DEEPINFRA_QWEN_VERIFY_VERSION, DEEPINFRA_HOLDOUT_VERSIONS, DEEPINFRA_PROFILE_SUPPORT_VERSION, DEEPINFRA_ANALYSIS_SUPPORT_VERSIONS, DEEPINFRA_QWEN_STREAM_VERSIONS, WireResponse, wire

NAMESPACE='learning-demo-deepinfra-fit-v1'
MODEL='deepseek-ai/DeepSeek-V4-Pro-0813'
FLASH_MODEL='deepseek-ai/DeepSeek-V4.1-Flash-1017'
ENDPOINT='https://api.deepinfra.com/v1/openai/chat/completions'
INPUT_CAP=65536
OUTPUT_CAP=16384
INPUT_PRICE='1.30'
OUTPUT_PRICE='2.60'
MAX_USD='0.25'
POLICY=dict(provider='DeepInfra',model=MODEL,endpoint=ENDPOINT,input_cap=INPUT_CAP,
    output_cap=OUTPUT_CAP,input_usd_per_million=INPUT_PRICE,output_usd_per_million=OUTPUT_PRICE,
    reasoning_effort='medium',service_tier='standard',
    timeout_policy='120s_plus_input_bound_at_100tps_plus_output_at_20tps_rounded_to_minute_max_1800s',
    model_pin_limitation='Hosted dated model ID, not a verifiable weight hash; no substitution accepted')
EXPANDED_NAMESPACE='learning-demo-deepinfra-expanded-v1'
EXPANDED_POLICY={**POLICY,'input_cap':49152,'output_cap':65536,
    'timeout_policy':'120s_plus_input_bound_at_100tps_plus_output_at_20tps_rounded_to_minute_max_7200s'}
DIRECT_NAMESPACE='learning-demo-deepinfra-direct-v1'
DIRECT_POLICY={**EXPANDED_POLICY,'model':FLASH_MODEL,'reasoning_effort':'none',
    'input_usd_per_million':'0.20','output_usd_per_million':'0.60','maximum_usd':'0.05'}
CORRECTION_NAMESPACE='learning-demo-deepinfra-correction-v1'
CORRECTION_POLICY={**DIRECT_POLICY,'maximum_usd':'0.10'}
BINDING_NAMESPACE='learning-demo-binding-retry-v1'
BINDING_POLICY={**CORRECTION_POLICY}
BINDING_HEADROOM_POLICY={**BINDING_POLICY,'input_cap':65536,'maximum_usd':'0.11'}
BINDING_FEEDBACK_POLICY={**BINDING_POLICY,'input_cap':131072,'maximum_usd':'0.15'}
BINDING_REASONING_POLICY={**BINDING_FEEDBACK_POLICY,'reasoning_effort':50}
BINDING_REASONING_TEXT_POLICY={**BINDING_FEEDBACK_POLICY,'reasoning_effort':'high'}
ENUM_NAMESPACE='learning-demo-deepinfra-enum-check-v1'
ENUM_POLICY={**DIRECT_POLICY,'input_cap':8192,'output_cap':1024,'maximum_usd':'0.003','timeout_policy':POLICY['timeout_policy']}
GUIDED_NAMESPACE='learning-demo-guided-source-v1'
GUIDED_POLICY={**DIRECT_POLICY,'output_cap':8192,'maximum_usd':'0.02','timeout_policy':POLICY['timeout_policy']}

QWEN_VERIFY_NAMESPACE='qwen-instant-qualification-check-v1'
QWEN_VERIFY_POLICY={**DIRECT_POLICY,'model':'Qwen/Qwen3.8-27B','input_cap':16384,'output_cap':4096,'input_usd_per_million':'0.20','output_usd_per_million':'2.50','maximum_usd':'0.02','timeout_policy':POLICY['timeout_policy']}

PROFILE_SUPPORT_POLICY={**QWEN_VERIFY_POLICY,'output_cap':2048,'maximum_usd':'0.01'}

ANALYSIS_SUPPORT_POLICIES={version:{**PROFILE_SUPPORT_POLICY,'input_cap':cap,'maximum_usd':'0.04'} for version,cap in zip(DEEPINFRA_ANALYSIS_SUPPORT_VERSIONS,(16384,32768,65536,131072))}

HOLDOUT_POLICIES={
    DEEPINFRA_HOLDOUT_VERSIONS[0]:{**QWEN_VERIFY_POLICY,'model':'Qwen/Qwen3.5-397B-A17B','input_cap':32768,'input_usd_per_million':'0.45','output_usd_per_million':'3.00','maximum_usd':'0.04'},
    DEEPINFRA_HOLDOUT_VERSIONS[1]:{**QWEN_VERIFY_POLICY,'input_cap':32768},
    DEEPINFRA_HOLDOUT_VERSIONS[2]:{**QWEN_VERIFY_POLICY,'model':FLASH_MODEL,'input_cap':32768,'output_usd_per_million':'0.60'},
}


def policy_for(version):
    if version in DEEPINFRA_QWEN_STREAM_VERSIONS:return policy_for(version.removesuffix('-stream-v1'))
    if version in ANALYSIS_SUPPORT_POLICIES:return ANALYSIS_SUPPORT_POLICIES[version]
    if version==DEEPINFRA_PROFILE_SUPPORT_VERSION:return PROFILE_SUPPORT_POLICY
    if version in HOLDOUT_POLICIES:return HOLDOUT_POLICIES[version]
    if version==DEEPINFRA_QWEN_VERIFY_VERSION: return QWEN_VERIFY_POLICY
    if version==DEEPINFRA_VERSION: return POLICY
    if version==DEEPINFRA_EXPANDED_VERSION: return EXPANDED_POLICY
    if version==DEEPINFRA_DIRECT_VERSION: return DIRECT_POLICY
    if version==DEEPINFRA_CORRECTION_VERSION: return CORRECTION_POLICY
    if version==DEEPINFRA_BINDING_VERSION: return BINDING_POLICY
    if version==DEEPINFRA_BINDING_HEADROOM_VERSION:return BINDING_HEADROOM_POLICY
    if version==DEEPINFRA_BINDING_FEEDBACK_VERSION:return BINDING_FEEDBACK_POLICY
    if version==DEEPINFRA_BINDING_REASONING_VERSION:return BINDING_REASONING_POLICY
    if version==DEEPINFRA_BINDING_REASONING_TEXT_VERSION:return BINDING_REASONING_TEXT_POLICY
    if version==DEEPINFRA_ENUM_VERSION: return ENUM_POLICY
    if version==DEEPINFRA_GUIDED_VERSION: return GUIDED_POLICY
    raise ValueError('Unknown DeepInfra request policy')


def reserved_usd(version=DEEPINFRA_VERSION):
    if version in DEEPINFRA_QWEN_STREAM_VERSIONS:
        base=version.removesuffix('-stream-v1');cost=reserved_usd(base)
        return cost*(2 if 2*cost<=Decimal(policy_for(base).get('maximum_usd',MAX_USD)) else 1)
    policy=policy_for(version)
    return (Decimal(policy['input_cap'])*Decimal(policy['input_usd_per_million'])+
            Decimal(policy['output_cap'])*Decimal(policy['output_usd_per_million']))/Decimal(1000000)


def preflight(spec):
    if spec.version in DEEPINFRA_QWEN_STREAM_VERSIONS:
        from dataclasses import replace
        base=spec.version.removesuffix('-stream-v1');runtime=dict(spec.runtime_identity);settings=runtime.pop('stream_recovery',None)
        if not isinstance(settings,dict) or set(settings)!={'version','whitespace_threshold','maximum_attempts'} or settings['version']!='json-whitespace-v1' or type(settings['whitespace_threshold']) is not int or settings['whitespace_threshold']<1:raise ValueError('Invalid frozen streaming recovery policy')
        expected=2 if reserved_usd(spec.version)==2*reserved_usd(base) else 1
        if type(settings['maximum_attempts']) is not int or settings['maximum_attempts']!=expected or spec.namespace!=spec.version:raise ValueError('Streaming retry reservation differs')
        namespace=QWEN_VERIFY_NAMESPACE if base==DEEPINFRA_QWEN_VERIFY_VERSION else BINDING_NAMESPACE if base==DEEPINFRA_BINDING_VERSION else base
        account=preflight(replace(spec,version=base,namespace=namespace,runtime_identity=runtime))
        account['reserved_usd']=str(reserved_usd(spec.version));account['stream_recovery']=settings
        return account
    body=spec.body
    policy=policy_for(spec.version)
    binding=spec.version in (DEEPINFRA_BINDING_VERSION,DEEPINFRA_BINDING_HEADROOM_VERSION,DEEPINFRA_BINDING_FEEDBACK_VERSION,DEEPINFRA_BINDING_REASONING_VERSION,DEEPINFRA_BINDING_REASONING_TEXT_VERSION)
    corrective=(spec.version in (DEEPINFRA_CORRECTION_VERSION,DEEPINFRA_GUIDED_VERSION) or binding
        or (spec.version in ANALYSIS_SUPPORT_POLICIES and spec.source_identity.get('contract_correction_policy')=='profile-support-contract-correction-v1'))
    expanded=spec.version in (DEEPINFRA_EXPANDED_VERSION,DEEPINFRA_DIRECT_VERSION,DEEPINFRA_CORRECTION_VERSION,DEEPINFRA_BINDING_VERSION,DEEPINFRA_BINDING_HEADROOM_VERSION,DEEPINFRA_BINDING_FEEDBACK_VERSION,DEEPINFRA_BINDING_REASONING_VERSION,DEEPINFRA_BINDING_REASONING_TEXT_VERSION)
    namespace=(spec.version if spec.version in HOLDOUT_POLICIES or spec.version in ANALYSIS_SUPPORT_POLICIES or spec.version in (DEEPINFRA_PROFILE_SUPPORT_VERSION,DEEPINFRA_BINDING_HEADROOM_VERSION,DEEPINFRA_BINDING_FEEDBACK_VERSION,DEEPINFRA_BINDING_REASONING_VERSION,DEEPINFRA_BINDING_REASONING_TEXT_VERSION) else QWEN_VERIFY_NAMESPACE if spec.version==DEEPINFRA_QWEN_VERIFY_VERSION else GUIDED_NAMESPACE if spec.version==DEEPINFRA_GUIDED_VERSION else ENUM_NAMESPACE if spec.version==DEEPINFRA_ENUM_VERSION else BINDING_NAMESPACE if binding else CORRECTION_NAMESPACE if corrective else DIRECT_NAMESPACE if spec.version==DEEPINFRA_DIRECT_VERSION else EXPANDED_NAMESPACE if expanded else NAMESPACE)
    input_cap,output_cap=policy['input_cap'],policy['output_cap']
    if (spec.namespace!=namespace or spec.phase!='source_reading'
        or spec.runtime_identity!=policy or body.get('model')!=policy['model']
        or set(body)!={'model','messages','max_tokens','response_format','temperature','top_p','stream','n','reasoning_effort'}
        or body.get('max_tokens')!=output_cap or body.get('temperature')!=0 or body.get('top_p')!=1
        or body.get('stream') is not False or type(body.get('n')) is not int or body['n']!=1
        or body.get('reasoning_effort')!=policy['reasoning_effort']):
        raise ValueError('Frozen DeepInfra model, endpoint, scope or generation policy differs')
    fmt=body['response_format']
    if (not isinstance(fmt,dict) or set(fmt)!={'type','json_schema'} or fmt['type']!='json_schema'
        or set(fmt['json_schema'])!={'name','strict','schema'} or fmt['json_schema']['name']!=('profile_analysis_support' if spec.version in ANALYSIS_SUPPORT_POLICIES else 'final_profile_support' if spec.version==DEEPINFRA_PROFILE_SUPPORT_VERSION else 'qualification_judgments' if spec.version==DEEPINFRA_QWEN_VERIFY_VERSION or spec.version in HOLDOUT_POLICIES else 'qualified_source_reading')
        or fmt['json_schema']['strict'] is not True or not isinstance(fmt['json_schema']['schema'],dict)):
        raise ValueError('DeepInfra requires the explicit strict JSON schema')
    roles=[m.get('role') for m in body['messages']] if isinstance(body['messages'],list) and all(isinstance(m,dict) for m in body['messages']) else None
    permitted=([['system','user'],['system','user','assistant','user']] if corrective else [['system','user']])
    if (roles not in permitted
        or any(set(m)!={'role','content'} or not isinstance(m['content'],str) for m in body['messages'])):
        raise ValueError('DeepInfra requires exactly the frozen system/source messages')
    bound=len(wire(body).encode())+4096
    if bound>input_cap: raise ValueError('DeepInfra input exceeds reservation; no truncation')
    timeout=math.ceil((120+bound/100+output_cap/20)/60)*60
    if timeout>(7200 if expanded else 1800): raise ValueError('DeepInfra timeout exceeds bounded policy')
    return dict(method='utf8_byte_upper_bound_plus_4096_framing',request_upper_bound=bound,
        reserved_input=input_cap,output_cap=output_cap,timeout_seconds=timeout,
        reserved_usd=str(reserved_usd(spec.version)),maximum_usd=policy.get('maximum_usd',MAX_USD),
        execution_policy=dict(provider='DeepInfra',reasoning_effort=policy['reasoning_effort'],output_cap=output_cap,timeout_seconds=timeout),
        output_accounting='completion_tokens includes billed reasoning; no cached-input discount assumed')


@dataclass(frozen=True)
class OneRequestLedger:
    """One logical request; permitted streaming attempts are reserved together."""
    max_usd: str=MAX_USD
    request_version: str=DEEPINFRA_VERSION

    def check(self,attempts,phase):
        try: cap=Decimal(self.max_usd)
        except InvalidOperation as error: raise ValueError('Invalid DeepInfra dollar ceiling') from error
        maximum=policy_for(self.request_version).get('maximum_usd',MAX_USD)
        if not cap.is_finite() or cap<=0 or cap>Decimal(maximum):
            raise ValueError('DeepInfra maximum ceiling is $'+maximum)
        if phase!='source_reading' or attempts: raise ValueError('One DeepInfra attempt only; no retry')
        if reserved_usd(self.request_version)>cap: raise ValueError('DeepInfra reservation exceeds approved dollar ceiling')


@dataclass(frozen=True)
class CorrectionLedger(OneRequestLedger):
    max_usd: str='0.10'
    request_version: str=DEEPINFRA_CORRECTION_VERSION

    def check(self,attempts,phase):
        try: cap=Decimal(self.max_usd)
        except InvalidOperation as error: raise ValueError('Invalid DeepInfra dollar ceiling') from error
        if self.request_version!=DEEPINFRA_CORRECTION_VERSION or not cap.is_finite() or not 0<cap<=Decimal('0.10'):
            raise ValueError('Corrective workflow requires its frozen policy and at most $0.10')
        if phase!='source_reading' or len(attempts)>=2: raise ValueError('At most two attempts; no further retry')
        if any(a.get('namespace')!=CORRECTION_NAMESPACE or a.get('provider')!='DeepInfra'
               or Decimal(a['reserved_usd'])!=reserved_usd(self.request_version) for a in attempts):
            raise ValueError('Foreign corrective reservation')
        # Reserve both full uncached requests before starting, regardless of cache or promotion.
        if 2*reserved_usd(self.request_version)>cap: raise ValueError('Both request reservations exceed approved ceiling')


@dataclass(frozen=True)
class BindingRetryLedger(OneRequestLedger):
    max_usd: str='0.10'
    request_version: str=DEEPINFRA_BINDING_VERSION

    def check(self,attempts,phase):
        try: cap=Decimal(self.max_usd)
        except InvalidOperation as error: raise ValueError('Invalid binding retry ceiling') from error
        if self.request_version!=DEEPINFRA_BINDING_VERSION or not cap.is_finite() or not 0<cap<=Decimal('0.10'):
            raise ValueError('Binding retry requires its frozen policy within $0.10')
        if phase!='source_reading' or len(attempts)>=2: raise ValueError('One binding retry only; attempts exhausted')
        if any(a.get('namespace')!=BINDING_NAMESPACE or a.get('provider')!='DeepInfra'
               or Decimal(a['reserved_usd'])!=reserved_usd(self.request_version) for a in attempts):
            raise ValueError('Foreign binding retry reservation')
        if 2*reserved_usd(self.request_version)>cap: raise ValueError('Reserve both binding attempts before starting')


@dataclass(frozen=True)
class GuidedBindingLedger(OneRequestLedger):
    """Two guided requests per explicitly frozen binding stage; unchanged per-call cap."""
    max_usd: str='0.04'
    request_version: str=DEEPINFRA_GUIDED_VERSION

    def check(self,attempts,phase):
        try: cap=Decimal(self.max_usd)
        except InvalidOperation as error: raise ValueError('Invalid guided binding ceiling') from error
        if self.request_version!=DEEPINFRA_GUIDED_VERSION or not cap.is_finite() or not 0<cap<=Decimal('0.04'):
            raise ValueError('Guided binding stage requires its frozen policy within $0.04')
        if phase!='source_reading' or len(attempts)>=2: raise ValueError('One guided binding retry only')
        if any(a.get('namespace')!=GUIDED_NAMESPACE or a.get('provider')!='DeepInfra' or
               Decimal(a['reserved_usd'])!=reserved_usd(self.request_version) for a in attempts):
            raise ValueError('Foreign guided binding reservation')
        if (2*reserved_usd(self.request_version)>cap or
            reserved_usd(self.request_version)>Decimal(GUIDED_POLICY['maximum_usd'])):
            raise ValueError('Reserve both guided attempts without changing the per-call cap')


def decode(raw,spec=None):
    streaming=raw.get('_pte_transport')
    if streaming and streaming.get('attempts') and streaming['attempts'][-1]['outcome']!='complete':
        last=streaming['attempts'][-1]
        raise ValueError('Incomplete DeepInfra stream: '+str(last.get('error'))+'; recovery='+streaming['retry_outcome'])
    policy=policy_for(spec.version if spec is not None else DEEPINFRA_VERSION)
    if raw.get('model')!=policy['model']: raise ValueError('Resolved DeepInfra model differs; no substitution')
    if raw.get('service_tier','standard') not in ('standard','default'):
        raise ValueError('Unexpected DeepInfra service tier')
    choices=raw.get('choices')
    if not isinstance(choices,list) or len(choices)!=1: raise ValueError('DeepInfra completion inventory differs')
    choice=choices[0]
    if not isinstance(choice,dict): raise ValueError('Invalid DeepInfra choice')
    if choice.get('finish_reason')!='stop':
        raise ValueError(f"Incomplete DeepInfra response (finish_reason={choice.get('finish_reason')!r}); no repair/retry")
    message=choice['message']
    if not isinstance(message,dict): raise ValueError('Invalid DeepInfra message')
    if message.get('refusal') or message.get('tool_calls') or not isinstance(message.get('content'),str) or not message['content'].strip():
        raise ValueError('DeepInfra refused or returned no final JSON')
    usage=raw['usage']
    if not isinstance(usage,dict): raise ValueError('Invalid DeepInfra usage')
    if spec is not None and (spec.version in DEEPINFRA_QWEN_STREAM_VERSIONS or spec.version in (DEEPINFRA_DIRECT_VERSION,DEEPINFRA_CORRECTION_VERSION,DEEPINFRA_BINDING_VERSION,DEEPINFRA_ENUM_VERSION,DEEPINFRA_GUIDED_VERSION,DEEPINFRA_QWEN_VERIFY_VERSION,DEEPINFRA_PROFILE_SUPPORT_VERSION,*DEEPINFRA_ANALYSIS_SUPPORT_VERSIONS,*DEEPINFRA_HOLDOUT_VERSIONS)):
        details=usage.get('completion_tokens_details') or {}
        if not isinstance(details,dict): raise ValueError('Invalid DeepInfra token details')
        if (message.get('reasoning_content') or message.get('thinking') or message.get('reasoning')
            or details.get('reasoning_tokens',0)):
            raise ValueError('DeepInfra emitted reasoning despite frozen disabled policy; no retry')
    return dict(model=raw['model'],complete=True,output=message['content'],
        usage=dict(input_tokens=usage['prompt_tokens'],output_tokens=usage['completion_tokens']),raw=raw)


def validate(response,spec=None):
    policy=policy_for(spec.version if spec is not None else DEEPINFRA_VERSION)
    if response['model']!=policy['model'] or response.get('complete') is not True:
        raise ValueError('Incomplete or substituted DeepInfra response')
    usage=response['usage']
    for field,cap in (('input_tokens',policy['input_cap']),('output_tokens',policy['output_cap'])):
        if type(usage[field]) is not int or not 0<=usage[field]<=cap:
            raise ValueError('DeepInfra usage outside reservation')


def public_model_metadata(model=MODEL):
    """Public GET only; no authentication, source text or inference."""
    import httpx
    if model not in (MODEL,FLASH_MODEL,QWEN_VERIFY_POLICY['model'],'Qwen/Qwen3.5-397B-A17B'): raise ValueError('Unsupported pinned DeepInfra model')
    with httpx.Client(timeout=15,follow_redirects=False,trust_env=False,
                      transport=httpx.HTTPTransport(retries=0)) as client:
        response=client.get('https://api.deepinfra.com/models/'+model)
    response.raise_for_status()
    raw=response.json()
    result=dict(model=raw['model_name'],deployment_version=raw['version'],
        native_output_schema_maximum=raw['in_schema']['properties']['max_new_tokens']['maximum'],
        context=raw['max_tokens'],input_cents_per_token=str(raw['pricing']['cents_per_input_token']),
        output_cents_per_token=str(raw['pricing']['cents_per_output_token']))
    if model in (FLASH_MODEL,QWEN_VERIFY_POLICY['model'],'Qwen/Qwen3.5-397B-A17B'):
        result.update(discount=raw['pricing']['discount'],discount_ends_at=raw['pricing']['discount_ends_at'],
                      capabilities=sorted(raw['tags']))
    return result


def credential_present():
    return bool(os.environ.get('DEEPINFRA_API_KEY','').strip())


def streaming_request(spec,*,whitespace_threshold=None):
    """Opt supported requests into durably reserved streaming recovery.

    Historical versions/reservations are immutable. Recovery remains disabled if
    a second full attempt cannot fit the existing per-request dollar ceiling.
    """
    from dataclasses import replace
    if spec.version in DEEPINFRA_QWEN_STREAM_VERSIONS:return spec
    version=spec.version+'-stream-v1'
    if version not in DEEPINFRA_QWEN_STREAM_VERSIONS:raise ValueError('Streaming recovery requires a supported request')
    threshold=int(os.environ.get('PTE_DEEPINFRA_WHITESPACE_THRESHOLD','256')) if whitespace_threshold is None else whitespace_threshold
    if type(threshold) is not int or threshold<1:raise ValueError('Whitespace threshold must be a positive integer')
    settings=dict(version='json-whitespace-v1',whitespace_threshold=threshold,maximum_attempts=2 if reserved_usd(version)==2*reserved_usd(spec.version) else 1)
    result=replace(spec,version=version,namespace=version,runtime_identity={**spec.runtime_identity,'stream_recovery':settings})
    result.preflight();return result


def transport(spec,*,before_attempt=None,after_attempt=None,maximum_attempts=1):
    import httpx
    account=spec.preflight()
    key=os.environ.get('DEEPINFRA_API_KEY','').strip()
    if not key: raise ValueError('Set DEEPINFRA_API_KEY before execution')
    if spec.body['model'].startswith('Qwen/') or spec.version in DEEPINFRA_QWEN_STREAM_VERSIONS:
        from . import deepinfra_streaming
        settings=account.get('stream_recovery',{})
        if maximum_attempts>settings.get('maximum_attempts',1):raise ValueError('Streaming retry lacks frozen reservation')
        if maximum_attempts>1 and (before_attempt is None or after_attempt is None):raise ValueError('Streaming retry requires durable attempt callbacks')
        threshold=settings['whitespace_threshold'] if settings else int(os.environ.get('PTE_DEEPINFRA_WHITESPACE_THRESHOLD','256'))
        return deepinfra_streaming.transport(spec,key=key,timeout=account['timeout_seconds'],threshold=threshold,maximum_attempts=maximum_attempts,before_attempt=before_attempt,after_attempt=after_attempt)
    # Historical non-Qwen transport remains unchanged.
    with httpx.Client(timeout=account['timeout_seconds'],follow_redirects=False,trust_env=False,
                      transport=httpx.HTTPTransport(retries=0)) as client:
        response=client.post(ENDPOINT,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json=spec.body)
    return WireResponse(response.status_code,response.text)


transport.supports_stream_callbacks=True
