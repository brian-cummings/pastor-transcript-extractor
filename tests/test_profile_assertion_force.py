from copy import deepcopy
import unittest
from pastor_transcript_extractor import profile_assertion_force as force
from pastor_transcript_extractor import profile_analysis_support as core
from pastor_transcript_extractor import profile_analysis_support_execution as execution
from pastor_transcript_extractor import profile_support_correction as correction
from test_profile_analysis_support import plan


class AssertionForceTests(unittest.TestCase):
    def case(self,statement,declared='local_observation',allowed=None):
        case=deepcopy(plan()['items'][0]['case']);case['state']['candidate']['statement']=statement
        case['state']['candidate']['assertion_contract']=dict(version=force.VERSION,declared_force=declared,
            allowed_forces=allowed or ['local_observation'])
        return case

    def answer(self,case,kind,complete=True):
        return dict(judgment='supported',evidence=[next(iter(core.citation_catalog(case)))],qualifications=[],reason='Synthetic support judgment.',
            assertion_force=dict(complete=complete,assertions=[dict(excerpt=case['state']['candidate']['statement'],force=kind)]))

    def test_stronger_force_is_withheld_even_when_model_supports_underlying_topic(self):
        for statement,kind in [('The valve usually closes.','frequency'),('Pressure causes closure.','causal'),
                ('Closure is more important than ventilation.','comparative_priority'),('Closure dominates the instructions.','dominance')]:
            case=self.case(statement);answer=self.answer(case,kind)
            judgment,errors=correction.inspect(case,execution.requests.wire(answer),execution.schema(case))
            self.assertEqual([],errors)  # Semantic failure is valid; never request another judgment.
            p=plan();p['items']=p['items'][:1];p['items'][0].update(case=case,statement=statement)
            doc=core.document_input(p,[dict(claim_id=p['items'][0]['claim_id'],judgment=judgment)])
            self.assertEqual([],doc['ready_claim_ids']);self.assertEqual('assertion_force_unresolved',doc['entries'][0]['support_status'])

    def test_local_and_warranted_membership_can_pass_but_incomplete_inventory_cannot(self):
        for statement,kind in [('This valve is closed.','local_observation'),('The selected examples include closed and open valves.','sample_membership')]:
            case=self.case(statement,kind,[kind]);value=self.answer(case,kind)
            judgment=core.validate_answer_v2(case,value)
            self.assertEqual('within_authority',judgment['assertion_assessment']['status'])
            value['assertion_force']['complete']=False
            self.assertEqual('unwarranted_or_unresolved',core.validate_answer_v2(case,value)['assertion_assessment']['status'])

    def test_inventory_binds_unchanged_text_and_opt_in_preserves_old_default(self):
        case=self.case('The valve is closed.');value=self.answer(case,'local_observation')
        value['assertion_force']['assertions'][0]['excerpt']='Repaired wording'
        with self.assertRaisesRegex(ValueError,'unchanged'):core.validate_answer_v2(case,value)
        plain=deepcopy(case);del plain['state']['candidate']['assertion_contract']
        old=execution.make_request(plain);new=execution.make_request(case)
        self.assertNotIn('assertion_force',execution.schema(plain)['properties'])
        self.assertNotEqual(old.fingerprint,new.fingerprint);self.assertEqual(old,execution.make_request(plain))
        self.assertEqual('none',new.body['reasoning_effort'])
