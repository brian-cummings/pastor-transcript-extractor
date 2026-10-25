"""Six frozen source requests through the shared executor; no paid/downstream calls."""
from dataclasses import asdict, replace
import json
from pathlib import Path
from httpx import HTTPError

from . import learning_demo as demo
from . import learning_demo_contracts as contract
from .config import build_paths
from .evidence_requests import BudgetLedger, ReceiptStore, RequestSpec, execute, ollama_transport, ollama_runtime_identity
from .pastor_evidence import EvidenceArtifactStore, SourceWindow, compile_machine_binding, digest

VERSION='learning-demo-source-model-fit-v1'
PRIOR='eddf82b9c3cf402757f12097e8bb4d84ecf6cd98969a6250ca7243a079894f04'
NAMESPACE='learning-demo-source-model-fit-v1'
SLOTS=('theology','application','independent_control')


def directory(base_dir,fingerprint):
    root=build_paths(base_dir).evaluation/'learning-demo-model-fit'
    if root.resolve().is_relative_to(Path(__file__).parents[2].resolve()):
        raise ValueError('Generated artifacts must be outside repository')
    return root/fingerprint


def code_identity():
    return {**demo.code_identity(),'learning_demo_model_fit':demo.file_hash(Path(__file__))}


def history(prior_input,base_dir):
    prior_input=Path(prior_input).resolve()
    if prior_input!=(demo._run_directory(base_dir,PRIOR)/'input.json').resolve():
        raise ValueError('Source model-fit trial must follow the preserved corrected-contract Gemma run')
    prior=json.loads(prior_input.read_text())
    if prior['input_fingerprint']!=PRIOR or digest({k:v for k,v in prior.items() if k!='input_fingerprint'})!=PRIOR:
        raise ValueError('Prior input identity changed')
    lineage=prior['contract_round']
    for path,sha in lineage['preserved_files'].items():
        if demo.file_hash(Path(path))!=sha: raise ValueError('Historical evidence changed')
    store=ReceiptStore(prior_input.parent/'execution')
    attempts=store.attempts()
    if len(attempts)!=13 or any(a['phase']!='source_reading' or a['reserved_usd']!='0' for a in attempts):
        raise ValueError('Expected the preserved thirteen-local-attempt run with no paid calls')
    stops=[json.loads(p.read_text()) for p in store.root.glob('stopped-*.json')]
    if len(stops)!=1 or stops[0]['reason']!="Incomplete Ollama response (done=True, done_reason='length'); no repair/retry":
        raise ValueError('Prior run is not the reviewed output-limit failure')
    files=[prior_input,*sorted(p for p in store.root.rglob('*.json') if p.name!='model-fit-authorization.json')]
    return prior,dict(prior_input=str(prior_input),prior_attempts=15,prior_local_attempts=15,
        prior_paid_attempts=0,prior_reserved_usd='0',
        preserved_files={**lineage['preserved_files'],**{str(p):demo.file_hash(p) for p in files}})


def select_cases(prior):
    # Interleave the profiles. Selection is fixed before inspecting model results.
    selected=[]
    available={w['id']:w for w in prior['windows']}
    for index,slot in enumerate(SLOTS):
        for profile,videos in demo.SCOPE.items():
            case=f'P{profile}-R{videos[index]}-{slot}'
            window=available[case]
            if window['profile_id']!=profile or window['video_id']!=videos[index]:
                raise ValueError('Frozen case coordinates differ')
            selected.append(case)
    return selected


def verify_sources(packet,base_dir):
    if demo.file_hash(Path(packet['proposal']['path']))!=packet['proposal']['sha256']:
        raise ValueError('Proposal changed')
    for row in packet['source_refs']:
        if demo.file_hash(Path(row['path']))!=row['sha256']: raise ValueError('Frozen source changed')
    from .profile_evidence_supply import read_sample
    for raw in packet['samples']:
        sample=demo.SampleSpec(**{**raw,'video_ids':tuple(raw['video_ids']),'input_run_ids':tuple(raw['input_run_ids'])})
        inventory,_,_=read_sample(sample,base_dir)
        if tuple(row['run_id'] for row in inventory['sermons'])!=sample.input_run_ids:
            raise ValueError('Frozen membership or source run lineage changed')


