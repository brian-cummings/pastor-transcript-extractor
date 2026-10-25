from copy import deepcopy
import unittest
from pastor_transcript_extractor.pastor_evidence import SampleSpec, EvidenceView, compile_machine_binding, REQUIRED_CHECKS
from pastor_transcript_extractor.pastor_fingerprint import build_fingerprint, qualified_key
from pastor_transcript_extractor.pastor_similarity import compare_fingerprints, ComparisonSpec, compare_panel
import test_pastor_evidence as evidence_fixture
from test_theological_binding import fixture


def observation(polarity='affirmed', conditions=(), video_id=2, adopted=True):
    text,row,_ = fixture()
    row['polarity']['value'] = polarity
    if not adopted:
        row['voice'].update(kind='quoted_or_reported',speaker='reported person')
        row['adoption'].update(status='reported_not_adopted',basis='quotation_only')
    window = evidence_fixture.EvidenceTests().window(text['target_text'])
    from dataclasses import replace
    window = replace(window, video_id=video_id)
    result = compile_machine_binding(window,row,model='fake',prompt_digest='p',raw_response_ref='fake',
        field_judgments={k:dict(resolved=True,probability=.95) for k in REQUIRED_CHECKS})
    result['alignment'] = dict(meaning=dict(proposition='creation',referents=['God','world'],
        modality='assertion',quantifiers=[],conditions=list(conditions),exceptions=[],temporal_scope='unspecified',scope='local'),
        paths=['theology/creation','theology/other'], resolved=True, probability=.95,evidence=[result['id']])
    return result


def measured(value, video_id=2, op='emphasis'):
    return dict(id='topic',operator=op,estimand='normalized_expected_prominence' if op=='emphasis' else 'assessed_binary',
        contract='pinned',video_id=video_id,value=value,paths=['theology/creation','theology/other'],
        assessed=True,denominator=1,unit='matched_endpoints',exposure='declared_window',source_refs=['synthetic'])


def fingerprint(rows=(), measurements=(), video_ids=(2,)):
    return build_fingerprint(SampleSpec(1,video_ids,'m'),EvidenceView(tuple(rows)),measurements=measurements)


