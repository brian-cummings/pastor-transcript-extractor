"""Read-only current planning/retirement registry; never inference."""
from pastor_transcript_extractor import evidence_pipeline_trace as trace

HERE=trace.ROOT/'docs/review-proposals/pastor-profile-implementation-plan-v1'
OLD_SELECTION_INPUT='19a1137161528d5c4eec95242148f05abb155b2fe710d2a0d59846cceabaa8a2'


def verify():
    plan=trace.read(HERE/'plan-v23.json',True)
    if (plan['version']!='pastor-profile-product-and-implementation-status-v23'
            or plan['analytical_families']!=['preaching_style','theological_emphasis','theological_orientation','pastoral_rhetorical_orientation']
            or any(plan[k] for k in ('model_probability_is_pastor_score','benchmark_percentages_authorized','single_pastor_score_proposed','draft_is_measurement_ground_truth'))
            or plan['high_labels_require_explicit_rules'] is not True
            or plan['status']!='LOCAL_EDITORIAL_SYNTHESIS_REJECTED_REVIEWED_NO_RERUN' or plan['exact_span_extraction_required_upstream'] is not False
            or plan['pipeline_order']!=['existing_segment_observations','supported_evidence_accumulation','bounded_profile_review','strongest_supporting_segment','optional_Ollama_editorial_synthesis','optional_Ollama_illustrative_quote']
            or plan['quote_context']!=['preceding_segment','center_segment','following_segment']
            or plan['quote_anchor']!='substantive_content_in_center'
            or plan['topic_presence_implies_position'] is not False
            or plan['quotes_change_measurements'] is not False
            or any(plan[k] for k in ('provider_execution','new_collection','new_projection_scoring','quote_implementation'))):
        raise ValueError('Current segment/quotation planning scope differs')
    reuse=plan['profile_reuse_increment']
    if (reuse['status']!='DELIVERED_BOUNDED_ARTIFACT_VERIFIED'
            or reuse['main_path']!=['R1','R3','R4']
            or reuse['conditional_branch']!='R2' or reuse['held_followup']!='R5'
            or reuse['steps']['R2']['status']!='conditional' or reuse['steps']['R5']['status']!='held'
            or reuse['semantic_owner']!='responsible_upstream_category_leaf_or_existing_shared_binding'
            or reuse['quote_input']!=['established_point','eligible_center_block','labeled_eligible_neighbors']
            or not reuse['reuse_before_new_inference'] or not reuse['changed_outputs_require_new_version']
            or any(reuse[k] for k in ('full_pack_miss_proves_constituent_absence','end_stage_general_extractor',
                    'quote_supplies_analytical_authority','standalone_inventory_gate',
                    'failed_experiment_automatically_starts_variant','unknowns_block_supported_delivery'))):
        raise ValueError('Reuse-first responsibility and delivery scope differs')
    descriptions=plan['description_increment']
    if (descriptions['status']!='BOUNDED_RUN_VERIFIED_WORDING_REVIEW_PENDING'
            or descriptions['sequence']!=['D1','D2','D3','D4']
            or any(descriptions[k] for k in ('provider_execution','full_transcript_reprocessing',
                'new_measurements','collection','production_admission','quote_execution',
                'example_is_measurement_ground_truth','promote_reviewed_proposals_to_production',
                'infer_missing_meaning_from_topic_or_probability','listener_directive_run_is_next',
                'technical_delivery_is_reader_acceptance'))
            or not all(descriptions[k] for k in ('preserve_clause_evidence_links',
                'preserve_meaning_changing_qualifications','preserve_unknowns_and_counterevidence',
                'require_full_sermon_coverage_for_sermon_summary','changed_outputs_require_new_version'))):
        raise ValueError('Human-friendly description planning scope differs')
    synthesis=plan['editorial_synthesis']
    if (synthesis['status']!='EXECUTED_REJECTED_REVIEWED_NO_RERUN'
            or synthesis['live_provider_requests']!=1 or synthesis['metadata_reads']!=2
            or synthesis['review_provider_requests']!=0 or synthesis['review_metadata_reads']!=0
            or not synthesis['sentence_review_complete'] or not synthesis['decision_required_before_variant']
            or synthesis['structural_rejection']!='A unique portrait section is required'
            or synthesis['input']!='existing_supported_descriptions_and_scoped_reviewed_proposals'
            or synthesis['max_generation_requests']!=1
            or synthesis['context_size']!=32768 or synthesis['max_output_tokens']!=3072
            or synthesis['confidence_owned_by']!='code_existing_coverage_and_limits'
            or any(synthesis[k] for k in ('automatic_retries','model_pulls','cloud_or_provider_fallback',
                'new_measurements','collection','production_admission','quote_execution',
                'benchmark_comparison_available','comparative_uniqueness_authorized',
                'confidence_calibrated','citations_prove_entailment','semantic_acceptance',
                'agent_generation_requests','agent_metadata_reads'))
            or not all(synthesis[k] for k in ('no_raw_transcripts','no_raw_probability_inventory',
                'source_analysis_unchanged','requires_semantic_review','raw_response_and_usage_preserved',
                'cached_reconstruction_no_network','default_description_command_provider_free'))):
        raise ValueError('Bounded editorial synthesis scope differs')
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
    connected=plan['connected_binding_development']
    if (connected['status']!='EXECUTED_FAILED_REVIEWED_NO_RERUN' or connected['executor']!='Brian'
            or connected['passages']!=3 or connected['development_references']!=10 or connected['max_generation_requests']!=3
            or connected['live_provider_requests']!=3 or connected['metadata_reads']!=7
            or connected['review_provider_requests']!=0 or connected['review_metadata_reads']!=0
            or connected['compiled_bindings']!=0 or not connected['semantic_comparison_complete']
            or any(connected[k] for k in ('reference_visible_to_generation','broader_collection','new_measurements','production_activation','automatic_acceptance','profile_projection','benchmark_comparison','ollama_quotation_execution','model_pulls','automatic_retries','provider_fallback'))):
        raise ValueError('Completed failed connected extraction scope differs')
    path=trace.ROOT/plan['plan_path']
    if trace.digest(trace.ROOT/plan['agents_path'])!=plan['agents_sha256']:
        raise ValueError('Project reuse instructions differ from current plan')
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
