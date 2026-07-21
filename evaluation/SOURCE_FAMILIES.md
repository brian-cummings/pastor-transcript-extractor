# Sermon evaluation source families

`source-families.json` prevents recordings from the same church or production
source from leaking across development, validation, and held-out evaluation.
The registry is evaluation provenance only. Its metadata must never determine
whether a recording contains a sermon or where sermon boundaries belong.

## Grouping rule

A source family represents a recurring church/channel production context. Keep
the entire family in one partition even when its recordings differ by date,
caption source, microphone, room, or service format. Those differences create
recording-condition groups for reporting; they do not split the family across
partitions.

The 22 fixtures in `sermon-localization-v1` all remain in `development` because
they influenced prompt or algorithm decisions before partitioning was added.
They cannot become held out retroactively.

## Adding a source family

Synchronize newly imported database sources first:

```bash
pte sync-source-families \
  evaluation/source-families.json \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The command groups URL aliases by resolved channel identity, preserves existing
assignments, and deterministically partitions genuinely new source families.

1. Review objective provenance: channel or church, production setup, production
   era, recording format, and caption source. Do not inspect expected outcomes
   when deciding the family or partition.
2. Reuse an existing family when the same recurring production source applies.
3. For a genuinely new family, choose a stable descriptive ID and use the
   `source_family_partition_v1` hash policy to determine its partition.
4. Add the family and freeze its partition before its fixture is reviewed.
5. Use `partition_origin: deterministic` for a hash assignment. Overrides must
   state a different explicit origin and must never be based on fixture truth or
   model performance.

Validate registry coverage with:

```bash
pte validate-source-families \
  evaluation/source-families.json \
  --fixture-dir evaluation/fixtures \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

## Partition discipline

- `development`: may inform prompts, rules, and implementation changes.
- `validation`: may measure a proposed change, but should not be tuned fixture by
  fixture.
- `held_out`: run only at explicit promotion checkpoints. Repeated inspection or
  tuning against these results invalidates held-out status.

Partition reports should include fixture, source-family, and recording-condition
group counts. A result is not independent merely because it uses a different
video from the same family.