class FingerprintTests(unittest.TestCase):
    def test_position_fraction_masks_bounds_and_both(self):
        a,b = observation(),observation('denied')
        left,right = fingerprint([a]),fingerprint([b])
        out = compare_fingerprints(left,right)
        self.assertEqual(out['position_metrics']['opposition'],1)
        self.assertEqual(out,compare_fingerprints(left,right))
        self.assertEqual(out['position_metrics']['agreement'],compare_fingerprints(right,left)['position_metrics']['agreement'])
        both = compare_fingerprints(fingerprint([a,b]),right)['position_metrics']
        self.assertIsNone(both['agreement']); self.assertEqual(both['coverage'],0)
        self.assertEqual(both['requested_denominator'],1)

    def test_null_unknown_and_conditions_not_erased(self):
        a,b=observation(),observation(conditions=['if trust'])
        result=compare_fingerprints(fingerprint([a]),fingerprint([b]))['position_metrics']
        self.assertEqual(result['requested_denominator'],2)
        self.assertIsNone(result['opposition'])
        self.assertIsNone(compare_fingerprints(fingerprint(),fingerprint())['position_metrics']['coverage'])
        result=compare_fingerprints(fingerprint([observation(adopted=False)]),fingerprint([a]))
        self.assertIsNone(result['position_metrics']['agreement'])

    def test_parent_deduplication_and_two_axes(self):
        a,b=observation(),observation('denied')
        left=fingerprint([a],[measured(.2)])
        same=fingerprint([a],[measured(.8)])
        changed=fingerprint([b],[measured(.2)])
        result=compare_fingerprints(left,same)
        self.assertEqual(result['position_metrics']['agreement'],1)
        self.assertAlmostEqual(result['emphasis_metrics']['resemblance'],.4)
        self.assertEqual(result['position_metrics']['denominator'],1)
        result=compare_fingerprints(left,changed)
        self.assertEqual(result['position_metrics']['opposition'],1)
        self.assertEqual(result['emphasis_metrics']['resemblance'],1)
        child=compare_fingerprints(left,changed,ComparisonSpec(path='theology/creation'))
        self.assertEqual(child['position_metrics']['agreement'],result['position_metrics']['agreement'])
        self.assertEqual(compare_panel(left,[changed],ComparisonSpec())['comparisons'][0],result)

    def test_reordering_idempotent_equal_sermon_mean(self):
        a,b=observation(video_id=2),observation(video_id=3)
        x=fingerprint([a,b],[measured(.2,2),measured(.8,3)],(2,3))
        y=fingerprint([b,a],[measured(.8,3),measured(.2,2)],(2,3))
        self.assertEqual(x,y)
        self.assertEqual(x['features']['emphasis']['topic']['value'],.5)
        self.assertEqual(fingerprint([a]),fingerprint([a,a]))

    def test_assessed_absent_is_zero_uninspected_is_unknown(self):
        a=fingerprint(measurements=[measured(0,op='relation')])
        b=fingerprint(measurements=[measured(1,op='relation')])
        self.assertEqual(compare_fingerprints(a,b)['relation_metrics']['resemblance'],0)
        self.assertIsNone(compare_fingerprints(a,fingerprint())['relation_metrics']['resemblance'])
        invalid=measured(.3,op='relation'); invalid['assessed']=False
        with self.assertRaises(ValueError): fingerprint(measurements=[invalid])

    def test_exact_fractions_and_unknown_changes_only_coverage(self):
        from pastor_transcript_extractor.pastor_evidence import observation_identity
        def row(label,denied=False):
            r=observation('denied' if denied else 'affirmed')
            r['binding']['binding_id']=label
            r['id']=observation_identity(r)
            r['alignment']['meaning']['proposition']=label
            r['alignment']['evidence']=[r['id']]
            return r
        left=fingerprint([row(k) for k in 'abcd'])
        right=fingerprint([row('a'),row('b'),row('c',True),row('e')])
        metrics=compare_fingerprints(left,right)['position_metrics']
        self.assertEqual(metrics['agreement'],2/3)
        self.assertEqual(metrics['opposition'],1/3)
        self.assertEqual(metrics['coverage'],3/5)
        self.assertEqual(len(metrics['feature_contributions']),3)

    def test_same_kernel_accepts_admissible_policy_fixture(self):
        from pastor_transcript_extractor.pastor_evidence import EvidencePolicy, observation_identity
        original=observation()
        policy=EvidencePolicy(namespace='fixture',require_production_admission=True,version='test-only-admissible')
        rejected=build_fingerprint(SampleSpec(1,(2,),'m'),EvidenceView((original,),policy))
        self.assertEqual(next(iter(rejected['claim_frames'].values()))['state'],[0,0])
        admitted=deepcopy(original)
        admitted.update(origin='admitted_policy_fixture',namespace='fixture',production_admission='admitted')
        admitted['id']=observation_identity(admitted)
        admitted['alignment']['evidence']=[admitted['id']]
        fp=build_fingerprint(SampleSpec(1,(2,),'m'),EvidenceView((admitted,),policy))
        self.assertEqual(compare_fingerprints(fp,fp)['position_metrics']['agreement'],1)

    def test_emphasis_estimands_not_mixed(self):
        from pastor_transcript_extractor.pastor_fingerprint import topic_measurements
        rows=list(topic_measurements(2,{'t':dict(normalized_expected_prominence=.2,
            developed_emphasis_probability=.8)},'pinned',[]))
        other=list(topic_measurements(2,{'t':dict(normalized_expected_prominence=.2,
            developed_emphasis_probability=.1)},'pinned',[]))
        result=compare_fingerprints(fingerprint(measurements=rows),fingerprint(measurements=other),
            ComparisonSpec(path='theological_emphasis'))
        self.assertEqual(result['emphasis_metrics']['resemblance'],1)
        self.assertEqual(result['emphasis_metrics']['denominator'],1)
