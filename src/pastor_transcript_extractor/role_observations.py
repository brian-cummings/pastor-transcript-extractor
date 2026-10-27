"""Offline materialization of receipt-backed partial observations; no inference."""
from decimal import Decimal
import json
from pathlib import Path
from . import role_decisions_check as check
from . import pastor_evidence as evidence

VERSION='role-observations-v1'
SAVED='2923c954833fbb5987af6c82f8df10a3d7dec23d040d851fab90f6ebb6098e39'


def decision_provenance(spec,raw,path,question_id):
    return dict(model=spec.body['model'],prompt_digest=evidence.digest(spec.body),
        raw_response_ref=str(path),request_fingerprint=spec.fingerprint,
        response_digest=raw['response_digest'],question_id=question_id)


def load_inputs(base_dir,input_path=None):
    path=Path(input_path) if input_path is not None else check.directory(base_dir,SAVED)/'input.json'
    packet=check.context.c.prior.previous.trial.frozen(path)
    if path.resolve()!=(check.directory(base_dir,packet['input_fingerprint'])/'input.json').resolve():
        raise ValueError('Decision input location differs from configured base')
    expected,_=check.prepare(base_dir,check_only=True)
    if packet!=expected: raise ValueError('Saved decision source or contract changed')
    root=path.parent/'execution';result_path=root/'results.json';result=json.loads(result_path.read_text())
    if result['input_fingerprint']!=packet['input_fingerprint'] or result['halt'] or result['accounting']['unknown_usage_attempts']:
        raise ValueError('Requires completed accounted decision run')
    spec=check.requests.RequestSpec(**packet['request']);new_path,new_raw=check.receipt(root,'',spec)
    if check.choices.decisions(new_raw['response'],spec,packet['audit_index'])!=result['decisions'] or result['reused_decisions']!=packet['reused_decisions']:
        raise ValueError('Saved decisions differ from receipts or reuse manifest')
    account=check.demo.usage_account(check.requests.ReceiptStore(root))
    if any(result['accounting'][key]!=value for key,value in account.items()): raise ValueError('Decision accounting differs')
    old_account=packet['history']['prior_accounting']
    for key in ('attempts','local_attempts','paid_attempts'):
        if old_account['cumulative_'+key]+account[key]!=result['accounting']['cumulative_'+key]: raise ValueError('Cumulative accounting differs')
    if Decimal(old_account['cumulative_known_list_price_usage_usd'])+Decimal(account['known_list_price_usage_usd'])!=Decimal(result['accounting']['cumulative_known_list_price_usage_usd']): raise ValueError('Cumulative cost differs')
    baseline_path=Path(packet['baseline_receipt']);baseline_raw=json.loads(baseline_path.read_text());baseline_spec=check.requests.RequestSpec(**baseline_raw['request'])
    # prepare() already validates this baseline receipt and exact reuse compatibility.
    context_path=Path(packet['history']['prior_input']);context_packet=check.context.c.prior.previous.trial.frozen(context_path)
    context_root=context_path.parent/'execution';checked_path=context_root/'evidence-role-validation.json';checked=json.loads(checked_path.read_text())
    source_spec=check.requests.RequestSpec(**context_packet['request']);source_path,source_raw=check.receipt(context_root,'selection',source_spec)
    if check.context.inspect(source_raw['response']['output'],context_packet)!=checked or checked['errors']: raise ValueError('Saved role evidence changed')
    files=dict(packet['history']['preserved_files'])
    files.update({str(p):check.demo.file_hash(p) for p in (path,result_path,new_path,baseline_path,context_path,checked_path,source_path)})
    return dict(packet=packet,context_packet=context_packet,checked=checked,result=result,
        new_receipt=(spec,new_raw,new_path),baseline_receipt=(baseline_spec,baseline_raw,baseline_path),
        evidence_receipt=(source_spec,source_raw,source_path),preserved_files=files)


def integrate(inputs):
    packet=inputs['packet'];context=inputs['context_packet'];checked=inputs['checked'];result=inputs['result']
    records={item['item_id']:{} for item in context['state']['items']}
    for row in result['decisions']:
        key=row['question_id'];index=packet['audit_index'][key];item=context['state']['items'][index['item_index']]
        fields=records[item['item_id']]
        if index['field'] in fields: raise ValueError('Duplicate new field decision')
        fields[index['field']]=(row,inputs['new_receipt'])
    for reused in result['reused_decisions']:
        row=reused['decision'];fields=records[reused['item_id']]
        if row['field'] in fields: raise ValueError('Duplicate new/reused field decision')
        fields[row['field']]=(row,inputs['baseline_receipt'])
    packages={r['item_id']:r['package'] for r in checked['evidence']}
    if len(packages)!=len(checked['evidence']) or set(packages)!=set(records): raise ValueError('Evidence item inventory differs')
    observations=[]
    for item in context['state']['items']:
        iid=item['item_id'];decisions={}
        if set(records[iid])!=set(evidence.ROLE_OPTIONS): raise ValueError('Partial field decision inventory differs')
        for field,(row,(spec,raw,path)) in records[iid].items():
            answer=raw['response']['output'][row['question_id']]
            if any(row[key]!=answer[key] for key in ('type','choice','probabilities','confidence')): raise ValueError('Field decision differs from raw answer')
            decisions[field]=dict(answer,**decision_provenance(spec,raw,path,row['question_id']))
        package=packages[iid];window=evidence.SourceWindow(**context['windows'][item['source_id']])
        if package['proposition']['span']!=package['binding_evidence']['proposition']['span']: raise ValueError('Role package proposition differs')
        spec,raw,path=inputs['evidence_receipt']
        proof=decision_provenance(spec,raw,path,iid)
        observations.append(evidence.compile_partial_observation(window,
            dict(reading=item['candidate_reading'],span=package['proposition']['span']),
            package['binding_evidence'],decisions,evidence_provenance=proof))
    return observations


