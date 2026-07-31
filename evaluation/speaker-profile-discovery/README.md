# Shadow Speaker Profile Discovery

`pte identity shadow-discover-profiles` bootstraps anonymous speaker-profile
candidates from eligible observations that do not yet belong to a profile.

The command:

1. resolves the observation matching each current accepted sermon window;
2. excludes reviewed-invalid, multi-speaker, unresolved, and already-profiled
   observations;
3. prepares five distributed 12-second spans backed by meaningful
   sermon-labeled transcript text and cached embeddings;
4. uses centroid similarity only to nominate a bounded nearest-neighbor graph;
5. applies the pinned pair decision policy to every nominated edge;
6. proposes a provisional anonymous component only when at least three distinct
   recordings form a complete-link same-speaker graph.

Centroid similarity is retrieval evidence, not identity evidence. Only pair
policy outcomes contribute same/different edges. Missing or abstaining required
edges, reviewed different-speaker constraints, and conflicting explicit names
block a component. Transcript-empty, repetitive, and non-sermon regions cannot
contribute discovery signatures. Pair evaluation reuses the exact spans chosen
for each signature.

The existing-profile shadow matcher uses this same span-selection contract.
Changing the contract advances the association artifact version; the strict
coverage audit treats earlier non-speech-grounded attempts as stale.

Run a read-only plan:

```bash
pte identity shadow-discover-profiles \
  --plan-only \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Run the acoustic shadow pass:

```bash
caffeinate pte identity shadow-discover-profiles \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Artifacts are content-addressed below the ignored `shadow-runs/` directory and
retain observation, span, model, policy, nomination, pair-result, component, and
blocker provenance. Every artifact declares:

```text
shadow_mode=true
registry_mutation_allowed=false
automatic_profile_creation_allowed=false
```

## Controlled promotion

A completed artifact can be validated and promoted into reversible provisional
registry profiles:

```bash
pte identity promote-discovered-profiles \
  --discovery-report evaluation/speaker-profile-discovery/shadow-runs/<run>/<report>.json \
  --base-dir /path/to/app-data
```

The command is plan-only unless `--apply` is supplied. Application creates an
unnamed `provisional` profile with a stable component-derived key, records the
source artifact and seed observations, and attaches the verified complete-link
members. These profiles are eligible for shadow association but are not
automatic-profile-ready.

After rerunning shadow association, validate independent proposed matches with:

```bash
pte identity confirm-discovered-profiles \
  --base-dir /path/to/app-data
```

That command is also plan-only unless `--apply` is supplied. It accepts only
current, checksum-valid, transcript-grounded, multi-exemplar `proposed_match`
artifacts aimed at a discovery profile and requires a recording outside the
seed component. One accepted independent recording clears the profile-level
discovery confirmation blocker. Model and decision-policy approval remain a
separate prerequisite for future automatic use.

Observation consistency remains a separately calibrated gate. Supply a report
and threshold only after that policy is approved:

```bash
pte identity shadow-discover-profiles \
  --consistency-report /path/to/report.json \
  --minimum-consistency-score CALIBRATED_VALUE \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```
