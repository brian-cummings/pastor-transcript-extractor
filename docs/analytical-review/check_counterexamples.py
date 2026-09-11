"""Three tiny synthetic falsification checks; never touches corpus data."""
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import statistics

from pastor_transcript_extractor.population_analysis import SermonRecord, aggregate_sermon_records
from pastor_transcript_extractor.benchmark import _rank_reference

record = SermonRecord(1, 1, 1, None, 1000, Counter({'John': 1}),
                      Counter({'John 3': 1}), 0, 0, 0, 0, (), Counter())
other = replace(record, run_id=2, video_id=2, books=Counter({'Romans': 1}),
                chapters=Counter({'Romans 8': 1}))
base = aggregate_sermon_records([record, other])
duplicate = aggregate_sermon_records([record, record])
assert base['cross_sermon_anchor_coverage'] == 0
assert duplicate['cross_sermon_anchor_coverage'] == 1
assert base['mean_pairwise_book_distribution_cosine'] == 0
assert duplicate['mean_pairwise_book_distribution_cosine'] == 1

values = [0, 1, 2, 3, 4]
loo = [statistics.mean(values[:i] + values[i + 1:]) for i in range(len(values))]
ratio = statistics.pvariance(values) / statistics.pvariance(loo)
assert ratio == 16

# A dimension constant in the panel is silently removed even for a very different candidate.
candidate = {'comparison_values': {'varying': 0., 'constant': 100.}}
reference = {'comparison_values': {'varying': 0., 'constant': 0.},
             'resolved_profile_id': 1, 'resolved_display_label': 'synthetic',
             'profile_analysis_run_id': 1}
rank = _rank_reference(candidate, reference, families={'example': ('varying', 'constant')},
                       panel_statistics={'features': {
                           'varying': {'median_absolute_deviation': 1, 'minimum': 0, 'maximum': 2},
                           'constant': {'median_absolute_deviation': 0, 'minimum': 0, 'maximum': 0}}})
assert rank['distance'] == 0 and len(rank['feature_differences']) == 1
result = {'bootstrap_duplicate': {name: [base[name], duplicate[name]] for name in
          ['cross_sermon_anchor_coverage', 'mean_pairwise_book_distribution_cosine']},
          'sermon_to_loo_variance_ratio_n5': ratio, 'constant_panel_dimension_result': rank}
Path(__file__).with_name('counterexamples.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