def report(observations):
    accepted,excluded=evidence.EvidenceView(tuple(observations)).partition()
    if accepted: raise ValueError('Partial observations unexpectedly eligible')
    known={field:sum(r['partial_binding']['masks'][field] for r in observations) for field in evidence.ROLE_OPTIONS}
    return dict(status='PASS',integration_status='PASS',semantic_outcome='INCONCLUSIVE: partial fields; broader semantic accuracy and complete bindings remain unvalidated',
        observations=len(observations),known_fields=known,unknown_fields={field:len(observations)-count for field,count in known.items()},
        eligible_complete_observations=len(accepted),excluded=excluded,production_admission=False,
        generation_calls=0,paid_calls=0,gap=dict(
            blocked_statement='This point contributes a qualified adopted actual affirmed/denied position.',
            inspected_reuse_paths=['Original literal role packages', 'Baseline compatible direct Choice receipt', 'New direct Choice receipt', 'Shared complete-binding compiler requirements and evidence policy'],
            reuse_outcome='Nine diagnostic field values retained with their original receipt provenance; nine field values remain masked. These receipts do not validate complete bindings or selected-evidence sufficiency.',
            missing_information='Validated speaker identity, adoption basis and remaining required semantic fields, plus compatible qualified alignment; availability elsewhere is not ruled out.',
            responsible_insertion_point='Existing shared upstream qualified-observation producer; profile assembly consumes verified observations.',
            smallest_next_change='Reuse compatible previously validated constituent fields at that producer before proposing any new inference; retain unsupported fields as unknown.',
            acceptance='A complete binding must satisfy the existing compiler, every required evidence check and qualified alignment without filling gaps from role labels.',
            authorization_boundary='Offline materialization only. No model calls, experiment expansion, actual pastor fingerprints/comparisons or production admission.'),limitations=['Diagnostic gates do not establish calibrated accuracy or evidence sufficiency.',
            'Speaker identity, adoption basis, polarity, conditions, scope, qualifications and warrants are not filled.',
            'No production admission, actual pastor fingerprints, comparisons or rankings.'],
        next_step='Retain partial observations for upstream integration. Complete semantic fields and validate them before enabling claim aggregation; no automatic inference or experiment.')


def build(base_dir=None,*,input_path=None,check_only=False):
    inputs=load_inputs(base_dir,input_path);observations=integrate(inputs);summary=report(observations)
    manifest=dict(version=VERSION,origin='machine_generated',input_fingerprint=inputs['packet']['input_fingerprint'],
        preserved_files=inputs['preserved_files'],observation_ids=[r['id'] for r in observations],
        code_identity={m.__name__:check.demo.file_hash(Path(m.__file__)) for m in (evidence,check,check.choices)},adapter_sha256=check.demo.file_hash(Path(__file__)),
        policy=dict(namespace=evidence.EXPERIMENTAL,partial_only=True,production_admission=False,automatic_inference=False),
        generation_calls=0,paid_calls=0)
    manifest['manifest_fingerprint']=evidence.digest(manifest)
    out=check.demo.build_paths(base_dir).evaluation/'role-observations'/manifest['manifest_fingerprint']
    if out.resolve().is_relative_to(Path(__file__).parents[2].resolve()): raise ValueError('Artifacts must be outside repository')
    if not check_only:
        store=evidence.EvidenceArtifactStore(out)
        store.write_immutable('manifest.json',manifest);store.write_immutable('observations.json',observations);store.write_immutable('report.json',summary)
        lines=['# Partial role observations integration','',
            'Offline integration: **PASS**. Semantic completeness: **INCONCLUSIVE**. No inference calls.',
            '',f'{len(observations)} experimental machine observations preserve literal role evidence, raw distributions and per-field request/receipt provenance. No complete observations are eligible.',
            '', '| Field | Known | Unknown |', '| --- | ---: | ---: |']
        lines.extend(f'| {field} | {count} | {len(observations)-count} |' for field,count in summary['known_fields'].items())
        lines.extend(['','Known values clear the existing diagnostic gate; they are not calibrated semantic acceptance. Unknown values remain null with false masks. A role label cannot supply speaker identity, adoption basis, polarity, conditions or warrants. The shared consumer retains these records and excludes them from fingerprint claims/relations.','',
            'Checks: immutable source/receipt hashes, exact saved-answer replay, source/candidate compatibility for reused decisions, literal source spans, field inventory, current accounting and policy exclusion. Historical artifacts remain unchanged.','',
            'Scope: six exposed candidates across the same three windows; no blinded benchmark, collection expansion, actual pastor fingerprint/comparison or production admission.','',
            'Next prerequisite: complete and validate missing semantic fields at the upstream producer before claim aggregation. Existing source review and diagnostic labels do not establish that the selected evidence is sufficient. No further experiment or automatic inference is launched.',''])
        path=out/'report.md';text='\n'.join(lines)
        if path.exists() and path.read_text()!=text: raise ValueError('Immutable report differs')
        path.write_text(text)
    return summary|dict(status='CHECKED_NO_WRITES' if check_only else 'MATERIALIZED_OFFLINE',manifest_fingerprint=manifest['manifest_fingerprint'],manifest=str(out/'manifest.json'),report=str(out/'report.md'),output=str(out/'observations.json'))
