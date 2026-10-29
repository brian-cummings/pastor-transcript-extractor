from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
from pastor_transcript_extractor import profile_support_validation as v
from pastor_transcript_extractor import profile_analysis_support_execution as x
from test_profile_analysis_support import plan,answer
from test_profile_analysis_support_execution import wire


def saved(folder):
    root=Path(folder)/'old';root.mkdir();profile=Path(folder)/'profile.json';profile.write_text('{}')
    p=plan();original=deepcopy(p['items'][0]);p['items']=[];tasks=[];rows=[]
    for index,category in enumerate(v.CATEGORIES):
        item=deepcopy(original);cid=f'case-{index}';item['claim_id']=cid;item['case']['state']['candidate']['id']=cid
        item['case']['state']['candidate']['analytical_basis']='source_reviewed_style_example'
        item['case']['dependencies']=[];p['items'].append(item);spec=x.make_request(item['case'])
        tasks.append(dict(claim_id=cid,request=asdict(spec)))
        a=answer()
        if category=='citation_binding':a['evidence'][0]['end_unit']='missing'
        if category=='qualification_preservation':a['qualifications']=[dict(reading='Local example only.',evidence=a['evidence'])]
        if category=='unresolved_path':a['judgment']='unresolved'
        raw=wire(spec,json.dumps(a))
        if category=='whitespace_recovery':
            body=json.loads(raw.text);body['choices'][0]['message']['content']='{"value":'+' '*300;body['choices'][0]['finish_reason']='length';raw=x.requests.WireResponse(200,json.dumps(body))
        store=x.requests.ReceiptStore(Path(folder)/cid/'execution')
        try:x.requests.execute(spec,x.provider.OneRequestLedger(str(x.requests.request_reservation(spec)),spec.version),store,lambda s:raw)
        except ValueError:pass
        failure='Incomplete DeepInfra response' if index==0 else 'Invalid binding' if index==1 else None
        rows.append(dict(claim_id=cid,status='component_failure' if failure else 'complete',failure=failure,judgment=None,receipt=str(store.root/'receipts'/f'{spec.fingerprint}.json')))
    packet=dict(plan=p,tasks=tasks,profile_input=dict(path=str(profile),sha256=v.file_hash(profile)))
    packet['input_fingerprint']=v.digest(packet);(root/'input.json').write_text(json.dumps(packet))
    (root/'results.json').write_text(json.dumps(dict(input_fingerprint=packet['input_fingerprint'],results=rows)))
    return root,p,profile


class BoundedValidationTests(unittest.TestCase):
    def test_selection_is_exact_auditable_and_has_no_authored_answers(self):
        with TemporaryDirectory() as folder:
            root,p,profile=saved(folder);before=v.file_hash(root/'results.json')
            chosen,lineage=v.select(root,p,profile)
            self.assertEqual([r['category'] for r in lineage['selection']],list(v.CATEGORIES))
            self.assertEqual(chosen['items'],p['items']);self.assertEqual(chosen['selection']['assembled_total'],4)
            self.assertEqual(len(lineage['preserved_files']),10)
            self.assertNotIn('expected',json.dumps(chosen));self.assertEqual(v.file_hash(root/'results.json'),before)
            changed=deepcopy(p);changed['items'][0]['statement']='Changed'
            with self.assertRaisesRegex(ValueError,'changed'):v.select(root,changed,profile)
            profile.write_text('changed')
            with self.assertRaisesRegex(ValueError,'identical'):v.select(root,p,profile)

    def test_tampering_and_missing_categories_fail_before_generation(self):
        with TemporaryDirectory() as folder:
            root,p,profile=saved(folder);report=json.loads((root/'results.json').read_text());report['results']=report['results'][:3];(root/'results.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'No saved case'):v.select(root,p,profile)
        with TemporaryDirectory() as folder:
            root,p,profile=saved(folder);report=json.loads((root/'results.json').read_text());receipt=Path(report['results'][0]['receipt']);value=json.loads(receipt.read_text());value['wire_response_digest']='wrong';receipt.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'digest'):v.select(root,p,profile)

    def test_missing_unselected_dependencies_remain_withheld(self):
        p=plan();p['selection']=dict(mode='bounded_contract_validation',assembled_total=2);p['items']=p['items'][1:]
        item=p['items'][0];rows=[dict(claim_id=item['claim_id'],status='complete',judgment=x.core.validate_answer(item['case'],answer()))]
        doc=x.core.document_input(p,rows)
        self.assertEqual(doc['ready_claim_ids'],[]);self.assertEqual(doc['entries'][0]['support_status'],'dependency_unresolved')
        self.assertIn('1 of 2',x.core.render_handoff(doc))

    def test_cli_selection_option_and_frozen_budget(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        with patch.object(x,'prepare',return_value=({'plan':{},'tasks':[]},Path('/tmp/frozen'))) as prepare,patch.object(x,'summary',return_value=dict(status='FROZEN_NO_EXECUTION')):
            result=CliRunner().invoke(app,['analysis','profile-support','prepare','--validation-from','/tmp/old','--json'])
            self.assertEqual(result.exit_code,0,result.output);self.assertEqual(prepare.call_args.kwargs['validation_from'],Path('/tmp/old'))

    def test_validation_ceiling_cannot_be_raised_by_run_option(self):
        from test_profile_analysis_support_execution import packet
        with TemporaryDirectory() as folder:
            value,out=packet(folder);value['budget']['max_usd']='.12';value['input_fingerprint']=x.digest({k:v for k,v in value.items() if k!='input_fingerprint'})
            out.mkdir();path=out/'input.json';path.write_text(json.dumps(value))
            with patch.object(x,'prepare',return_value=(value,out)):
                with self.assertRaisesRegex(ValueError,'frozen run ceiling'):x.run(path,folder,check_only=True,max_usd='.55')
                self.assertEqual(x.run(path,folder,check_only=True,max_usd='.12')['status'],'CHECKED_NO_EXECUTION')
