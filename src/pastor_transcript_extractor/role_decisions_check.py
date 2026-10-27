"""One bounded direct semantic check using literal role packages and saved choices."""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
from httpx import HTTPError
from . import passage_voice_context as context
from . import voice_adoption_check as choices

requests=context.requests
demo=context.demo
digest=context.digest
Store=context.Store
VERSION='role-decisions-check-v1'
PRIOR='e8182c6e7ac6863c3eea770e77f3f2cdd27b6b89719d80201d3eb04776e18a39'
BASELINE='dae1edb234c41c527658f5873b332a85853849f784fda5425493a8738d8da1be'
LIMITATION='Six exposed candidates, unchanged direct Choice meanings and diagnostic gates. Seven compatible resolved full-source choices are reused; only eleven unresolved fields are requested with new literal evidence packages. Changed presentation is not an isolated ablation or independent accuracy/calibration benchmark. No selected evidence sufficiency, speaker name, adoption basis, warrant or production admission is established by a label.'


def make_request(packet,checked,baseline,baseline_spec):
    sources={sid:''.join(u['text'] for u in src['units']) for sid,src in packet['state']['sources'].items()}
    packages={r['item_id']:r['package'] for r in checked['evidence']}
    identities={r['item_id']:r for r in packet['candidate_index']}
    items=[];index={};questions={};reused=[]
    for n,item in enumerate(packet['state']['items']):
        identity=identities[item['item_id']];package=packages[item['item_id']]
        items.append(dict(source_id=item['source_id'],proposition=dict(reading=item['candidate_reading'],span=deepcopy(package['proposition']['span']),binding_evidence=deepcopy(package['binding_evidence']))))
        for field in choices.CRITERIA:
            matches=[r for r in baseline if r['origin']=='saved_claim' and r['case_id']==identity['case_id'] and r['binding_id']==identity['binding_id'] and r['field']==field]
            if len(matches)!=1: raise ValueError('Baseline candidate inventory differs')
            old=matches[0];old_item=baseline_spec.body['state']['items'][old['item_index']]
            if old_item['proposition']['reading']!=item['candidate_reading'] or baseline_spec.body['state']['sources'][old_item['source_id']]!=sources[item['source_id']]: raise ValueError('Candidate/source incompatible with direct choice reuse')
            if old['diagnostically_resolved']:
                reused.append(dict(item_id=item['item_id'],baseline_question_id=old['question_id'],decision=deepcopy(old),evidence_sufficiency='Not established by full-source label reuse'))
                continue
            key=f'q{n}_{field}'
            index[key]=dict(origin='saved_claim',case_id=identity['case_id'],binding_id=identity['binding_id'],previous=None,expected=None,field=field,item_index=n)
            questions[key]=dict(type='choice',criteria=deepcopy(choices.CRITERIA[field]),instructions=f'Read `items[{n}].proposition` and its complete source in `sources.{item["source_id"]}`. '+choices.INSTRUCTIONS[field]+' '+choices.COMMON)
    spec=requests.RequestSpec('source_verification',dict(model='jev-1.13.0',state=dict(sources=sources,items=items,evidence_policy='Binding evidence contains literal model-proposed role spans, not validated labels. The proposition reading defines the point; a span may contain additional clauses or voices. Judge each field against the complete source; do not infer adoption from a voice citation. Labels do not certify selected-evidence sufficiency.'),questions=questions),dict(state_digest=digest(packet['state']),evidence_digest=digest(checked['evidence'])),namespace=VERSION,version=VERSION)
    spec.preflight()
    return spec,index,reused


def directory(base_dir,fp):
    root=demo.build_paths(base_dir).evaluation/'role-decisions-check'/fp
    if root.resolve().is_relative_to(Path(__file__).parents[2].resolve()): raise ValueError('Artifacts must be outside repository')
    return root


