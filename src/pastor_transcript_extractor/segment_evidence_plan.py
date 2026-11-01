"""Read-only current product status; no planning archives or inference."""
from pastor_transcript_extractor import evidence_pipeline_trace as trace

STATUS_PATH=trace.ROOT/'docs/PROFILE_STATUS.json'
OLD_SELECTION_INPUT='19a1137161528d5c4eec95242148f05abb155b2fe710d2a0d59846cceabaa8a2'


def verify():
    plan=trace.read(STATUS_PATH,True)
    if (plan['version']!='pastor-profile-current-status-v1'
            or plan['status']!='AUTOMATIC_ANALYSIS_PARTIAL_DIMENSIONAL_BENCHMARK_GOAL_NOT_ACHIEVED'
            or plan['analytical_families']!=['preaching_style','theological_emphasis','theological_orientation','pastoral_rhetorical_orientation']
            or any(plan[k] for k in ('model_probability_is_pastor_score','benchmark_percentages_authorized',
                'single_pastor_score_proposed','draft_is_measurement_ground_truth',
                'provider_execution','new_collection','new_projection_scoring','quote_implementation',
                'topic_presence_implies_position','quotes_change_measurements','exact_span_extraction_required_upstream'))
            or not plan['high_labels_require_explicit_rules']
            or plan['pipeline_order'][-1]!='optional_Ollama_illustrative_quote'
            or plan['quote_context']!=['preceding_segment','center_segment','following_segment']
            or plan['quote_anchor']!='substantive_content_in_center'):
        raise ValueError('Current planning and quotation boundaries differ')
    product=plan['product_goal']
    section=plan['automatic_section_delivery']
    if (product['status']!='not_achieved'
            or product['automatic_analysis_acceptance']!='partial'
            or product['broad_dimensional_benchmark_validated']
            or not all(product[k] for k in ('existing_scripture_use_benchmark_implemented',
                'no_model_probability_as_pastor_score','unknown_is_not_zero',
                'reuse_existing_benchmark_machinery','sampling_confirmation_independent_of_exposed_windows',
                'no_new_paid_or_dataset_run_frozen_by_documentation_update'))
            or section['eligible_complete_bindings']!=0
            or section['eligible_specific_response_descriptions']!=0
            or section['qualified_growth_dimensions']!=1
            or any(section[k] for k in ('general_generator_validated','independent_holdout',
                'production_admission','quarantine_changed','remaining_credit_is_new_experiment_authorization'))):
        raise ValueError('Product acceptance and dimensional benchmark readiness differ')
    reuse=plan['reuse_policy']
    if (reuse['semantic_owner']!='responsible_upstream_category_leaf_or_existing_shared_binding'
            or reuse['quote_input']!=['established_point','eligible_center_block','labeled_eligible_neighbors']
            or not reuse['reuse_before_new_inference'] or not reuse['changed_outputs_require_new_version']
            or any(reuse[k] for k in ('full_pack_miss_proves_constituent_absence','end_stage_general_extractor',
                'quote_supplies_analytical_authority','standalone_inventory_gate',
                'failed_experiment_automatically_starts_variant','unknowns_block_supported_delivery'))):
        raise ValueError('Reuse-first responsibility differs')
    for name,expected in plan['active_document_hashes'].items():
        if trace.digest(trace.ROOT/name)!=expected:
            raise ValueError('Current documentation differs: '+name)
    path=trace.ROOT/plan['plan_path']
    implementation=trace.ROOT/plan['implementation_path']
    if implementation.name not in path.read_text() or path.name not in implementation.read_text():
        raise ValueError('Product and implementation plans must reference each other')
    return plan,path


def reject_closed_selection(approved):
    if approved==OLD_SELECTION_INPUT:
        raise ValueError('Exact-span selection is retired. Use segment evidence first; illustrative Ollama quotes belong at the tail. No provider client opened.')
