from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import passage_voice_context as v
from pastor_transcript_extractor.binding_evidence import validate_span
from pastor_transcript_extractor.cli import app
from test_source_passages import window_with


def span(uid): return dict(start_unit=uid,end_unit=uid)


def specimen():
    window=window_with('The guide said this. The gate is open. I endorse that message.')
    state=dict(sources=dict(w0=v.c.passages.inventory(window)),items=[dict(item_id='i0',source_id='w0',candidate_reading='The gate is open.')])
    packet=dict(input_fingerprint='synthetic',state=state,windows=dict(w0=asdict(window)),before=dict(selections=[dict(item_id='i0',status='selected',proposition_range=span('u0001'),adoption_ranges=[span('u0002')])]),
        prior_audits=[dict(item_id='i0',evidence_units=['u0000','u0001'],finding='no_demonstrated_defect',action='retain')],request=asdict(v.c.reader_request(state)),
        history=dict(prior_accounting=dict(cumulative_attempts=99,cumulative_local_attempts=28,cumulative_paid_attempts=71,cumulative_known_list_price_usage_usd='.362334670')))
    packet['request']=asdict(v.reader_request(packet));return packet


def output(status='context_selected'):
    return dict(contexts=[dict(item_id='i0',status=status,voice_context_ranges=[span('u0000')] if status=='context_selected' else [],rationale='The preceding sentence identifies the reported speaker.' if status=='context_selected' else 'The speaker frame remains a source judgment.')])


class VoiceContextTests(unittest.TestCase):
    def test_roles_remain_separate_exact_compiler_spans_without_label_inference(self):
        packet=specimen();before=deepcopy(packet);checked=v.inspect(output(),packet)
        self.assertFalse(checked['errors']);self.assertEqual(packet,before)
        package=checked['evidence'][0]['package'];fields=package['binding_evidence']
        self.assertEqual(fields['proposition']['span']['text'],' The gate is open.')
        self.assertEqual([s['text'] for s in fields['voice']['evidence']],[' The gate is open.','The guide said this.'])
        self.assertEqual([s['text'] for s in fields['adoption']['evidence']],[' I endorse that message.'])
        texts=v.c.SourceWindow(**packet['windows']['w0']).target()[0]
        for item in [fields['proposition']['span'],*fields['voice']['evidence'],*fields['adoption']['evidence']]: validate_span(item,texts)
        self.assertNotIn('kind',fields['voice']);self.assertNotIn('status',fields['adoption']);self.assertTrue(package['partial_binding']);self.assertFalse(package['production_admission'])
        fields['voice']['evidence'][0]['text']='changed'
        self.assertEqual(fields['proposition']['span']['text'],' The gate is open.')

    def test_invalid_roles_sources_inventory_and_status_are_rejected(self):
        value=specimen()
        for kind in ('unknown','duplicate_range','contained','status','missing_context','changed_proposition','missing_id','source_change'):
            bad=output();row=bad['contexts'][0];packet=deepcopy(value)
            if kind=='unknown': row['voice_context_ranges']=[span('foreign')]
            if kind=='duplicate_range': row['voice_context_ranges']*=2
            if kind=='contained': row['voice_context_ranges']=[span('u0001')]
            if kind=='status': row['status']='self_contained'
            if kind=='missing_context': row['voice_context_ranges']=[]
            if kind=='changed_proposition': row['proposition_range']=span('u0000')
            if kind=='missing_id': bad['contexts']=[]
            if kind=='source_change': packet['state']['sources']['w0']['target_digest']='foreign'
            with self.subTest(kind=kind): self.assertTrue(v.inspect(bad,packet)['errors'])
        for status in ('self_contained','unresolved'): self.assertFalse(v.inspect(output(status),value)['errors'])

    def test_request_reuses_unverified_audit_candidates_and_verifier_separates_roles(self):
        packet=specimen();spec=v.requests.RequestSpec(**packet['request']);spec.preflight()
        state=json.loads(spec.body['messages'][1]['content'])
        self.assertEqual(state['items'][0]['fixed_selection'],packet['before']['selections'][0]);self.assertEqual(state['items'][0]['prior_machine_audit'],packet['prior_audits'][0])
        self.assertNotIn('expected',state['items'][0]);self.assertNotIn('voice',v.schema()['properties']['contexts']['items']['properties'])
        verify=v.verification(packet,v.inspect(output(),packet));self.assertEqual(len(verify.body['questions']),2)
        self.assertEqual(verify.body['state']['items'][0]['selected_binding_evidence']['proposition']['span']['text'],' The gate is open.')
        for question in verify.body['questions'].values(): self.assertEqual(question['type'],'noul')

    def test_bounded_retry_explicit_unknown_and_no_replay_calls(self):
        for mode in ('valid','unresolved','retry','failed_twice','timeout'):
            packet=specimen();calls=[]
            def flash(spec):
                calls.append('flash')
                if mode=='timeout': raise OSError('synthetic timeout')
                out=output('unresolved' if mode=='unresolved' else 'context_selected')
                if mode=='failed_twice' or (mode=='retry' and calls.count('flash')==1): out['contexts'][0]['voice_context_ranges']=[span('foreign')]
                return dict(model=v.hosted.FLASH_MODEL,complete=True,usage=dict(input_tokens=100,output_tokens=100),output=json.dumps(out))
            def verify(spec):
                calls.append('typesafe')
                return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),output={key:dict(type='noul',noul=.01 if mode=='unresolved' and key.endswith('sufficiency') else .99) for key in spec.body['questions']})
            with self.subTest(mode=mode),TemporaryDirectory() as folder:
                root=Path(folder);result=v.run_recipe(packet,root,flash,verify)
                self.assertEqual(result['status'],'FAIL(component)' if mode in ('failed_twice','timeout') else 'INCONCLUSIVE')
                self.assertFalse(result['production_admission']);self.assertLessEqual(len(calls),3)
                self.assertEqual(v.run_recipe(packet,root,lambda s:self.fail('replay'),lambda s:self.fail('replay')),result)
                if mode=='valid':
                    proof=json.loads((root/'machine-evidence-proposals.json').read_text());self.assertEqual(proof['origin'],'machine_generated');self.assertTrue(proof['partial_binding'])
                if mode=='retry': self.assertEqual(calls,['flash','flash','typesafe'])
                if mode=='failed_twice': self.assertEqual(calls,['flash','flash'])

    def test_frozen_authorization_budget_and_cli(self):
        with patch.object(v,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            out=CliRunner().invoke(app,['analysis','learning-demo','model-fit','voice-context-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(out.exit_code,0,out.output);self.assertTrue(run.call_args.kwargs['check_only'])
        with TemporaryDirectory() as folder:
            packet=json.loads(json.dumps(specimen()));packet['budget']=dict(reserved_usd='.032243712')
            packet['input_fingerprint']=v.digest({k:x for k,x in packet.items() if k!='input_fingerprint'})
            path=v.directory(Path(folder),packet['input_fingerprint'])/'input.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(packet))
            with patch.object(v,'prepare',return_value=(packet,path.parent)):
                self.assertEqual(v.run(path,Path(folder),check_only=True)['paid_calls'],0);self.assertFalse((path.parent/'execution').exists())
                with self.assertRaises(ValueError): v.run(path,Path(folder))
                for cap in ('.01','.05','NaN'):
                    with self.assertRaises(ValueError): v.run(path,Path(folder),max_usd=cap,check_only=True)
            changed=deepcopy(packet);changed['version']='foreign'
            with patch.object(v,'prepare',return_value=(changed,path.parent)),self.assertRaises(ValueError): v.run(path,Path(folder),check_only=True)
