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
            assertion_force=dict(candidate_id=case['state']['candidate']['id'],complete=complete,forces=[kind],
                measurement_entitlement='within_meaning',reason='Matches the supplied local relationship meaning.'))

    def test_disjunctive_meaning_cannot_be_promoted_by_a_supported_source_judgment(self):
        from pastor_transcript_extractor import profile_support_regression as regression
        case=regression.case(dict(id='indicator',candidate='The indicator is red and blue.',scope='This indicator.',source='The indicator is blue.'))
        case['state']['candidate']['assertion_contract']=dict(version=force.VERSION,declared_force='local_observation',allowed_forces=['local_observation'])
        case['state']['measurement_ledger']['contracts']=[dict(meaning='The indicator is red or blue.')]
        value=self.answer(case,'local_observation');item=value['assertion_force']
        item.update(measurement_entitlement='requires_missing_distinction',reason='The observed alternative does not establish both colors.')
        before=deepcopy(value);judgment,errors=correction.inspect(case,execution.requests.wire(value),execution.schema(case))
        self.assertEqual([],errors);self.assertEqual(before,value)
        self.assertEqual('unwarranted_or_unresolved',judgment['assertion_assessment']['status'])
        value['assertion_force']['measurement_entitlement']='unresolved'
        self.assertEqual([],correction.inspect(case,execution.requests.wire(value),execution.schema(case))[1])

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
        value['assertion_force']['candidate_id']='another-candidate'
        with self.assertRaisesRegex(ValueError,'inventory'):core.validate_answer_v2(case,value)
        plain=deepcopy(case);del plain['state']['candidate']['assertion_contract']
        old=execution.make_request(plain);new=execution.make_request(case)
        self.assertNotIn('assertion_force',execution.schema(plain)['properties'])
        self.assertNotEqual(old.fingerprint,new.fingerprint);self.assertEqual(old,execution.make_request(plain))
        self.assertEqual('none',new.body['reasoning_effort'])

    def test_compact_inventory_retains_stronger_force_and_long_candidate_without_copying_it(self):
        case=self.case('This valve is closed. '+('A supplied explanation remains part of the candidate. '*20))
        value=self.answer(case,'local_observation')
        self.assertNotIn(case['state']['candidate']['statement'],execution.requests.wire(value))
        self.assertEqual('within_authority',core.validate_answer_v2(case,value)['assertion_assessment']['status'])
        value['assertion_force']['forces'].append('frequency')
        self.assertEqual('unwarranted_or_unresolved',core.validate_answer_v2(case,value)['assertion_assessment']['status'])
