from copy import deepcopy
import unittest

from pastor_transcript_extractor import connected_proposition_binding as c


def quote(text,index=0,field='target_text'):
    return dict(source_field=field,text=text,occurrence_index=index)


def proposal(local_id,phrase,frame):
    def finding(value):return dict(value=value,evidence=[quote(phrase)],rationale='Direct wording in the synthetic source.')
    return dict(local_id=local_id,span=quote(phrase),reading=phrase,frame_id=frame,
        adoption=dict(status='own_assertion',basis='own_speech',evidence=[quote(phrase)],rationale='Own actual statement in this synthetic source.'),
        polarity=finding('affirmed'),expression=finding('assertion'),epistemic_status=finding('not_stated'),scope=dict(reading='Local synthetic statement only.',evidence=[quote(phrase)]),conditions=[],evidence_nodes=[],qualifications=[],development_relations=[],address_acts=[],unknowns=['No ministry-wide inference.'])


def fixture():
    text='The maker shaped the land and he formed the sea.'
    source=dict(case_id='control',texts=dict(target_text=text,leading_context='',trailing_context=''))
    frame=dict(frame_id='outer',parent_frame_id=None,span=quote(text),voice='preacher',speaker='preacher',occurrence='actual',evidence=[quote(text)],rationale='Actual synthetic preacher statement.')
    content=dict(frames=[frame],propositions=[proposal('first',text,'outer')],passage_unknowns=['External truth and actual listener status unverified.'])
    return content,source,dict(request_fingerprint='request',case_id='control')


def invitation():
    content,source,prov=fixture();inner='The shepherd will guide me.';outer='Can you say, "'+inner+'"'
    source['texts']['target_text']=outer
    f=content['frames'][0];f.update(span=quote(outer),evidence=[quote(outer)])
    content['frames'].append(dict(frame_id='inner',parent_frame_id='outer',span=quote(inner),voice='quoted_or_reported',speaker='invited listener',occurrence='projected',evidence=[quote(outer)],rationale='Outer invitation offers these words; no actual response.'))
    p=proposal('outer-prop',outer,'outer');p['expression']['value']='question';p['polarity'].update(value='unresolved',evidence=[]);p['adoption'].update(status='undetermined',basis='unresolved',evidence=[])
    child=proposal('inner-prop',inner,'inner');child['adoption'].update(status='adopted',basis='discourse_use',evidence=[quote(outer)],rationale='Affirmative offered-confidence use in the invitation; no actual saving-status assertion.')
    act=dict(type='invitation',frame_id='outer',utterance_span=quote(outer),adoption='own_or_adopted',addressee='direct_current_listener',addressee_evidence=[quote(outer)],link_evidence=[quote(outer)],rationale='Actual preacher act linked to the projected content.')
    p['address_acts']=[deepcopy(act)];child['address_acts']=[deepcopy(act)]
    content['propositions']=[p,child]
    return content,source,prov