def receipt(root,phase,spec):
    path=root/phase/'receipts'/f'{spec.fingerprint}.json';raw=json.loads(path.read_text())
    if raw['request']!=asdict(spec) or raw['halt'] or raw['response_digest']!=digest(raw['response']): raise ValueError('Receipt integrity differs')
    requests.validate_response(spec,raw['response']);return path,raw


def prepare(base_dir=None,*,check_only=False):
    packet,_=context.prepare(base_dir,check_only=True)
    path=context.directory(base_dir,PRIOR)/'input.json';frozen=context.c.prior.previous.trial.frozen(path)
    if packet!=frozen: raise ValueError('Context lineage differs')
    root=path.parent/'execution';result=json.loads((root/'results.json').read_text());checked=json.loads((root/'evidence-role-validation.json').read_text())
    if result['halt'] or result['mechanical_fit']!='PASS' or checked['errors'] or result['accounting']['unknown_usage_attempts']: raise ValueError('Requires completed context run with known accounting')
    files=dict(packet['history']['preserved_files']);refs=[path,root/'results.json',root/'evidence-role-validation.json',root/'verifier-request.json']
    for phase,spec in [('selection',requests.RequestSpec(**packet['request'])),('verification',context.verification(packet,checked))]:
        ref,raw=receipt(root,phase,spec);refs.append(ref)
        if phase=='selection' and context.inspect(raw['response']['output'],packet)!=checked: raise ValueError('Context proposal differs')
        if phase=='verification' and any(raw['response']['output'][r['item_id']+':'+r['field']]['noul']!=r['probability_correct'] for r in result['context_scores']): raise ValueError('Context scores differ')
    baseline_path=choices.directory(base_dir,BASELINE)/'input.json';old=context.c.prior.previous.trial.frozen(baseline_path);old_root=baseline_path.parent/'execution';old_result=json.loads((old_root/'results.json').read_text());old_spec=requests.RequestSpec(**old['request'])
    ref,raw=receipt(old_root,'',old_spec);refs.extend([baseline_path,old_root/'results.json',ref])
    baseline=choices.decisions(raw['response'],old_spec,old['audit_index'])
    if old_result['halt'] or old_result['decisions']!=baseline: raise ValueError('Baseline direct choices differ')
    spec,index,reused=make_request(packet,checked,baseline,old_spec)
    if len(index)!=11 or len(reused)!=7: raise ValueError('Expected eleven unresolved and seven reusable decisions')
    for name,sha in files.items():
        if demo.file_hash(Path(name))!=sha: raise ValueError('Historical evidence changed')
    files.update({str(p):demo.file_hash(p) for p in refs})
    accounts=[demo.usage_account(requests.ReceiptStore(root/phase)) for phase in ('selection','verification')]
    for key in ('attempts','paid_attempts','local_attempts','known_input_tokens','known_output_tokens','unknown_usage_attempts'):
        if sum(a[key] for a in accounts)!=result['accounting'][key]: raise ValueError('Context accounting differs')
    if sum((Decimal(a['known_list_price_usage_usd']) for a in accounts),Decimal(0))!=Decimal(result['accounting']['known_list_price_usage_usd']): raise ValueError('Context cost differs')
    out=dict(version=VERSION,request=asdict(spec),audit_index=index,reused_decisions=reused,baseline_receipt=str(ref),token_account=spec.preflight(),coverage=packet['coverage'],
        policy=dict(maximum_attempts=1,retries=0,automatic_advancement=False,production_admission=False,diagnostic_minimum_selected_probability=.90,diagnostic_minimum_confidence=.90,cumulative_counts_reporting_only=True),
        budget=dict(max_usd='.003',reserved_usd=str(requests.reservation('source_verification')),maximum_paid_attempts=1),history=dict(prior_input=str(path),prior_accounting=result['accounting'],preserved_files=files),
        code_identity={m.__name__:demo.file_hash(Path(m.__file__)) for m in (choices,context,requests)},adapter_sha256=demo.file_hash(Path(__file__)),limitation=LIMITATION)
    out['input_fingerprint']=digest(out);dest=directory(base_dir,out['input_fingerprint'])
    if not check_only:
        Store(dest).write_immutable('input.json',out)
        (dest/'preparation.md').write_text('# Direct decisions with explicit evidence roles\n\n'+LIMITATION+'\n\nOne Jev 1.13.0 call, no retries or Flash calls; maximum $0.003. Same full sources, candidate readings and semantic Choice definitions; prior labels, scores, rationales and expected answers withheld. New role spans are machine proposals. Seven resolved decisions are retained with baseline receipt provenance; they do not verify new selected evidence. Eleven uncertain decisions are tested. Stop after source review; do not infer missing speaker names, adoption bases or warrants.\n')
    return out,dest


