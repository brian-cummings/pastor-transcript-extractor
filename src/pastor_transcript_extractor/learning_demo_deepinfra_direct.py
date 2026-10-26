"""One explicitly selected Flash request with provider reasoning disabled."""
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal
import json
from pathlib import Path

from . import learning_demo as demo
from . import learning_demo_deepinfra_fit as hosted
from . import deepinfra_requests as provider
from .evidence_requests import RequestSpec,ReceiptStore,DEEPINFRA_DIRECT_VERSION
from .pastor_evidence import EvidenceArtifactStore,digest

PRIOR='f1bafae24c11abf0f6fdadb975bade428b94cef517b19a87c2723838e69cefcc'


def directory(base_dir,fingerprint):
    path=demo.build_paths(base_dir).evaluation/'learning-demo-deepinfra-direct'/fingerprint
    if path.resolve().is_relative_to(Path(__file__).parents[2].resolve()):
        raise ValueError('Generated artifacts must be outside repository')
    return path


def prepare(prior_input,base_dir=None,*,check_only=False):
    prior_input=Path(prior_input).resolve()
    if prior_input!=(hosted.directory(base_dir,PRIOR,expanded=True)/'input.json').resolve():
        raise ValueError('Direct Flash check requires the reviewed generous-output Pro stop')
    prior=json.loads(prior_input.read_text())
    if prior['input_fingerprint']!=PRIOR or digest({k:v for k,v in prior.items() if k!='input_fingerprint'})!=PRIOR:
        raise ValueError('Prior hosted input identity changed')
    for path,sha in prior['history']['preserved_files'].items():
        if demo.file_hash(Path(path))!=sha: raise ValueError('Historical evidence changed')
    store=ReceiptStore(prior_input.parent/'execution')
    result=json.loads((store.root/'results.json').read_text())
    if (result['input_fingerprint']!=PRIOR or len(store.attempts())!=1
        or result['accounting']['paid_attempts']!=1 or result['accounting']['unknown_usage_attempts']!=0
        or result['accounting']['known_output_tokens']!=65536
        or result['halt']!="Incomplete DeepInfra response (finish_reason='length'); no repair/retry"):
        raise ValueError('Prior result is not the reviewed complete-usage Pro length stop')
    # Follow the already frozen source lineage, without reconstructing a new reading.
    pro=json.loads(Path(prior['history']['prior_input']).read_text())
    local=json.loads(Path(pro['history']['prior_input']).read_text())
    original=json.loads(Path(local['history']['prior_input']).read_text())
    from .learning_demo_model_fit import verify_sources
    verify_sources(original,base_dir)
    for name in ('pastor_evidence','theological_binding','binding_evidence','learning_demo_contracts'):
        if prior['code_identity'][name]!=demo.code_identity()[name]: raise ValueError('Evidence/compiler contract changed')
    metadata=provider.public_model_metadata(provider.FLASH_MODEL)
    policy=provider.DIRECT_POLICY
    if (metadata['model']!=provider.FLASH_MODEL or metadata['native_output_schema_maximum']<policy['output_cap']
        or metadata['context']<policy['input_cap']+policy['output_cap']
        or 'can-disable-reasoning' not in metadata['capabilities'] or 'structured-output' not in metadata['capabilities']
        or Decimal(metadata['input_cents_per_token'])*10000!=Decimal(policy['input_usd_per_million'])
        or Decimal(metadata['output_cents_per_token'])*10000!=Decimal(policy['output_usd_per_million'])):
        raise ValueError('Published Flash model capabilities or full-list prices differ')
    discount=Decimal(str(metadata['discount'] or 0))
    if not discount.is_finite() or not 0<=discount<1: raise ValueError('Invalid published discount')
    old=RequestSpec(**prior['request'])
    request=replace(old,body={**deepcopy(old.body),'model':provider.FLASH_MODEL,'reasoning_effort':'none'},
        namespace=provider.DIRECT_NAMESPACE,version=DEEPINFRA_DIRECT_VERSION,runtime_identity=policy)
    account=request.preflight()
    files=[prior_input,*sorted(p for p in store.root.rglob('*.json') if p.name!='direct-flash-authorization.json')]
    packet={**deepcopy(prior),'schema_version':provider.DIRECT_NAMESPACE,'direct_from':str(prior_input),
        'request':asdict(request),'token_account':account,'published_model_metadata':metadata,
        'provider_docs':{**prior['provider_docs'],'urls':{**prior['provider_docs']['urls'],
            'model':'https://deepinfra.com/'+provider.FLASH_MODEL}},
        'code_identity':{**demo.code_identity(),'learning_demo_thinking_check':demo.file_hash(Path(hosted.thinking.__file__)),
            'deepinfra_requests':demo.file_hash(Path(provider.__file__)),
            'learning_demo_deepinfra_fit':demo.file_hash(Path(hosted.__file__)),
            'learning_demo_deepinfra_direct':demo.file_hash(Path(__file__))},
        'history':dict(prior_input=str(prior_input),prior_attempts=30,prior_local_attempts=28,prior_paid_attempts=2,
            prior_source_attempts=26,prior_synthetic_attempts=4,
            prior_known_list_price_usage_usd=result['accounting']['cumulative_known_list_price_usage_usd'],
            preserved_files={**prior['history']['preserved_files'],**{str(p):demo.file_hash(p) for p in files}}),
        'pricing':dict(reservation_basis='Full uncached list prices, independent of promotion',
            promotional_input_usd_per_million=str(Decimal(policy['input_usd_per_million'])*(1-discount)),
            promotional_output_usd_per_million=str(Decimal(policy['output_usd_per_million'])*(1-discount)),
            discount_ends_at=metadata['discount_ends_at']),
        'budget':dict(maximum_attempts=1,maximum_paid_attempts=1,max_usd='0.05',reserved_usd=str(provider.reserved_usd(request.version)),
            input_cap=policy['input_cap'],output_cap=policy['output_cap'],maximum_claims=2,cumulative_maximum_attempts=31,retries=0,fallbacks=0),
        'limitation':'User-selected Flash model with reasoning disabled; model and reasoning both change. One reviewed window, not a controlled model comparison or independent accuracy benchmark. No retry or admission.'}
    packet.pop('expanded_from',None)
    packet.pop('input_fingerprint')
    packet['input_fingerprint']=digest(packet)
    out=directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        command=f'pte analysis learning-demo model-fit deepinfra-run --base-dir {demo.build_paths(base_dir).root} --input {out / "input.json"} --experimental --approve-input {packet["input_fingerprint"]} --max-usd 0.05 --confirm-prices --json'
        (out/'preparation.md').write_text('# Flash 1017, reasoning disabled\n\n'
            f'{provider.FLASH_MODEL}; reasoning_effort=none; same complete source window and strict two-claim schema. '
            '65,536 output allowance; 49,152 input reservation; 3,780-second HTTP inactivity allowance. '
            f'Full-list reservation ${account["reserved_usd"]}; new request ceiling $0.05. '
            f'Current promotional input/output rates per million: ${packet["pricing"]["promotional_input_usd_per_million"]}/'
            f'${packet["pricing"]["promotional_output_usd_per_million"]}. '
            'Public metadata supplies no promotion end date when discount_ends_at is null. '
            'Metadata deployment/prices/discount are rechecked before execution. '
            'Prior 28 local and two paid attempts remain preserved. One new paid attempt, no retries or fallback. '
            'Unexpected reasoning is a component failure. Provider estimated cost is reported separately from full-list usage. '
            'No semantic accuracy or production admission follows from valid JSON.\n\n```sh\n'+command+'\n```\n')
    return packet,out
