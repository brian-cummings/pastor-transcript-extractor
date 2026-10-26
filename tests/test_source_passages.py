from copy import deepcopy
from dataclasses import replace,asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typer.testing import CliRunner
from pastor_transcript_extractor import source_passages as p
from pastor_transcript_extractor import passage_selection_check as c
from pastor_transcript_extractor.binding_evidence import validate_span
from pastor_transcript_extractor.cli import app
from test_source_context import fixture


def window_with(*texts):
    window,_,_=fixture();blocks=[]
    for i,text in enumerate(texts):
        block=deepcopy(window.blocks[0]);block.update(block_id=i,target_text=text);blocks.append(block)
    return replace(window,blocks=tuple(blocks))


def packet():
    window,_,reading=fixture();source_state,windows=c.state([dict(window=asdict(window),reading=reading)])
    spec=c.reader_request(source_state)
    return dict(input_fingerprint='synthetic',request=asdict(spec),state=source_state,windows={k:asdict(v) for k,v in windows.items()},
        history=dict(prior_accounting=dict(cumulative_attempts=91,cumulative_local_attempts=28,cumulative_paid_attempts=63,cumulative_known_list_price_usage_usd='.354660876')))


def selected(source_state,status='selected'):
    rows=[]
    for item in source_state['items']:
        units=source_state['sources'][item['source_id']]['units']
        rows.append(dict(item_id=item['item_id'],status=status,proposition_range=dict(start_unit=units[0]['id'] if status=='selected' else '',end_unit=units[-1]['id'] if status=='selected' else ''),adoption_ranges=[]))
    return dict(selections=rows)