def prepare(prior_input,base_dir=None,*,model='qwen3.5:9b',check_only=False):
    prior,lineage=history(prior_input,base_dir)
    if prior['contracts']!=dict(version=contract.VERSION,schemas=contract.SCHEMAS,
                               prompts=contract.PROMPTS,required_checks=contract.CHECK_MEANINGS):
        raise ValueError('Model-fit trial requires the unchanged corrected reading contract')
    current=code_identity()
    for name in ('pastor_evidence','theological_binding','binding_evidence'):
        if prior['code_identity'][name]!=current[name]: raise ValueError('Literal binding semantics changed')
    verify_sources(prior,base_dir)
    runtime=ollama_runtime_identity(model=model)
    if runtime['model']!='qwen3.5:9b': raise ValueError('This authorized trial selects installed qwen3.5:9b')
    cases=select_cases(prior);requests=[]
    old={row['case_id']:row for row in prior['source_requests']}
    for case in cases:
        original=RequestSpec(**old[case]['request'])
        state=json.loads(original.body['messages'][1]['content'])
        request=replace(contract.generation_request('source_reading',state,original.source_identity,
            runtime_identity=runtime),namespace=NAMESPACE)
        if request.body['messages']!=original.body['messages'] or request.body['format']!=original.body['format']:
            raise ValueError('Model comparison changed source state, prompt or schema')
        requests.append(dict(case_id=case,request=asdict(request),fingerprint=request.fingerprint,
                             token_account=request.preflight()))
    baseline=demo.source_contract_diagnostics(prior,ReceiptStore(Path(prior_input).parent/'execution'))
    baseline={row['window_id']:row for row in baseline['windows'] if row['window_id'] in cases}
    packet=dict(schema_version=VERSION,code_identity=current,history=lineage,generation_runtime=runtime,
        contracts=prior['contracts'],proposal=prior['proposal'],source_refs=prior['source_refs'],samples=prior['samples'],
        windows=[next(w for w in prior['windows'] if w['id']==case) for case in cases],source_requests=requests,
        selection=dict(policy='interleaved profiles; theology/application/control across each profile recording order',
                       cases=cases,profiles=[318,130],recordings=6,windows=6,independent_controls=2),
        baseline=baseline,baseline_policy='Saved machine outputs for offline comparison only; never sent to Qwen',
        budget=dict(maximum_attempts=6,maximum_paid_attempts=0,max_usd='0',prior_attempts=15,
                    cumulative_maximum_attempts=21,output_cap=8192,retries=0,fallbacks=0),
        acceptance=dict(contract_fit='All six complete, schema-consistent, nonempty, all proposed claims literal-bound',
            semantic_outcome='Always INCONCLUSIVE without independent semantic/reference verification',
            scope='Source-reading feasibility only; not family completeness, comparisons, ranking or admission'),
        execution_authorized=False,authorization='Brian authorized preparation of one bounded Qwen source-reading trial')
    packet['input_fingerprint']=digest(packet)
    out=directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        base=build_paths(base_dir).root
        command=f'pte analysis learning-demo model-fit run --base-dir {base} --input {out / "input.json"} --experimental --approve-input {packet["input_fingerprint"]} --max-usd 0 --json'
        (out/'preparation.md').write_text('# Bounded Qwen source-reading model-fit preparation\n\nSix local requests, one per recording; three per profile, including one frozen control per profile. Same corrected source contract, 8192-token output cap, thinking disabled. No paid verification or downstream comparisons. Prior 15 local attempts remain counted; cumulative maximum 21.\n\nCases:\n\n'+ '\n'.join('- '+case for case in cases)+'\n\nBrian executes:\n\n```sh\n'+command+'\n```\n\nContract-fit PASS is a technical component only. Semantic accuracy remains INCONCLUSIVE. No automatic retry or advancement to the full workflow.\n')
    return packet,out


