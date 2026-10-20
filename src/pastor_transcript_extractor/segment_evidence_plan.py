"""Read-only current planning/retirement registry; never inference."""
from pastor_transcript_extractor import evidence_pipeline_trace as trace

HERE=trace.ROOT/'docs/review-proposals/pastor-profile-implementation-plan-v1'
OLD_SELECTION_INPUT='19a1137161528d5c4eec95242148f05abb155b2fe710d2a0d59846cceabaa8a2'


def verify():
    plan=trace.read(HERE/'plan-v13.json',True)
    if (plan['version']!='pastor-profile-product-and-implementation-status-v13'
            or plan['analytical_families']!=['preaching_style','theological_emphasis','theological_orientation','pastoral_rhetorical_orientation']
            or any(plan[k] for k in ('model_probability_is_pastor_score','benchmark_percentages_authorized','single_pastor_score_proposed','draft_is_measurement_ground_truth'))
            or plan['high_labels_require_explicit_rules'] is not True
            or plan['status']!='AUTOMATIC_BINDING_V2_EXECUTED_COMPARED_STOP_MENU_TUNING' or plan['exact_span_extraction_required_upstream'] is not False
            or plan['pipeline_order']!=['existing_segment_observations','supported_evidence_accumulation','bounded_profile_review','strongest_supporting_segment','optional_Ollama_illustrative_quote']
            or plan['quote_context']!=['preceding_segment','center_segment','following_segment']
            or plan['quote_anchor']!='substantive_content_in_center'
            or plan['topic_presence_implies_position'] is not False
            or plan['quotes_change_measurements'] is not False
            or any(plan[k] for k in ('provider_execution','new_collection','new_projection_scoring','quote_implementation'))):
        raise ValueError('Current segment/quotation planning scope differs')
    development=plan['binding_development']
    if (development['passages']!=3 or development['development_references']!=10
            or not development['semantic_comparison_complete'] or development['reference_visible_to_generation']
            or any(development[k] for k in ('broader_collection','production_activation','automatic_acceptance','profile_projection'))):
        raise ValueError('Bounded automatic development scope differs')
    revision=plan['binding_revision']
    if (revision['passages']!=3 or revision['development_references']!=10
            or revision['status']!='EXECUTED_COMPARED_STOP_MENU_TUNING' or revision['executor']!='Brian'
            or revision['live_provider_requests']!=39 or revision['review_provider_requests']!=0 or revision['min_probability']!=.8
            or not revision['live_results_available'] or not revision['semantic_comparison_complete']
            or any(revision[k] for k in ('reference_visible_to_generation','broader_collection','production_activation','automatic_acceptance','profile_projection','backend_comparison','ollama_execution','proposed_architecture_executed'))):
        raise ValueError('Completed same-case V2 development scope differs')
    path=trace.ROOT/plan['plan_path']
    if trace.digest(path)!=plan['plan_sha256']:raise ValueError('Current plan text differs')
    implementation=trace.ROOT/plan['implementation_path']
    if trace.digest(implementation)!=plan['implementation_sha256']:
        raise ValueError('Current implementation plan text differs')
    if implementation.name not in path.read_text() or path.name not in implementation.read_text():
        raise ValueError('Product and implementation plans must reference each other')
    manifest=trace.ROOT/plan['archive_manifest_path']
    if trace.digest(manifest)!=plan['archive_manifest_sha256']:
        raise ValueError('Planning archive manifest differs')
    for row in trace.read(manifest,True)['archives']:
        if trace.digest(trace.ROOT/row['archive_path'])!=row['original_sha256'] or row['archive_sha256']!=row['original_sha256']:
            raise ValueError('Historical planning document differs')
    return plan,path


def reject_closed_selection(approved):
    if approved==OLD_SELECTION_INPUT:
        verify()
        raise ValueError('Exact-span selection is retired. Use segment evidence first; illustrative Ollama quotes belong at the tail. No provider client opened.')