def run_recipe(packet,root,transport):
    root=Path(root);store=requests.ReceiptStore(root)
    if (root/'results.json').exists():
        saved=json.loads((root/'results.json').read_text())
        if saved['input_fingerprint']!=packet['input_fingerprint']: raise ValueError('Foreign result')
        return saved
    halt=None;rows=[]
    try:
        spec=requests.RequestSpec(**packet['request'])
        response=requests.execute(spec,requests.BudgetLedger(max_attempts=1,max_usd='.003'),store,transport)
        rows=choices.decisions(response,spec,packet['audit_index'])
    except (ValueError,OSError,KeyError,TypeError,HTTPError) as error: halt=str(error)
    account=demo.usage_account(store);old=packet['history']['prior_accounting']
    for key in ('attempts','local_attempts','paid_attempts'): account['cumulative_'+key]=old['cumulative_'+key]+account[key]
    account['cumulative_known_list_price_usage_usd']=str(Decimal(old['cumulative_known_list_price_usage_usd'])+Decimal(account['known_list_price_usage_usd']))
    result=dict(input_fingerprint=packet['input_fingerprint'],status='FAIL(component)' if halt else 'INCONCLUSIVE',halt=halt,decisions=rows,reused_decisions=packet['reused_decisions'],
        newly_resolved=sum(r['diagnostically_resolved'] for r in rows),still_unresolved=sum(not r['diagnostically_resolved'] for r in rows),accounting=account,coverage=packet['coverage'],production_admission=False,
        human_effort=dict(runtime_repairs=0,manual_reference_inputs=0,source_review='Required; time unmeasured'),limitation=LIMITATION,next_step='Review actual labels and preservation of uncertainty against full source; stop without retry or automatic advancement.')
    store.write_immutable('results.json',result);demo._write_report(root.parent,result);return result


def run(input_path,base_dir=None,*,experimental=False,approve_input=None,max_usd='.003',confirm_prices=False,check_only=False):
    path=Path(input_path);packet=context.c.prior.previous.trial.frozen(path);fp=packet['input_fingerprint']
    if path.resolve()!=(directory(base_dir,fp)/'input.json').resolve(): raise ValueError('Frozen location differs')
    expected,_=prepare(base_dir,check_only=True)
    if expected!=packet: raise ValueError('Frozen source, labels, model, code or budget changed')
    try: cap=Decimal(max_usd)
    except InvalidOperation as error: raise ValueError('Invalid ceiling') from error
    if not cap.is_finite() or not Decimal(packet['budget']['reserved_usd'])<=cap<=Decimal('.003'): raise ValueError('Reserve one request within $0.003')
    if check_only: return dict(status='PREPARED_NO_EXECUTION',budget=packet['budget'],paid_calls=0,generation_calls=0)
    if not experimental or approve_input!=fp or not confirm_prices: raise ValueError('Use exact frozen approval, --experimental and --confirm-prices')
    root=path.parent/'execution'
    if not (root/'results.json').exists() and not os.environ.get('TYPESAFE_API_KEY','').strip(): raise ValueError('TYPESAFE_API_KEY required; no attempts started')
    Store(root).write_immutable('authorization.json',dict(input_fingerprint=fp,max_usd=str(cap)))
    return run_recipe(packet,root,requests.typesafe_transport)|dict(results=str(root/'results.json'))