def verify(input_path,base_dir):
    packet=json.loads(Path(input_path).read_text())
    if packet['schema_version']!=VERSION or digest({k:v for k,v in packet.items() if k!='input_fingerprint'})!=packet['input_fingerprint']:
        raise ValueError('Model-fit input identity differs')
    if Path(input_path).resolve()!=(directory(base_dir,packet['input_fingerprint'])/'input.json').resolve():
        raise ValueError('Model-fit input must be in the configured application directory')
    if packet['code_identity']!=code_identity(): raise ValueError('Implementation changed after freeze')
    # Reconstruct the exact provider-free recipe, including all historical/source hashes.
    if 'runtime_repeat' in packet:
        from .learning_demo_runtime_repeat import prepare as repeat_prepare
        expected,_=repeat_prepare(packet['runtime_repeat']['prior_input'],base_dir,model=packet['generation_runtime']['model'],check_only=True)
    else:
        expected,_=prepare(packet['history']['prior_input'],base_dir,model=packet['generation_runtime']['model'],check_only=True)
    if expected!=packet: raise ValueError('Model-fit frozen sources, requests, model or limits differ')
    marker=authorization_marker(packet)
    if marker.exists() and json.loads(marker.read_text())!={'input_fingerprint':packet['input_fingerprint']}:
        raise ValueError('Approved model-fit trial already assigned to another input')
    return packet


def authorization_marker(packet):
    if 'runtime_repeat' in packet:
        return Path(packet['runtime_repeat']['prior_input']).parent/'execution/runtime-repeat-authorization.json'
    return Path(packet['history']['prior_input']).parent/'execution/model-fit-authorization.json'


def run_recipe(packet,store,transport,progress=None):
    cached=store.root/'results.json'
    if cached.exists():
        result=json.loads(cached.read_text())
        if result['input_fingerprint']!=packet['input_fingerprint']: raise ValueError('Foreign model-fit results')
        return result
    ledger=BudgetLedger(max_attempts=6,max_usd='0',source_max_usd='0',downstream_max_usd='0')
    windows={w['id']:SourceWindow(**{**w,'blocks':tuple(w['blocks']),
        'excluded_neighbors':tuple(w['excluded_neighbors'])}) for w in packet['windows']}
    observations=[];readings=[];failures=[];halt=None
    for index,row in enumerate(packet['source_requests'],1):
        request=RequestSpec(**row['request'])
        if request.phase!='source_reading' or request.namespace!=NAMESPACE:
            raise ValueError('Model-fit execution permits only its six namespaced source requests')
        if progress: progress(f'Source window {index}/6: {row["case_id"]}; {request.body["model"]}')
        try: response=execute(request,ledger,store,transport)
        except (ValueError,OSError,KeyError,TypeError,HTTPError) as error:
            halt=str(error);break
        try:
            reading=contract.generated_output('source_reading',response)
            readings.append(dict(window_id=row['case_id'],output=reading))
            if (reading['status']=='none' and reading['claims']) or (reading['status']=='proposed' and not reading['claims']):
                raise ValueError('Inconsistent reading status')
            claim_ids=set();bound=0
            for claim in reading['claims']:
                try:
                    if claim['binding_id'] in claim_ids: raise ValueError('Duplicate claim identity')
                    claim_ids.add(claim['binding_id'])
                    envelope=compile_machine_binding(windows[row['case_id']],claim,model=request.body['model'],
                        prompt_digest=digest(dict(system=request.body['messages'][0]['content'],schema=request.body['format'])),
                        raw_response_ref='receipts/'+request.fingerprint+'.json',locate_quotes=True)
                    observations.append(envelope);bound+=1
                except (ValueError,KeyError,TypeError) as error:
                    failures.append(dict(component='literal_binding',window_id=row['case_id'],binding_id=claim.get('binding_id'),reason=str(error)))
            if progress: progress(f'Source window {index}: {len(reading["claims"])} proposed, {bound} literal-bound; no verification call')
        except (ValueError,KeyError,TypeError) as error:
            failures.append(dict(component='reading_schema',window_id=row['case_id'],reason=str(error)))
    diagnostics=demo.source_contract_diagnostics(packet,store)
    nonempty=all(row['literal_bound_claims']>0 for row in diagnostics['windows'])
    fit='FAIL(component)' if halt or failures else ('PASS' if len(readings)==6 and nonempty else 'INCONCLUSIVE')
    account=demo.usage_account(store)
    prior=packet.get('budget',{}).get('prior_attempts',15)
    account.update(prior_attempts=prior,cumulative_attempts=prior+account['attempts'],
                   cumulative_local_attempts=prior+account['local_attempts'],cumulative_paid_attempts=account['paid_attempts'])
    if 'runtime_repeat' in packet:
        account.update(prior_source_attempts=21,prior_synthetic_attempts=4)
    comparison=[dict(window_id=row['case_id'],baseline=packet['baseline'].get(row['case_id'],dict(status='UNATTEMPTED')),
        selected=next((r for r in diagnostics['windows'] if r['window_id']==row['case_id']),dict(status='UNATTEMPTED')))
        for row in packet['source_requests']]
    result=dict(schema_version=VERSION,input_fingerprint=packet['input_fingerprint'],
        status='FAIL(component)' if fit=='FAIL(component)' else 'INCONCLUSIVE',contract_fit=fit,
        semantic_outcome='INCONCLUSIVE: no independent semantic/reference verification',halt=halt,
        accounting=account,diagnostics=diagnostics,baseline_comparison=comparison,
        raw_readings=readings,observations=observations,failures=failures,
        saturation_windows=[r['window_id'] for r in diagnostics['windows'] if r.get('status')=='saturated'],
        production_admission=False,next_step='Review saved contract-fit and source evidence; no automatic retries or full-workflow advancement')
    if 'runtime_repeat' in packet:
        result['runtime_comparison']=dict(server_version=packet['generation_runtime']['server_version'],
            prior_input=packet['runtime_repeat']['prior_input'],
            prior_diagnostics=packet['runtime_repeat']['prior_diagnostics'],selected_diagnostics=diagnostics)
    store.write_immutable('results.json',result)
    return result