class SourcePassageTests(unittest.TestCase):
    def test_lossless_deterministic_unicode_and_punctuation_free_units(self):
        for text in ('Écho.  Écho!\nIf yes, then go?',' '.join('word'+str(i) for i in range(137)),'  \n ',''):
            w=window_with(text);units=p.inventory(w)['units']
            self.assertEqual(p.inventory(w),p.inventory(w));self.assertEqual(''.join(u['text'] for u in units),text)
            self.assertEqual(len({u['id'] for u in units}),len(units))
            for u in units:
                self.assertEqual(text[u['start']:u['end']],u['text']);self.assertLessEqual(len(u['text'].split()),40)
            for left,right in zip(units,units[1:]): self.assertEqual(left['end'],right['start'])

    def test_repeated_text_has_distinct_coordinates_and_cross_block_provenance(self):
        w=window_with('Same. Same.',' If rain, stay.');units=p.inventory(w)['units']
        first=p.resolve(w,dict(start_unit=units[0]['id'],end_unit=units[0]['id']))
        second=p.resolve(w,dict(start_unit=units[1]['id'],end_unit=units[1]['id']))
        self.assertNotEqual(first['span']['start'],second['span']['start'])
        joined=p.resolve(w,dict(start_unit=units[0]['id'],end_unit=units[-1]['id']))
        self.assertEqual(joined['span']['text'],w.target()[0]['target_text']);self.assertEqual(len(joined['source_refs']),2)
        validate_span(joined['span'],w.target()[0])
        self.assertIn('pending',joined['semantic_validation'])
        for selection in (dict(start_unit='x',end_unit='u0000'),dict(start_unit=units[-1]['id'],end_unit=units[0]['id']),dict(start_unit=0,end_unit=0),dict(start_unit='u0000',end_unit='u0000',text='invented')):
            with self.assertRaises(ValueError): p.resolve(w,selection)
        blank=window_with(' ')
        with self.assertRaises(ValueError): p.resolve(blank,dict(start_unit='u0000',end_unit='u0000'))

    def test_selection_schema_inventory_abstention_and_window_guards(self):
        value=packet();windows={k:c.SourceWindow(**v) for k,v in value['windows'].items()};good=selected(value['state']);before=deepcopy(value)
        checked=c.inspect(good,value['state'],windows);self.assertFalse(checked['errors']);self.assertEqual(value,before)
        for kind in ('missing','duplicate','extra_quote','reversed','foreign','false_abstention'):
            bad=deepcopy(good)
            if kind=='missing': bad['selections'].pop()
            if kind=='duplicate': bad['selections'].append(deepcopy(bad['selections'][0]))
            if kind=='extra_quote': bad['selections'][0]['text']='invented'
            if kind=='reversed': bad['selections'][0]['proposition_range']={k:v for k,v in zip(('end_unit','start_unit'),bad['selections'][0]['proposition_range'].values())}
            if kind=='foreign': bad['selections'][0]['proposition_range']['end_unit']='foreign'
            if kind=='false_abstention': bad['selections'][0]['status']='no_adequate_passage'
            with self.subTest(kind=kind): self.assertTrue(c.inspect(bad,value['state'],windows)['errors'])
        abstain=selected(value['state'],'no_adequate_passage');self.assertFalse(c.inspect(abstain,value['state'],windows)['errors']);self.assertIsNone(c.verification(value['state'],abstain))
        changed=deepcopy(value['state']);next(iter(changed['sources'].values()))['target_digest']='foreign'
        with self.assertRaises(ValueError): c.inspect(good,changed,windows)

    def test_stubbed_executor_separates_semantics_and_bounded_mechanical_retry(self):
        for mode in ('pass','uncertain','fail','bad_ids','retry_recovers','abstain','timeout'):
            value=packet();calls=[]
            def flash(spec):
                calls.append('flash')
                if mode=='timeout': raise OSError('timeout')
                out=selected(value['state'],'no_adequate_passage' if mode=='abstain' else 'selected')
                if mode=='bad_ids' or (mode=='retry_recovers' and calls.count('flash')==1): out['selections'][0]['proposition_range']['start_unit']='absent'
                return dict(model=c.hosted.FLASH_MODEL,complete=True,usage=dict(input_tokens=100,output_tokens=100),output=json.dumps(out))
            def verifier(spec):
                calls.append('typesafe');p={'pass':.99,'uncertain':.5,'fail':.01}.get(mode,.99)
                return dict(model='jev-1.13.0',complete=True,usage=dict(input_tokens=100,output_tokens=100),output={key:dict(type='noul',noul=p) for key in spec.body['questions']})
            with self.subTest(mode=mode),TemporaryDirectory() as folder:
                root=Path(folder);result=c.run_recipe(value,root,flash,verifier)
                self.assertFalse(result['production_admission']);self.assertLessEqual(len(calls),3)
                self.assertEqual(result['status'],'FAIL(component)' if mode in ('fail','bad_ids','timeout') else 'INCONCLUSIVE')
                self.assertEqual(c.run_recipe(value,root,lambda s:self.fail('no repeat'),lambda s:self.fail('no repeat')),result)
                if mode=='bad_ids': self.assertEqual(calls,['flash','flash'])
                elif mode=='retry_recovers':
                    self.assertEqual(calls,['flash','flash','typesafe']);self.assertEqual(result['mechanical_retries'],1)
                    retry=json.loads((root/'range-retry-request.json').read_text())
                    self.assertIn('Unknown source unit ID',retry['body']['messages'][-1]['content'])
                    self.assertIn('absent',retry['body']['messages'][-2]['content'])
                elif mode in ('abstain','timeout'): self.assertEqual(calls,['flash'])
                else: self.assertEqual(calls,['flash','typesafe'])
                self.assertEqual(result['accounting']['cumulative_paid_attempts'],63+len(calls))

    def test_request_has_only_proposals_and_id_output_schema(self):
        value=packet();spec=c.requests.RequestSpec(**value['request']);body=json.loads(spec.body['messages'][1]['content'])
        self.assertEqual(body,value['state']);self.assertEqual(spec.body['model'],c.hosted.FLASH_MODEL)
        self.assertEqual(spec.body['reasoning_effort'],'none')
        self.assertNotIn('voice',c.schema()['properties']['selections']['items']['properties'])
        verify=c.verification(value['state'],selected(value['state']));verify.preflight()
        self.assertEqual(len(verify.body['questions']),6)
        for q in verify.body['questions'].values(): self.assertEqual(q['type'],'noul')

    def test_cli_frozen_approval_budget_and_no_execution_preflight(self):
        with patch.object(c,'run',return_value=dict(status='PREPARED_NO_EXECUTION')) as run:
            result=CliRunner().invoke(app,['analysis','learning-demo','model-fit','passage-selection-run','--input','/tmp/input.json','--check-only','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertTrue(run.call_args.kwargs['check_only'])
        with TemporaryDirectory() as folder:
            value=json.loads(json.dumps(packet()));value['budget']=dict(reserved_usd='.032243712');value['input_fingerprint']=c.digest({k:v for k,v in value.items() if k!='input_fingerprint'})
            path=c.directory(Path(folder),value['input_fingerprint'])/'input.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(value))
            with patch.object(c,'prepare',return_value=(value,path.parent)):
                self.assertEqual(c.run(path,Path(folder),check_only=True)['paid_calls'],0);self.assertFalse((path.parent/'execution').exists())
                with self.assertRaises(ValueError): c.run(path,Path(folder))
                for cap in ('0.001','.03','.05','NaN'):
                    with self.assertRaises(ValueError): c.run(path,Path(folder),max_usd=cap,check_only=True)
