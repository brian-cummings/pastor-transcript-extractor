"""Summarize saved artifacts only; no database, detector, model, or resampling jobs."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics as st

ROOT = Path(__file__).resolve().parent


def quantile(values, p):
    values = sorted(values)
    x = (len(values) - 1) * p
    a = int(x)
    return values[a] + (values[min(a + 1, len(values) - 1)] - values[a]) * (x - a)


def distribution(values):
    return dict(n=len(values), minimum=min(values), q1=quantile(values, .25),
                median=st.median(values), q3=quantile(values, .75), maximum=max(values))


def main():
    snapshot = json.loads((ROOT / 'population-snapshot-2.json').read_text())
    inputs = json.loads((ROOT / 'persisted-inputs.json').read_text())
    report = snapshot['report']
    within = {}
    # These two sermon-level measurements are saved directly, not reconstructed.
    for feature, key in [('references_per_1000_words', 'reference_density_per_1000_words'),
                         ('scripture_text_engagement_fraction', 'scripture_text_engagement_fraction')]:
        groups = [[s[key] for s in p['measurements']['sermon_scripture_structure']
                   if s[key] is not None] for p in inputs['scripture_profiles']]
        groups = [g for g in groups if len(g) >= 2]
        k, n = len(groups), sum(map(len, groups))
        grand = sum(map(sum, groups)) / n
        ssw = sum(sum((x - st.mean(g)) ** 2 for x in g) for g in groups)
        ssb = sum(len(g) * (st.mean(g) - grand) ** 2 for g in groups)
        msw, msb = ssw / (n - k), ssb / (k - 1)
        n0 = (n - sum(len(g) ** 2 for g in groups) / n) / (k - 1)
        intercept = max(0, (msb - msw) / n0)
        within[feature] = dict(
            sermon_distribution=distribution([v for g in groups for v in g]),
            within_profile_sd_distribution=distribution([st.stdev(g) for g in groups]),
            between_equal_sermon_profile_mean_sd=st.stdev([st.mean(g) for g in groups]),
            residual_mean_square=msw, unadjusted_profile_intercept_variance=intercept,
            unadjusted_icc=intercept / (intercept + msw),
            caveat='One-way method of moments; source, topic, date, measurement error and selection unadjusted. No interval estimated; not a causal pastor variance component.')
    features = {}
    for name, d in report['feature_diagnostics'].items():
        features[name] = dict(distribution=d['distribution'],
                             median_max_loo_iqr=d['leave_one_out']['median_max_delta_in_population_iqr'],
                             median_conditional_bootstrap_width_iqr=d['bootstrap']['median_ci_width_in_population_iqr'],
                             sermon_count_r=d['corpus_size_pearson'])
    out = dict(snapshot_id=snapshot['snapshot']['id'],
               snapshot_fingerprint=report['input_fingerprint'],
               input_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                             for name in ['population-snapshot-2.json', 'persisted-inputs.json']},
               depth_counts=Counter(p['sermon_count'] for p in report['profiles']),
               features=features, actual_sermon_variation=within,
               structure=inputs['structure_profiles'][0]['measurements']['feature_summaries'])
    (ROOT / 'summary.json').write_text(json.dumps(out, indent=2, sort_keys=True) + '\n')
    print(json.dumps(within, indent=2))


if __name__ == '__main__':
    main()
