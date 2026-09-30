# Evaluation storage dry-run — 2026-09-29

Command:

```console
pte migrate-evaluation-storage --dry-run --verify \
  --base-dir /Users/briancummings/Documents/PastorSearchData \
  --repo-root /Users/briancummings/code/pastor-transcript-extractor
```

Result: **331,430 files** and **41,706,302,797 bytes** planned. The scan found
**zero destination collisions**, **zero unsafe symlinks**, and **zero already-migrated
files**. No files were moved or deleted.

| Category | Files | Bytes |
| --- | ---: | ---: |
| diagnostics | 52,879 | 12,633,167,774 |
| drafts | 75 | 68,205 |
| identity-leverage | 39 | 991,778 |
| interaction-diagnostics | 132 | 1,738,261 |
| recording-verifier | 108 | 535,482 |
| recording-verifier-typesafe | 220 | 2,080,338 |
| results | 195 | 5,150,358 |
| source-profile-consolidation/runs | 28 | 1,608,578 |
| speaker-associations/shadow-runs | 16,675 | 3,148,938,466 |
| speaker-pairs/cache | 260,297 | 25,238,298,294 |
| speaker-pairs/drafts | 484 | 4,520,304 |
| speaker-pairs/models | 4 | 82,616,268 |
| speaker-pairs/reports | 3 | 89,708 |
| speaker-pairs/runs | 71 | 557,488 |
| speaker-profile-discovery/promotion-judgments | 181 | 3,024,475 |
| speaker-profile-discovery/shadow-runs | 39 | 582,917,020 |

The database audit found **450** legacy path values eligible for transactional conversion:

| Field | Rows |
| --- | ---: |
| `speaker_machine_evidence.association_artifact_path` | 101 |
| `speaker_profile_candidate_confirmations.association_artifact_path` | 174 |
| `speaker_profile_discovery_promotions.discovery_artifact_path` | 138 |
| `speaker_profile_discovery_promotions.promotion_judgment_artifact_path` | 37 |

A read-only JSON reference scan found 79,817 generated JSON files containing a legacy
repository evaluation reference. These immutable artifacts are intentionally not
rewritten: moving them byte-for-byte preserves their result hashes and cache identities,
and the central resolver translates their paths when dereferenced.

Expected final layout is
`/Users/briancummings/Documents/PastorSearchData/evaluation/<generated-category>`.
Repository fixtures, policies, reviews, revocations, source-family definitions, and
documentation remain under the checkout's `evaluation/` tree.
