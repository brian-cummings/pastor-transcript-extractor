"""Three frozen source windows, shared guided reader and bounded TypeSafe loop."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal,InvalidOperation
import json
import os
from pathlib import Path
from httpx import HTTPError

from . import learning_demo as demo
from . import learning_demo_five_windows as five
from . import learning_demo_model_fit as fit
from . import source_context as context
from . import source_enum_check as guide
from . import binding_retry
from . import binding_feedback
from . import evidence_requests as requests
from . import deepinfra_requests as hosted
from .pastor_evidence import SourceWindow,EvidenceArtifactStore,digest

VERSION='source-attachment-three-window-v1'
LATEST='b3f5524a1bf7c216f8a2616f49d395ed0cee1b0008d4091c6e1e61725cf05a78'
LIMITATION='Three previously exposed windows; unequal profile counts, no profile comparison or ranking. Feasibility and correction/preservation review only, not blinded accuracy, family coverage or production admission.'


def frozen(path):
    packet=json.loads(Path(path).read_text());fp=packet['input_fingerprint']
    if digest({k:v for k,v in packet.items() if k!='input_fingerprint'})!=fp: raise ValueError('Frozen history changed: '+str(path))
    return packet


def directory(base_dir,fp):
    root=demo.build_paths(base_dir).evaluation/'source-attachment-trial'/fp
    if root.resolve().is_relative_to(Path(__file__).parents[2].resolve()): raise ValueError('Artifacts must be outside repository')
    return root


def select(source):
    if source['selection']['cases']!=fit.select_cases(source): raise ValueError('Six-window selection changed')
    selected=[]
    for family in ('theology','application','independent_control'):
        selected.append(next(case for case in source['selection']['cases'][1:] if case.endswith('-'+family)))
    return selected


def reader(window,old,contract):
    state=demo._source_state(SourceWindow(**window))
    expected=dict(texts=state['texts'],block_mapping=state['block_mapping'],
        source_identity={k:v for k,v in window.items() if k!='blocks'},target_scope='declared_blocks_only')
    original=requests.RequestSpec(**old)
    if json.loads(original.body['messages'][1]['content'])!=expected: raise ValueError('Complete source message differs')
    body=dict(model=hosted.FLASH_MODEL,messages=[dict(role='system',content=contract['reader_prompt']+
        '\nField/type/vocabulary guide (derived mechanically from the schema):\n'+'\n'.join(guide.field_guide(context.schema()))),
        deepcopy(original.body['messages'][1])],max_tokens=8192,temperature=0,top_p=1,stream=False,n=1,reasoning_effort='none',
        response_format=dict(type='json_schema',json_schema=dict(name='qualified_source_reading',strict=True,schema=context.schema())))
    spec=requests.RequestSpec('source_reading',body,deepcopy(original.source_identity),namespace=hosted.GUIDED_NAMESPACE,
        version=requests.DEEPINFRA_GUIDED_VERSION,runtime_identity=hosted.GUIDED_POLICY)
    context.validate_request(spec);spec.preflight();return spec


def build(source,account,contract):
    selected=select(source);windows={w['id']:w for w in source['windows']}
    producers={r['case_id']:r['request'] for r in source['source_requests']};cases=[]
    for key in selected:
        spec=reader(windows[key],producers[key],contract)
        cases.append(dict(case_id=key,window=deepcopy(windows[key]),request=asdict(spec),token_account=spec.preflight()))
    flash=4*len(cases);typesafe=2*len(cases)
    reserve=flash*hosted.reserved_usd(requests.DEEPINFRA_GUIDED_VERSION)+typesafe*requests.reservation('source_verification')
    if account['cumulative_paid_attempts']+flash+typesafe>66: raise ValueError('Cumulative 66 paid-attempt limit exceeded')
    if Decimal(account['cumulative_known_list_price_usage_usd'])+reserve>2 or reserve>Decimal('.20'):
        raise ValueError('Cumulative $2 or trial $0.20 reservation exceeded')
    return dict(schema_version=VERSION,cases=cases,schema=context.schema(),contract_fingerprint=contract['contract_fingerprint'],
        contract=contract,model=hosted.FLASH_MODEL,
        policy=dict(source_context_version=context.VERSION,binding_retries=1,guided_binding_retries=1,
            maximum_semantic_reviews_per_window=1,maximum_binding_retries_per_stage=1,verifier_fields=list(context.FIELDS),
            pass_at_least=.90,fail_at_most=.10,output_tokens_per_flash_request=8192,reasoning_effort='none',
            transport_retries=0,manual_repairs=0,runtime_approvals=0,reference_inputs=0,production_admission=False),
        selection=dict(cases=selected,policy='First remaining frozen case in each family; excludes the original development case; identical execution policy for every case.',
            families=['theology','application','independent_control'],
            profile_counts=dict(Counter(str(c['window']['profile_id']) for c in cases)),
            source_strata=dict(Counter(c['window']['stratum'] for c in cases)),
            family_coverage='Selection strata only; theological/pastoral family accuracy and coverage remain unmeasured.'),
        budget=dict(maximum_attempts=flash+typesafe,maximum_paid_attempts=flash+typesafe,flash_attempts=flash,typesafe_attempts=typesafe,
            reserved_usd=str(reserve),max_usd='0.20',cumulative_maximum_paid_attempts=account['cumulative_paid_attempts']+flash+typesafe,
            cumulative_paid_attempt_ceiling=66,cumulative_usd_ceiling='2',
            cumulative_reserved_plus_prior_list_usd=str(Decimal(account['cumulative_known_list_price_usage_usd'])+reserve)),
        history=dict(prior_attempts=account['cumulative_attempts'],prior_local_attempts=account['cumulative_local_attempts'],
            prior_paid_attempts=account['cumulative_paid_attempts'],prior_known_list_price_usage_usd=account['cumulative_known_list_price_usage_usd']),
        limitation=LIMITATION)


def prepare(base_dir=None,*,check_only=False):
    base=demo.build_paths(base_dir).root
    latest_path=base/'evaluation/condition-model-check'/LATEST/'input.json';latest=frozen(latest_path)
    root=latest_path.parent/'execution';result=json.loads((root/'results.json').read_text());account=result['accounting']
    if (result['input_fingerprint']!=LATEST or result['halt'] is not None or account['attempts']!=2
        or account['unknown_usage_attempts'] or account['cumulative_paid_attempts']!=47):
        raise ValueError('Requires the completed, accounted synthetic attachment check')
    accounts=[]
    for phase in ('initial','verification'):
        store=requests.ReceiptStore(root/phase);accounts.append(demo.usage_account(store))
        receipts=list((store.root/'receipts').glob('*.json'))
        if len(receipts)!=1: raise ValueError('Historical receipt inventory changed')
        receipt=json.loads(receipts[0].read_text());spec=requests.RequestSpec(**receipt['request'])
        expected=latest['request'] if phase=='initial' else json.loads((root/'verifier-request.json').read_text())
        if receipt['request']!=expected or receipt['halt'] or receipt['response_digest']!=digest(receipt['response']): raise ValueError('Historical receipt changed')
        requests.validate_response(spec,receipt['response'])
    for key in ('attempts','paid_attempts','local_attempts','unknown_usage_attempts','known_input_tokens','known_output_tokens'):
        if sum(a[key] for a in accounts)!=account[key]: raise ValueError('Historical attempt accounting changed')
    cost=sum((Decimal(a['known_list_price_usage_usd']) for a in accounts),Decimal(0))
    old=latest['history']['prior_accounting']
    if cost!=Decimal(account['known_list_price_usage_usd']) or Decimal(old['cumulative_known_list_price_usage_usd'])+cost!=Decimal(account['cumulative_known_list_price_usage_usd']):
        raise ValueError('Historical cost accounting changed')
    for key in ('attempts','local_attempts','paid_attempts'):
        if old['cumulative_'+key]+account[key]!=account['cumulative_'+key]: raise ValueError('Historical cumulative accounting changed')
    files={str(latest_path):demo.file_hash(latest_path)};cursor=latest_path;visited=set()
    while cursor not in visited:
        visited.add(cursor);ancestor=frozen(cursor);files[str(cursor)]=demo.file_hash(cursor)
        for name,sha in ancestor.get('history',{}).get('preserved_files',{}).items():
            if name in files and files[name]!=sha: raise ValueError('Conflicting history hashes')
            files[name]=sha
        previous=ancestor.get('history',{}).get('prior_input')
        if ancestor['input_fingerprint']==five.SIX or not previous: break
        cursor=Path(previous)
        if len(visited)>40: raise ValueError('Unexpected history lineage')
    for name,sha in files.items():
        if demo.file_hash(Path(name))!=sha: raise ValueError('Preserved history changed: '+name)
    source_path=fit.directory(base_dir,five.SIX)/'input.json';source=frozen(source_path);fit.verify_sources(source,base_dir)
    metadata=hosted.public_model_metadata(hosted.FLASH_MODEL)
    if metadata!=latest['published_model_metadata']: raise ValueError('Pinned Flash 1017 deployment or published prices changed')
    contract=context.contract_packet();packet=build(source,account,contract)
    packet['published_model_metadata']=metadata
    for path in [source_path,*sorted(p for p in root.rglob('*.json') if p.name!='attachment-trial-authorization.json')]: files[str(path)]=demo.file_hash(path)
    matches={case['case_id']:five.compatible_receipts(requests.RequestSpec(**case['request']),files) for case in packet['cases']}
    if any(matches.values()): raise ValueError('Compatible reader receipt found; resolve reuse before paying for a new reading')
    constituents={case['case_id']:[] for case in packet['cases']}
    for name in files:
        if '/receipts/' not in name: continue
        receipt=json.loads(Path(name).read_text());producer=receipt.get('request',{})
        if producer.get('phase')!='source_reading' or receipt.get('halt'): continue
        for case in packet['cases']:
            spec=requests.RequestSpec(**case['request'])
            old_body=producer.get('body',{});old_messages=old_body.get('messages',[])
            if old_body.get('model')==hosted.FLASH_MODEL and len(old_messages)>1 and old_messages[1]==spec.body['messages'][1]:
                constituents[case['case_id']].append(dict(receipt=name,role='Preserved baseline evidence; not a response to the clarified producer contract',
                    prompt_compatible=old_messages[0]==spec.body['messages'][0],schema_compatible=old_body.get('response_format')==spec.body['response_format']))
    packet['reuse_audit']=dict(compatible_reader_receipts=matches,same_model_source_constituents=constituents,
        source='Exact existing windows, source files, mappings, five-minute discovery and nominal-minute blocks; no collection.',
        observations='Compatible constituent evidence is retained for audit. New readings test the clarified producer rule; old readings are not re-labelled as new-contract outputs.',
        verification='Old probabilities remain historical. Four-field requests assess each newly generated binding; missing conditions verdicts cannot be filled from other field scores.',
        verification_bias='Previously reviewed sources; compare corrections AND preservation against full source. Scores are not accuracy counts.',
        human_effort='No runtime manual repairs, reference readings or routine approvals; post-run source-review effort must be reported, not treated as zero.')
    packet['history'].update(prior_input=str(latest_path),six_window_input=str(source_path),preserved_files=files)
    packet['code_identity']={**demo.code_identity(),**{m.__name__.rsplit('.',1)[-1]:demo.file_hash(Path(m.__file__))
        for m in (context,binding_retry,binding_feedback,five,fit,hosted,guide,context.fields,context.review,context.diagnostics)}}
    packet['code_identity']['attachment_trial']=demo.file_hash(Path(__file__))
    packet['input_fingerprint']=digest(packet);out=directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        context.export(base_dir);EvidenceArtifactStore(out).write_immutable('input.json',packet)
        (out/'preparation.md').write_text('# Three-window full-schema attachment trial\n\n'+LIMITATION+
            '\n\nPinned **'+hosted.FLASH_MODEL+'**, reasoning disabled, 8,192 output tokens. Initial reading with one binding retry; '
            'TypeSafe conditions/qualifications/polarity/context; one semantic correction with one binding retry; TypeSafe recheck. '
            'Mechanical feedback includes all literal matches and saved node roles without selecting a semantic repair. '
            'Schema/binding exhaustion is a component failure; transport, context-fit or unknown-spend stops end the batch. '
            'Uncertainty remains INCONCLUSIVE, even when all mechanical checks pass. No comparisons, rankings or production admission.\n\n'+
            '\n'.join('- '+c['case_id'] for c in packet['cases'])+
            '\n\nMaximum 18 paid attempts: 12 Flash and 6 TypeSafe; cumulative maximum 65/66. Full uncached reservation $'+packet['budget']['reserved_usd']+
            ', ceiling $0.20. Prior list-price usage plus reservation $'+packet['budget']['cumulative_reserved_plus_prior_list_usd']+' < $2. '
            'This is a bounded subset, not a replacement for the original frozen 24-window V3 experiment.\n\n```sh\n'+command(out,packet,base_dir)+'\n```\n')
    return packet,out


def command(out,packet,base_dir):
    return (f'pte analysis learning-demo model-fit attachment-run --base-dir {demo.build_paths(base_dir).root} '
        f'--input {out/"input.json"} --experimental --approve-input {packet["input_fingerprint"]} --max-usd 0.20 --confirm-prices --json')


def run(input_path,base_dir=None,*,experimental=False,approve_input=None,max_usd='0.20',confirm_prices=False,check_only=False,progress=None):
    path=Path(input_path);packet=frozen(path);fp=packet['input_fingerprint']
    if path.resolve()!=(directory(base_dir,fp)/'input.json').resolve(): raise ValueError('Frozen input location differs')
    expected,_=prepare(base_dir,check_only=True)
    if packet!=expected: raise ValueError('Source, model, contract, implementation or budget changed after freeze')
    try: cap=Decimal(max_usd)
    except InvalidOperation as error: raise ValueError('Invalid ceiling') from error
    if not cap.is_finite() or not Decimal(packet['budget']['reserved_usd'])<=cap<=Decimal('.20'): raise ValueError('Reserve full plan within $0.20')
    if check_only: return dict(status='PREPARED_NO_EXECUTION',model=packet['model'],budget=packet['budget'],selection=packet['selection'],generation_calls=0,paid_calls=0)
    if not experimental or approve_input!=fp or not confirm_prices: raise ValueError('Use exact frozen approval, --experimental and --confirm-prices')
    root=path.parent/'execution'
    if not (root/'results.json').exists() and (not hosted.credential_present() or not os.environ.get('TYPESAFE_API_KEY','').strip()):
        raise ValueError('Both API keys required; no attempts started')
    marker=Path(packet['history']['prior_input']).parent/'execution'
    EvidenceArtifactStore(marker).write_immutable('attachment-trial-authorization.json',dict(input_fingerprint=fp))
    EvidenceArtifactStore(root).write_immutable('authorization.json',dict(input_fingerprint=fp,max_usd=str(cap)))
    result=five.run_recipe(packet,root,hosted.transport,requests.typesafe_transport,progress=progress)
    return result|dict(model=packet['model'],results=str(root/'results.json'),review_packet=str(root/'source-review-packet.json'))
