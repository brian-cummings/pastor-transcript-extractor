"""Read-only current planning/retirement registry; never inference."""
from pastor_transcript_extractor import evidence_pipeline_trace as trace

HERE=trace.ROOT/'docs/review-proposals/pastor-profile-product-plan-v2'
OLD_SELECTION_INPUT='19a1137161528d5c4eec95242148f05abb155b2fe710d2a0d59846cceabaa8a2'


def verify():
    plan=trace.read(HERE/'plan-v2.json',True)
    if (plan['version']!='pastor-profile-product-plan-v2'
            or plan['analytical_families']!=['preaching_style','theological_emphasis','theological_orientation','pastoral_rhetorical_orientation']
            or any(plan[k] for k in ('model_probability_is_pastor_score','benchmark_percentages_authorized','single_pastor_score_proposed','draft_is_measurement_ground_truth'))
            or plan['high_labels_require_explicit_rules'] is not True
            or plan['status']!='ACTIVE_PLAN_NO_EXECUTION' or plan['exact_span_extraction_required_upstream'] is not False
            or plan['pipeline_order']!=['existing_segment_observations','supported_evidence_accumulation','bounded_profile_review','strongest_supporting_segment','optional_Ollama_illustrative_quote']
            or plan['quote_context']!=['preceding_segment','center_segment','following_segment']
            or plan['quote_anchor']!='substantive_content_in_center'
            or plan['topic_presence_implies_position'] is not False
            or plan['quotes_change_measurements'] is not False
            or any(plan[k] for k in ('provider_execution','new_collection','new_projection_scoring','quote_implementation'))):
        raise ValueError('Current segment/quotation planning scope differs')
    path=trace.ROOT/plan['plan_path']
    if trace.digest(path)!=plan['plan_sha256']:raise ValueError('Current plan text differs')
    return plan,path


def reject_closed_selection(approved):
    if approved==OLD_SELECTION_INPUT:
        verify()
        raise ValueError('Exact-span selection is retired. Use segment evidence first; illustrative Ollama quotes belong at the tail. No provider client opened.')