class ConnectedCompilerTests(unittest.TestCase):
    def test_compound_is_not_rejected_by_a_candidate_boundary_gate(self):
        args=fixture();before=deepcopy(args);result=c.compile_passage(*args)
        self.assertEqual(before,args);b=result['generated'][0]['binding'];self.assertIsNotNone(b)
        self.assertEqual(args[1]['texts']['target_text'],b['proposition']['span']['text'])
        self.assertTrue(b['automatic_binding']);self.assertFalse(b['accepted_observation'])
        self.assertNotIn('subject_id',b)

    def test_outer_actual_question_and_inner_projected_declaration_keep_independent_use(self):
        result=c.compile_passage(*invitation());outer,inner=[x['binding'] for x in result['generated']]
        self.assertEqual('actual',outer['voice']['occurrence']);self.assertEqual('projected',inner['voice']['occurrence'])
        self.assertEqual('undetermined',outer['adoption']['status']);self.assertEqual('adopted',inner['adoption']['status'])
        self.assertEqual('own_or_adopted',inner['address_acts'][0]['adoption'])
        self.assertEqual('preacher',inner['address_acts'][0]['voice']);self.assertEqual('not_stated',outer['epistemic_status']['value'])
        self.assertEqual('outer',result['frames'][1]['parent_frame_id'])

    def test_quotes_are_exact_and_repetitions_require_correct_occurrence(self):
        texts=dict(target_text='He spoke. He spoke.',leading_context='',trailing_context='')
        self.assertEqual(10,c.locate(quote('He spoke.',1),texts)['start'])
        for q in (quote('he spoke.'),quote('He  spoke.'),quote('He spoke.',2)):
            with self.assertRaises(ValueError):c.locate(q,texts)
        with self.assertRaises(ValueError):c.locate(quote('He spoke.',True),texts)

    def test_malformed_literal_is_rejected_and_retained_without_repair(self):
        content,source,prov=fixture();content['propositions'][0]['span']['text']='Invented teaching.'
        out=c.compile_passage(content,source,prov)['generated'][0]
        self.assertIsNone(out['binding']);self.assertIn('not present',out['compile_error'])
        self.assertEqual('Invented teaching.',out['raw_proposition']['span']['text'])

    def test_context_cannot_supply_proposition_or_adoption(self):
        for field in ('span','adoption'):
            content,source,prov=fixture();source['texts']['leading_context']=source['texts']['target_text']
            q=content['propositions'][0]['span'] if field=='span' else content['propositions'][0]['adoption']['evidence'][0]
            q['source_field']='leading_context'
            out=c.compile_passage(content,source,prov)['generated'][0]
            self.assertIsNone(out['binding']);self.assertIn('context',out['compile_error'])

    def test_cyclic_missing_and_noncontaining_frames_fail_visibly(self):
        for mutation in ('cycle','missing','outside','unparented'):
            content,source,prov=invitation()
            if mutation=='cycle':content['frames'][0]['parent_frame_id']='inner'
            if mutation=='missing':content['frames'][1]['parent_frame_id']='absent'
            if mutation=='outside':content['frames'][0]['span']=quote('Can you say,')
            if mutation=='unparented':content['frames'][1]['parent_frame_id']=None
            result=c.compile_passage(content,source,prov);self.assertTrue(result['compile_error']);self.assertFalse(result['generated'])

    def test_quote_alone_and_projected_own_assertion_cannot_be_promoted(self):
        for mutation in ('quotation','own'):
            content,source,prov=invitation();p=content['propositions'][1]
            if mutation=='quotation':p['adoption']['evidence']=[deepcopy(p['span'])]
            else:p['adoption'].update(status='own_assertion',basis='own_speech')
            result=c.compile_passage(content,source,prov)['generated'][1]
            self.assertIsNone(result['binding']);self.assertTrue(result['compile_error'])

    def test_inner_projected_frame_cannot_perform_current_listener_address(self):
        content,source,prov=invitation();p=content['propositions'][1]
        p['address_acts'][0].update(frame_id='inner',utterance_span=deepcopy(p['span']))
        result=c.compile_passage(content,source,prov)['generated'][1]
        self.assertIsNone(result['binding']);self.assertIn('actual preacher',result['compile_error'])

    def test_qualifications_and_links_keep_existing_meanings_and_grounded_endpoints(self):
        content,source,prov=fixture();p=content['propositions'][0];s=source['texts']['target_text']
        p['evidence_nodes']=[dict(node_id='reason',span=quote('he formed the sea.'),role='reason',voice='preacher',adoption='own_assertion'),dict(node_id='qual',span=quote('the land'),role='qualification',voice='preacher',adoption='own_assertion')]
        p['qualifications']=[dict(node_id='qual',reading='Synthetic attachment only, not a new condition meaning.')]
        p['development_relations']=[dict(kind='reason_supports_claim',from_node='reason',to_node='claim',evidence=[quote(s)],voice='preacher',adoption='own_assertion',scope='Synthetic local relation only.',stated_qualifications=[],status='supported_observation',unresolved_reason=None,rationale='Fixture tests grounded relation transport, not semantic correctness.')]
        good=c.compile_passage(content,source,prov)['generated'][0]['binding'];self.assertEqual([],good['conditions']);self.assertEqual('claim',good['qualifications'][0]['applies_to'])
        p['development_relations'][0]['from_node']='not-present'
        self.assertIsNone(c.compile_passage(content,source,prov)['generated'][0]['binding'])

    def test_rejected_content_does_not_generate_an_opposite_and_schema_is_closed(self):
        content,source,prov=fixture();p=content['propositions'][0]
        p['adoption'].update(status='rejected',basis='explicit_rejection')
        b=c.compile_passage(content,source,prov)['generated'][0]['binding']
        self.assertEqual('affirmed',b['polarity']['value']);self.assertEqual('rejected',b['adoption']['status'])
        content['accepted_observation']=True
        self.assertIsNotNone(c.compile_passage(content,source,prov)['compile_error'])