def run(input_path,base_dir=None,*,approve_input=None,experimental=False,max_usd='0',check_only=False,progress=None):
    if progress: progress('Validating frozen six-window model-fit input and installed model')
    packet=verify(input_path,base_dir)
    if check_only: return dict(status='PREPARED_NO_EXECUTION',input_fingerprint=packet['input_fingerprint'],budget=packet['budget'],model_calls=0)
    if approve_input!=packet['input_fingerprint'] or not experimental or str(max_usd)!='0':
        raise ValueError('Use --experimental --approve-input exact fingerprint --max-usd 0')
    marker=authorization_marker(packet)
    EvidenceArtifactStore(marker.parent).write_immutable(marker.name,dict(input_fingerprint=packet['input_fingerprint']))
    store=ReceiptStore(Path(input_path).parent/'execution')
    store.write_immutable('authorization.json',dict(input_fingerprint=approve_input,maximum_attempts=6,
        paid_attempts=0,max_usd='0',model=packet['generation_runtime']['model'],production_admission=False))
    def transport(request):
        if 'runtime_repeat' in packet:
            from .ollama_conformance import server_version
            if server_version(request.runtime_identity['base_url'])!=request.runtime_identity['server_version']:
                raise ValueError('Ollama server changed after freeze; no retry/substitution')
        return ollama_transport(request)
    result=run_recipe(packet,store,transport,progress)
    return dict(status=result['status'],contract_fit=result['contract_fit'],input_fingerprint=packet['input_fingerprint'],
        model=packet['generation_runtime']['model'],accounting=result['accounting'],halt=result['halt'],
        completed_windows=result['diagnostics']['complete_responses'],
        schema_valid_windows=result['diagnostics']['schema_valid_responses'],
        proposed_claims=result['diagnostics']['proposed_claims'],literal_bound_claims=result['diagnostics']['literal_bound_claims'],
        production_admission=False,results=str(store.root/'results.json'),next_step=result['next_step'])


def report(run_dir,base_dir=None):
    run_dir=Path(run_dir);packet=json.loads((run_dir/'input.json').read_text())
    if run_dir.resolve()!=directory(base_dir,packet['input_fingerprint']).resolve():
        raise ValueError('Model-fit report must be under configured application base')
    path=run_dir/'execution/results.json'
    if not path.exists():
        store=ReceiptStore(run_dir/'execution')
        if store.attempts():
            return dict(status='INCONCLUSIVE',reason='Execution incomplete or active; snapshot only',
                        accounting=demo.usage_account(store),budget=packet['budget'])
        return dict(status='PREPARED_NO_EXECUTION',budget=packet['budget'],model_calls=0)
    result=json.loads(path.read_text())
    return demo._write_report(run_dir,result)
