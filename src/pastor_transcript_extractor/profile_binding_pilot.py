"""Execute the authorized source-review pilot: serialize authored bindings only.

No candidate discovery, semantic judgment or new vocabulary is performed by code.
The unchanged G1 pure composer receives explicitly authored field decisions.
Literal-coordinate checks are integrity checks, not independent semantic review.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import html
import json
from pathlib import Path

from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor import profile_description
from pastor_transcript_extractor.sermon_g1_feasibility_review import compose, questions
from pastor_transcript_extractor.sermon_topics import resolve_topic_analysis_artifact, resolve_topic_block_context
from pastor_transcript_extractor.segment_profile_view import timestamp

VERSION = 'profile-binding-source-review-v1'
READINGS_PATH = Path(__file__).with_name('data') / 'profile-binding-source-readings-v1.json'
FIELDS = ('proposition','subject','relation','polarity','expression','voice','adoption','conditions','qualifications','epistemic_status','scope')
GAPS = {
    'predicate_inventory': dict(title='The reusable binding envelope is coupled to a narrow proof vocabulary',
        evidence='The passages assert saving mercy, completion of a good work, saving desire, warnings, criticism of neutrality and invited confidence. These are not interchangeable with knowability of present acceptance, loss or retention.',
        effect='Exact proposition words and partial facts can be preserved, but a faithful general theological proposition cannot always receive one of the existing G1 relations.',
        boundary='No predicate, doctrine label or subject is added here.',
        recommendation='Separately review separating the reusable evidence/attribution envelope from subject-specific predicate contracts. Reuse claim_span as literal content; do not launch an exhaustive theology catalog.'),
    'projected_voice': dict(title='Projected utterance versus actual report is not a selectable distinction',
        evidence='“you will say Lord ...” and “Can you ... say ...” supply words for an invited listener. No listener is attested to have spoken them.',
        effect='The proof menu offers preacher, explicitly reported speakers, mixed and unclear. Its assertion/question/open-issue menu cannot independently encode a merely projected declarative utterance. Voice/expression remain withheld where choosing a value would falsely attest speech.',
        boundary='No invited_listener or hypothetical_assertion enum is introduced.',
        recommendation='Review a speech-frame/utterance-occurrence distinction independently from proposition content and preacher adoption; inspect applicable G2/G3 framing reuse before any extension.'),
    'nonconditional_qualification': dict(title='Nonconditional qualifications are preserved as text but not typed',
        evidence='“anyway” qualifies saving desire concessively; “because you are lukewarm ...” gives a stated ground. Neither is automatically an if/only-if condition.',
        effect='G1 can retain these words in claim_span/binding_evidence, but its typed conditions list admits only condition/exception. It does not explicitly bind concession or rationale as such.',
        boundary='No new condition kind or causal/necessity interpretation is added.',
        recommendation='Preserve literal evidence now. Separately review whether existing G2 reason/claim links or a qualified-binding design can express the needed relation without widening conditions.'),
    'evaluation_target': dict(title='The target of rejection must be distinguished from a proposition’s logical negation',
        evidence='The preacher criticizes a “middle of the road Christian” stance. That does not settle the truth of the reported speakers’ Christian identity.',
        effect='G1 separates adoption and polarity, which prevents manufacturing an opposite, but the exact proposition/evaluation target must first be specified. The narrow predicate set cannot encode this critique.',
        boundary='No not_a_Christian or opposed_assurance predicate is manufactured.',
        recommendation='Retain the report and the preacher’s own critique separately. A future general contract must identify the exact evaluated proposition before a rejection label can support a position.'),
    'rhetorical_invitation': dict(title='Question form does not encode the communicative act',
        evidence='“Can you ... say ...” invites confidence. It is not necessarily an unanswered inquiry into salvation’s knowability.',
        effect='Question is a usable surface-expression value, but does not encode invitation versus information-seeking or projected adoption. Do not assign unsettled or expressed_uncertainty merely from a question mark.',
        boundary='No new speech-act classifier or semantic judgment is implemented.',
        recommendation='Keep expression, epistemic uncertainty and adoption separate; consider existing listener/address contracts for a separately designed speech-frame binding.'),
}


def text_digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def validate_span(span, texts):
    field = span.get('source_field')
    if field not in ('target_text','leading_context','trailing_context'):
        raise ValueError('Unknown evidence source field')
    start, end = span.get('start'), span.get('end')
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(texts[field]):
        raise ValueError('Evidence coordinates outside the supplied source')
    if texts[field][start:end] != span.get('text'):
        raise ValueError('Authored evidence no longer matches the literal source')


def compile_reading(case_id, texts, authored):
    row = deepcopy(authored)
    validate_span(row['unit']['claim_span'], texts)
    if row['unit']['claim_span']['source_field'] != 'target_text':
        raise ValueError('A target claim cannot be supplied by context')
    if set(row['field_review']) != set(FIELDS):
        raise ValueError('Every required binding field needs a source-review entry')
    for pool, values in row['phrase_pools'].items():
        for span in values.values():
            validate_span(span, texts)
            if pool == 'frames' and span['source_field'] != 'target_text':
                raise ValueError('Voice/adoption framing must be supported in the target')
    for field in row['field_review'].values():
        for span in field['evidence']:
            validate_span(span, texts)
    for span in row['additional_binding_evidence']:
        validate_span(span, texts)
    inventory = questions(row['phrase_pools'])
    decisions = row['authored_decisions']
    if set(decisions) != set(inventory):
        raise ValueError('Authored decisions must use the unchanged G1 question inventory')
    for name, choice in decisions.items():
        if choice not in inventory[name]['criteria']:
            raise ValueError('A new G1 choice cannot be introduced by the source review')
        if name.startswith('bind_') and choice == 'bound':
            span = row['phrase_pools']['conditions'][name.removeprefix('bind_')]
            if span['source_field'] != 'target_text' or row['field_review']['conditions']['status'] != 'supported':
                raise ValueError('An unreviewed or context-only condition cannot be bound')
    if decisions['epistemic_status'] == 'expressed_uncertainty' and decisions['epistemic_evidence'] in ('none','unclear'):
        raise ValueError('Expressed speaker uncertainty requires exact evidence')
    record = compose(texts | {'phrase_pools':row['phrase_pools']}, row['unit'], decisions)
    for span in row['additional_binding_evidence']:
        if span not in record['binding_evidence']:
            record['binding_evidence'].append(span)
    row['g1_record'] = record
    row['case_id'] = case_id
    row['authorship'] = 'Codex source-reviewed proposal; not a model answer or Brian acceptance'
    row['contract_gap_ids'] = list(dict.fromkeys(row['contract_gap_ids']))
    if any(key not in GAPS for key in row['contract_gap_ids']):
        raise ValueError('Unrecognized representational gap')
    return row


def build(record, authored, contexts):
    if authored['inventory_fingerprint'] != record['inventory_fingerprint'] or authored['membership_fingerprint'] != record['profile'].get('membership_fingerprint'):
        raise ValueError('Reviewed inventory or membership changed')
    cases = record['capability_review']['cases']
    if len(cases) != 3 or len(authored['cases']) != 3 or {c['evidence_id'] for c in cases} != {c['evidence_id'] for c in authored['cases']}:
        raise ValueError('The pilot must retain exactly the three authorized prepared passages')
    by_id = {c['evidence_id']:c for c in cases}
    results = []
    for review in authored['cases']:
        source = by_id[review['evidence_id']]
        context = contexts[review['evidence_id']]
        if review['source_sha256'] != source['source_sha256'] or review['target_sha256'] != text_digest(source['full_target_text']):
            raise ValueError('A prepared pilot source changed')
        if text_digest(json.dumps(context, sort_keys=True, ensure_ascii=False)) != review['context_sha256'] or context['target_text'] != source['full_target_text']:
            raise ValueError('The supplied target or context changed')
        texts = {key:context[key] for key in ('target_text','leading_context','trailing_context')}
        readings = [compile_reading(review['case_id'], texts, row) for row in review['readings']]
        if not readings or len({row['id'] for row in readings}) != len(readings):
            raise ValueError('Missing or duplicate proposed readings')
        results.append(dict(case_id=review['case_id'], title=source['title'], sermon_title=source['sermon_title'],
            video_id=source['video_id'], block_id=source['block_id'], source_sha256=source['source_sha256'],
            start_seconds=source['start_seconds'], end_seconds=source['end_seconds'], watch_url=source['watch_url'],
            existing_observation=dict(state=source['current_state'], probability=source['probability'], threshold=source['threshold'], used_as_binding_authority=False),
            texts=texts, context_diagnostics=context.get('diagnostics',{}), readings=readings))
    used = {gap for case in results for row in case['readings'] for gap in row['contract_gap_ids']}
    return seal(dict(version=VERSION, status='SOURCE_REVIEW_EXECUTED_PROPOSED_READINGS_READY_FOR_BRIAN',
        capability='Faithful source-reviewed theological proposition binding', test_domain='Assurance of salvation; not an assurance classifier',
        source_inventory_fingerprint=record['inventory_fingerprint'], membership_fingerprint=record['profile'].get('membership_fingerprint'),
        cases=results, contract_gaps={key:dict(value, supporting_reading_ids=[row['id'] for case in results for row in case['readings'] if key in row['contract_gap_ids']]) for key,value in GAPS.items() if key in used},
        conclusion=dict(verdict='PARTIAL_FIT_NOT_SUFFICIENT_UNCHANGED_FOR_GENERAL_BINDING',
            sufficient='The existing envelope preserves exact claims, separate voice/adoption, conditions, scope, epistemic distinctions and conservative partial records. These readings demonstrate those useful properties on supplied passages.',
            insufficient='The unchanged subject/relation proof inventory cannot faithfully admit all concrete theological propositions here. Projected speech, nonconditional qualifications and the exact target of evaluation are not fully typed by the existing fields/menus.',
            recommendation='Retain G1 as the evidence-binding backbone, but do not declare the unchanged contract sufficient for a reusable general position capability. Separately review the precise predicate, speech-frame and qualification gaps before any contract extension. No extension is implemented in this pilot.',
            scope_limit='This is a Codex-authored source review of three supplied passages, not automatic binding accuracy, discovery recall, a general benchmark, opportunity coverage or a pastor-wide assurance assessment.'),
        published_profile_positions=[], contract_extended=False, provider_requests=0, database_writes=0,
        automatic_binding=False, new_measurements=False, new_discovery=False, broader_collection=False,
        collector_changes=False, threshold_changes=False, profile_projection=False, quote_execution=False,
        source_review_executed=True, human_acceptance='pending', structural_checks_are_semantic_validation=False))


def load(base_dir=None):
    authored = json.loads(READINGS_PATH.read_text())
    for key in ('contract','composer'):
        if trace.digest(trace.ROOT / authored[key+'_path']) != authored[key+'_sha256']:
            raise ValueError('The frozen G1 '+key+' changed; no pilot reinterpretation is permitted')
    record = profile_description.load(base_dir)
    contexts = {}
    for case in record['capability_review']['cases']:
        source = next(s for s in record['source_identity'] if s['video_id'] == case['video_id'])
        path = Path(source['source_path'])
        if trace.digest(path) != case['source_sha256']:
            raise ValueError('Source changed during pilot load')
        raw = json.loads(path.read_text())
        analysis = resolve_topic_analysis_artifact(raw['classification'])
        block = next(b for b in analysis['blocks'] if b['block_id'] == case['block_id'])
        contexts[case['evidence_id']] = resolve_topic_block_context(block)
    return build(record, authored, contexts)


def markdown(report):
    lines = ['# Who asserted what? Source-reviewed theological bindings', '',
        '**Completed provider-free pilot; proposed readings for Brian’s review.** Assurance is the test domain; the capability is faithful proposition binding, not assurance classification.', '',
        'The source review below separates what the passages say from what the frozen G1 vocabulary can encode. “No in-scope claim” means no admitted claim in that narrow vocabulary, not no theology, no assertion or doctrinal denial.', '',
        'Each field is proposed from direct source inspection. Code checks literal spans and serializes those authored decisions using the unchanged G1 composer; those checks do not independently prove semantic correctness.', '']
    for case in report['cases']:
        lines += ['## '+case['sermon_title']+' · '+timestamp(case['start_seconds'])+'–'+timestamp(case['end_seconds']), '',
            '[Watch this passage]('+case['watch_url']+')', '', case['title'], '']
        for row in case['readings']:
            lines += ['### '+row['title'], '', '**Proposed reading:** '+row['proposed_reading'], '',
                '| Binding field | Source-reviewed finding | Exact source evidence |', '|---|---|---|']
            for field in FIELDS:
                review = row['field_review'][field]
                evidence = '<br>'.join('“'+span['text'].replace('\n',' ').replace('|','/')+'” ('+span['source_field']+', '+str(span['start'])+'–'+str(span['end'])+')' for span in review['evidence'])
                lines.append('| '+field.replace('_',' ')+' | '+review['finding'].replace('|','/')+' | '+evidence+' |')
            lines += ['', '**Withheld conclusions:**', '']+['- '+text for text in row['withheld_conclusions']]
            lines += ['', '<details><summary>Proposed record in the unchanged G1 representation</summary>', '', '```json', json.dumps(row['g1_record'],ensure_ascii=False,indent=2), '```', '', '</details>', '']
        lines += ['<details><summary>Complete target and existing bounded context</summary>', '']
        for field, text in case['texts'].items():
            lines += ['**'+field.replace('_',' ')+'**', '', '> '+text.replace('\n','\n> '), '']
        lines += ['Context is reference/framing evidence, not a source of missing target assertions. Truncation/normalization diagnostics are preserved in JSON.', '', '</details>', '']
    lines += ['## Recommendation: is unchanged G1 sufficient?', '', report['conclusion']['verdict'].replace('_',' ').capitalize(), '',
        report['conclusion']['sufficient'], '', report['conclusion']['insufficient'], '', report['conclusion']['recommendation'], '',
        '**Evidence limit:** '+report['conclusion']['scope_limit'], '',
        'The supplied readings do not contain an unambiguous positive example of a condition/exception bound to an admitted G1 assurance predicate, or explicit speaker uncertainty. The pilot therefore does not validate positive performance on those distinctions; empty conditions and not_stated uncertainty must not become unconditional doctrine or pastoral certainty.', '',
        '### Precise gaps, without contract extension', '']
    for key, gap in report['contract_gaps'].items():
        lines += ['#### '+gap['title'], '', 'Source readings: '+', '.join(f'[Inspect {key}](index.html#{key})' for key in gap['supporting_reading_ids']), '', gap['evidence'], '', '**What cannot be encoded faithfully:** '+gap['effect'], '', gap['boundary'], '', '**Recommendation:** '+gap['recommendation'], '']
    lines += ['## Reproduce these completed readings', '', '```bash', 'pte analysis profile-binding-review --json', '```', '',
        'For freshness/literal-integrity verification without writing artifacts:', '', '```bash', 'pte analysis profile-binding-review --check-only --json', '```', '',
        'No providers, new measurements, automatic binding, doctrine vocabulary, collection, collector/threshold changes, discovery, profile projection or quotation execution. The existing profile and raw observations remain unchanged. These proposals are not a new semantic admission authority.', '']
    return '\n'.join(lines)


def render(report):
    from pastor_transcript_extractor.profile_presentation import STYLE
    e = lambda value: html.escape(str(value),quote=True)
    parts = []
    labels = dict(proposition='What is said', subject='Subject / referent', relation='G1 relation', polarity='Polarity', expression='Expression / utterance', voice='Who voices it', adoption='Preacher adoption', conditions='Conditions / exceptions', qualifications='Other qualifications', epistemic_status='Speaker uncertainty', scope='Scope')
    for case in report['cases']:
        rows = []
        for row in case['readings']:
            fields = []
            for field in FIELDS:
                finding = row['field_review'][field]
                spans = ''.join('<blockquote>'+e(span['text'])+'<div class="muted"><a href="#'+e(case['case_id']+'-'+span['source_field'])+'">'+e(span['source_field'].replace('_',' '))+'</a> · characters '+str(span['start'])+'–'+str(span['end'])+'</div></blockquote>' for span in finding['evidence'])
                fields.append('<tr><th>'+e(labels[field])+'</th><td>'+e(finding['finding'])+'</td><td>'+spans+'</td></tr>')
            withheld = ''.join('<li>'+e(text)+'</li>' for text in row['withheld_conclusions'])
            rows.append('<article id="'+e(row['id'])+'"><h3>'+e(row['title'])+'</h3><p class="note">'+e(row['proposed_reading'])+'</p>'+
                '<details><summary>Inspect each binding field and its exact evidence</summary><div class="tablewrap"><table><thead><tr><th>Field</th><th>Proposed source reading</th><th>Exact evidence</th></tr></thead><tbody>'+''.join(fields)+'</tbody></table></div></details>'+
                '<p><strong>Withheld conclusions</strong></p><ul>'+withheld+'</ul><p>Representation gaps: '+', '.join('<a href="#gap-'+e(key)+'">'+e(GAPS[key]['title'])+'</a>' for key in row['contract_gap_ids'])+'</p>'+
                '<details class="technical"><summary>Proposed G1 record and source-review decisions</summary><pre>'+e(json.dumps(dict(g1_record=row['g1_record'],authored_decisions=row['authored_decisions'],contract_gap_ids=row['contract_gap_ids']),ensure_ascii=False,indent=2))+'</pre></details></article>')
        source = ''.join('<details id="'+e(case['case_id']+'-'+field)+'"><summary>'+e(field.replace('_',' ').capitalize())+'</summary><div class="source">'+e(text)+'</div></details>' for field,text in case['texts'].items())
        parts.append('<section class="panel" id="'+e(case['case_id'])+'"><h2>'+e(case['sermon_title'])+'</h2><p>'+e(timestamp(case['start_seconds'])+'–'+timestamp(case['end_seconds']))+' · <a href="'+e(case['watch_url'])+'" target="_blank" rel="noopener noreferrer">Watch passage</a></p>'+''.join(rows)+
            '<h3>Complete supplied passage and context</h3>'+source+'<p class="muted">Only the supplied target supports assertions. Existing context can resolve references; its original truncation diagnostics remain visible below.</p>'+
            '<details class="technical"><summary>Source identity and context diagnostics</summary><pre>'+e(json.dumps({key:value for key,value in case.items() if key not in ('readings','texts')},ensure_ascii=False,indent=2))+'</pre></details></section>')
    gaps = ''.join('<article id="gap-'+e(key)+'"><h3>'+e(gap['title'])+'</h3><p>'+e(gap['evidence'])+'</p><p>'+e(gap['effect'])+'</p><p class="muted">'+e(gap['boundary'])+'</p><p>'+e(gap['recommendation'])+'</p><p>Inspect source readings: '+', '.join('<a href="#'+e(row_id)+'">'+e(row_id)+'</a>' for row_id in gap['supporting_reading_ids'])+'</p></article>' for key,gap in report['contract_gaps'].items())
    conclusion = report['conclusion']
    navigation = '''<script>function reveal(){let key;try{key=decodeURIComponent(location.hash.slice(1));}catch{return;}let el=document.getElementById(key);if(!el)return;let p=el;while(p){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}el.scrollIntoView();}window.addEventListener('hashchange',reveal);window.addEventListener('load',reveal);</script>'''
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Who asserted what? · Source-reviewed binding pilot</title><style>'+STYLE+'blockquote{margin:10px 0;padding:8px 12px;border-left:2px solid var(--line);font-family:Georgia,serif}article{border-top:1px solid var(--line);margin-top:24px;padding-top:12px}td{min-width:200px}pre{max-width:100%}</style></head><body><main>'+
        '<span class="eyebrow">PASTOR TRANSCRIPT EXTRACTOR · COMPLETED SOURCE REVIEW</span><h1>Who asserted what?</h1><p class="assessment">'+str(sum(len(case['readings']) for case in report['cases']))+' proposed readings from '+str(len(report['cases']))+' supplied passages. Assurance is the test domain; faithful theological proposition binding is the capability under review.</p>'+
        '<p class="note">These are concrete Codex source-reviewed proposals, pending Brian’s acceptance. The current G1 record is shown separately from what the source lets us say. A missing in-scope relation never means that the passage contains no theology or no assertion.</p>'+
        '<p><a href="readings-v1.md">Readable Markdown report</a> · <a href="readings-v1.json">Complete bindings and provenance</a></p>'+
        '<nav>'+''.join('<a href="#'+e(case['case_id'])+'">'+e(case['sermon_title'])+'</a> ' for case in report['cases'])+'<a href="#recommendation">Recommendation</a></nav>'+''.join(parts)+
        '<section class="panel" id="recommendation"><h2>Is the existing G1 representation sufficient?</h2><p class="note">Useful backbone; not sufficient unchanged for the general capability.</p><p>'+e(conclusion['sufficient'])+'</p><p>'+e(conclusion['insufficient'])+'</p><p>'+e(conclusion['recommendation'])+'</p><p>'+e(conclusion['scope_limit'])+'</p><p>No unambiguous positive condition/exception binding to an admitted assurance predicate, or explicit speaker uncertainty, is established by these supplied readings. This pilot does not validate positive performance on those distinctions.</p>'+gaps+'</section>'+
        '<footer>No provider execution, new measurements, automatic binding, new doctrine vocabulary, collection, collector/threshold changes, profile projection, discovery or quote execution. Exact evidence excerpts are source-review citations, not the illustrative quotation pipeline.</footer></main>'+navigation+'</body></html>')


def prepare(base_dir=None):
    report = load(base_dir)
    authored = json.loads(READINGS_PATH.read_text())
    manifest = seal(dict(version=VERSION, report=report, implementation_files={
        str(Path(__file__)):trace.digest(__file__), str(READINGS_PATH):trace.digest(READINGS_PATH),
        str(trace.ROOT/authored['contract_path']):authored['contract_sha256'],
        str(trace.ROOT/authored['composer_path']):authored['composer_sha256']},provider_requests=0,database_writes=0))
    out = build_paths(base_dir).evaluation / VERSION / manifest['content_fingerprint']
    out.mkdir(parents=True, exist_ok=True)
    files = {'readings-v1.json':json.dumps(manifest,ensure_ascii=False,indent=2)+'\n', 'readings-v1.md':markdown(report), 'index.html':render(report)}
    for name,text in files.items():
        path = out/name
        if path.exists() and path.read_text()!=text:
            raise ValueError('Immutable source-review artifact differs')
        path.write_text(text)
    return report,out/'index.html'
