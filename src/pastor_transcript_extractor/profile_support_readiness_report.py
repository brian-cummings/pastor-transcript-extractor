"""Saved readiness decision and cost audit; no inference or automatic successor."""
from decimal import Decimal
from pathlib import Path
import json
from . import profile_support_readiness_review as review
from . import profile_support_regression as regression
from . import profile_support_readiness as readiness
from . import profile_analysis_support_execution as x


def prepare(root):
    root=Path(root);work=json.loads((root/'work-plan.json').read_text());auth=json.loads((root/'allowance.json').read_text())
    regression_result=json.loads((root/'regression-report.json').read_text());human=json.loads((root/'human-review/packet.json').read_text())
    if human['packet_fingerprint']!=x.digest({k:v for k,v in human.items() if k!='packet_fingerprint'}):raise ValueError('Human review packet differs')
    checks=[work['regression_input_sha256']==readiness.file_hash(root/'regression-inputs.json'),work['reference_sha256']==readiness.file_hash(root/'regression-references.json')]
    if not all(checks):raise ValueError('Original frozen regression cases or references changed')
    paths=sorted(root.glob('capacity/*/results.json'))+sorted(root.glob('regression/*/results.json'))+sorted(root.glob('judgment-diagnostic/*/results.json'))
    if len(paths)!=6:raise ValueError('Expected one capacity, four regression and one two-case diagnostic result')
    charges=Decimal(0);reserve=Decimal(0);estimated=Decimal(0);estimates=0;attempts=0;corrections=0;receipts={};batches=[]
    for path in paths:
        p=json.loads((path.parent/'input.json').read_text());r=json.loads(path.read_text())
        if p['input_fingerprint']!=x.digest({k:v for k,v in p.items() if k!='input_fingerprint'}) or r['input_fingerprint']!=p['input_fingerprint']:raise ValueError('Foreign saved result')
        if r['halt'] or r['execution_status']!='COMPLETE':raise ValueError('A readiness call remains halted or uncertain')
        cap=Decimal(p['budget']['reserved_usd'])
        if cap>Decimal('.50'):raise ValueError('A batch exceeded the authorized reservation')
        reserve+=cap;charges+=Decimal(r['accounting']['new_conservative_charge_usd']);attempts+=r['accounting']['new_paid_attempts'];corrections+=r['accounting']['contract_corrections']
        batches.append(dict(input=review.reference(path.parent/'input.json'),results=review.reference(path),reservation_usd=str(cap),accounting=r['accounting']))
        for row in r['results']:
            for turn in row.get('rounds',[row]):
                if turn.get('receipt'):receipts[turn['receipt']]=json.loads(Path(turn['receipt']).read_text())
    # Count estimates only for calls made by this goal; the capacity batch's
    # original invalid answer was cached before the goal and remains historical.
    goal_fingerprints={}
    for batch in batches:
        p=json.loads(Path(batch['input']['path']).read_text())
        for task in p['tasks']:
            spec=x.requests.RequestSpec(**task['request'])
            if '/capacity/' not in batch['input']['path']:goal_fingerprints[spec.fingerprint]=True
    for ref,r in receipts.items():
        spec=x.requests.RequestSpec(**r['request'])
        if spec.fingerprint not in goal_fingerprints and not spec.source_identity.get('correction_of'):continue
        raw=r.get('response',{}).get('raw',{});usage=raw.get('usage',{})
        if usage.get('estimated_cost') is not None:estimated+=Decimal(str(usage['estimated_cost']));estimates+=1
    start=Decimal(auth['starting_conservative_usd']);ceiling=Decimal(auth['cumulative_ceiling_usd'])
    if charges>Decimal(auth['additional_usd']):raise ValueError('Goal allowance exceeded')
    with x.supervised.cumulative_history(dict(budget=dict(spend_root=auth['spend_root'])),root/'final-ledger') as history:
        ledger=x.supervised.BASELINE_SPEND+sum((cost for _,cost in history),Decimal(0))
    if ledger!=start+charges:raise ValueError('Independent ledger movement must be reconciled before final reporting')
    diagnostic=json.loads(next(root.glob('judgment-diagnostic/*/results.json')).read_text())
    judgment_cases=[dict(claim_id=r['claim_id'],status=r['status'],answer=r['judgment']['answer'] if r['judgment'] else None,receipt=r['receipt']) for r in diagnostic['results']]
    prior_findings=json.loads(Path(human['source_review_findings_reference']['path']).read_text())
    indexed_findings={f['id']:f for f in prior_findings['findings']}
    blocked={key:dict(value,blocked_statement=indexed_findings[key]['blocked_statement'],
        source_coordinates={k:indexed_findings[key][k] for k in ('videos','blocks','blocks_by_video') if k in indexed_findings[key]},
        inspected_reuse=indexed_findings[key]['inspected_reuse'],
        smallest_change=indexed_findings[key]['smallest_remedy'],authorization_boundary=indexed_findings[key]['authorization'])
        for key,value in human['reuse_audit']['missing_producer_contracts'].items()}
    for row in judgment_cases:
        row['assistant_evaluation']=('Preservation distinction improved; the model recognizes the supplied limits. Independent review remains pending.' if row['claim_id']=='reader-portrait-posture' else 'FAIL: the model still approves comparative priority without establishing it; its explanation evaluates a possible question and overlooks the actual priority assertion.')
    model_document=json.loads((root/'human-review/document-input.json').read_text())
    requirements=[
        dict(requirement='Freeze implementation sequence and acceptance criteria',status='PASS',evidence=['work-plan.json','regression-inputs.json','regression-references.json']),
        dict(requirement='Reserve complete corrective headroom; preserve exact successful caches',status='PASS',evidence=['capacity saved initial and corrective receipts','focused headroom and cache-identity tests']),
        dict(requirement='Improve whole-statement and qualification judgment without reference feedback',status='PARTIAL',evidence=['whole-statement-support-v1','regression-report.json','two-case judgment diagnostic'],limit='11/12 frozen references match; the actual priority statement still receives unsupported approval. Qualification preservation improved. Contradiction-versus-uncertainty discrepancy remains. No accuracy rate inferred'),
        dict(requirement='Reuse upstream evidence and integrate missing distinctions as far as existing evidence permits',status='BLOCKED_EVIDENCE_NOT_COLLECTED_OR_VALIDATED',evidence=['evidence-reuse-audit.json','human-review/packet.json'],limit='1,422 exact registered identities absent; broad existing contracts do not imply particular adopted positions; three salvation leaves remain quarantined'),
        dict(requirement='Focused tests and at most two evidence-driven implementation iterations',status='PASS',evidence=['verification.json','capacity policy increment','single whole-statement instruction increment'],limit='No further prompt variants, reference changes, models or semantic retries'),
        dict(requirement='Prepare independent whole-profile validation',status='HUMAN_REVIEW_PREPARED_HOLDOUT_BLOCKED',evidence=['human-review/packet.json','holdout-audit.json'],limit='36 concrete statement decisions plus complete 162-block sample review; human decisions pending; all existing compatible profiles exposed'),
        dict(requirement='Additional $3 superseding allowance and maximum fifty-cent batches',status='PASS',evidence=['allowance.json','saved batch inputs and receipts','shared conservative ledger']),
        dict(requirement='Preserve production boundaries and stop without successor',status='PASS',evidence=['not_admitted on all outputs','unchanged source artifacts and quarantines'],limit='No broad jobs, new recording collection, pastor comparisons or admission changes')]
    result=dict(version='profile-support-readiness-report-v1',decision='RETROSPECTIVE_HUMAN_REVIEW_READY_INDEPENDENT_HOLDOUT_BLOCKED',accuracy_established=False,
        objective=work['objective'],human_review=review.reference(root/'human-review/packet.json'),requirements=requirements,
        implementation={m.__name__:readiness.file_hash(m.__file__) for m in (x,x.core,x.correction,x.requests,x.budget_guard,regression,review,readiness)},
        regression=dict(status=regression_result['status'],matched=regression_result['matched'],total=regression_result['total'],mismatches=[{k:r[k] for k in ('id','expected','actual')} for r in regression_result['checks'] if not r['matched']],limitation=regression_result['limitation']),
        judgment_diagnostic=judgment_cases,model_handoff=dict(coverage=model_document['coverage'],authority='All 36 are now model-supported and mechanically processable. This is NOT semantic acceptance: the known priority error remains, and independent human review is pending.'),batches=batches,blocked_statements=blocked,holdout=human['review']['holdout'],
        costs=dict(starting_conservative_usd=str(start),additional_allowance_usd=auth['additional_usd'],new_conservative_charge_usd=str(charges),new_provider_estimated_usd=str(estimated),provider_estimate_receipts=estimates,
            new_paid_attempts=attempts,mechanical_corrections=corrections,maximum_reserved_across_completed_batches_usd=str(reserve),largest_batch_reservation_usd=str(max(Decimal(b['reservation_usd']) for b in batches)),pending_reservation_usd='0',cumulative_conservative_usd=str(ledger),cumulative_ceiling_usd=str(ceiling),remaining_goal_allowance_usd=str(ceiling-ledger),actual_invoice_usd=None,invoice_limit='Provider estimates and list-price ledger are not an invoice; no cached-token discount assumed in reservation'),
        next_action='Review the prepared concrete human packet and decide whether to authorize one focused producer/judgment revision for unsupported comparative priority. Do not expand evaluation infrastructure to bypass that failure. Before independent whole-profile accuracy testing, identify an accepted unexposed profile with compatible materialized evidence; separately authorize upstream gap collection/validation if those missing dimensions are to be claimed.',
        stop='No automatic successor experiment; no remaining paid calls',production_admission='not_admitted')
    result['report_fingerprint']=x.digest(result);x.Store(root).write_immutable('readiness-report.json',result)
    lines=['# Whole-profile accuracy readiness','', '**Decision: retrospective human review is ready; independent whole-profile validation remains blocked. Accuracy is not established.**','',
        'Correction capacity is fixed. A saved invalid answer received its single fully reserved correction without regenerating the original. The same initial and successful corrective cache identities are preserved.','',
        f"Frozen synthetic checks: {regression_result['matched']}/{regression_result['total']} reference matches. The mismatch remains a reported failure; references, thresholds and labels were not changed to pass it.",'','## Profile judgment diagnostic','']
    for row in judgment_cases:lines += [f"- {row['claim_id']}: model **{row['answer']['judgment'] if row['answer'] else row['status']}**. {row['assistant_evaluation']}"]
    lines+=['','These are exposed development cases, not an independent accuracy benchmark. No controlled synthetic before/after baseline was run. The recomputed handoff has 36 model-supported, mechanically processable statements, but the known priority error proves that this is not semantic acceptance. The document remains an unapproved review artifact.','','## Readiness by requirement','', '| Requirement | Outcome |','|---|---|']+[f"| {r['requirement']} | {r['status']} |" for r in requirements]
    lines+=['','## Exact missing evidence and producer boundaries','']
    for key,v in result['blocked_statements'].items():lines += [f"- **{key}**: {v['missing']}. Responsible producer: {v['owner']}. Acceptance: {v['acceptance']}."]
    lines+=['','The prior source-review findings name the corresponding blocked reader-facing statements and source block coordinates. The new audit records every full-pack, refinement, individual and persisted composed identity inspected, plus compatible materialized layers and reviewed binding reuse. No absent answer was reconstructed downstream.','','## Human and independent validation','',f"[Prepared 36-statement review packet]({root/'human-review/review.md'})",'', 'All 162 canonical blocks are linked, including four excluded from projection measurements. Model recommendations and prior assistant source judgments are separate from blinded statement pages. Human review is pending; neither model nor assistant review is independent human validation.','',result['holdout']['smallest_remedy'],'','## Cost audit','',f"New conservative usage: ${charges}; provider-estimated usage: ${estimated}; {attempts} new paid attempts. Starting ledger: ${start}; final ledger: ${ledger}. The additional authorization is $3, and ${ceiling-ledger} remains unused. Largest batch reservation: ${result['costs']['largest_batch_reservation_usd']}. Pending reservation: $0. No invoice is available.",'','## Verification','',f"[Focused verification results]({root/'verification.json'})",'','## Next action','',result['next_action'],'','No further experiment, classification job, profile comparison or production admission was launched.','']
    (root/'readiness-report.md').write_text('\n'.join(lines))
    return result
