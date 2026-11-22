# Object-position check: does an object-centered, whole-sermon question fix what the block unit could not

**Status: specification only (2026-11-22). Nothing is implemented, and no provider call is authorized until Brian approves
sections 2 to 8.** Read [AGENTS.md](../AGENTS.md), the closed [bound-claim pilot](BOUND_CLAIM_PILOT.md) (§15 close-out) and the
evidence trace in the pilot directory (`GAP_ANALYSIS.md`) first. This check does not change the pilot's closed result.

## 1. The one question

> For one named object in one sermon, does a single object-centered question over the whole sermon return the preacher's own
> position, with its qualifications and reasons, as correctly and more completely than the block-by-block claims did?

Why this and nothing broader. The pilot failed criterion 1 and the failing component was the contract. Its position evidence for
"the American experiment" in sermon 281 already contained 6 of 7 components, but scattered over three blocks, under two object
names, with the key qualification in a neighboring block that the contract bars as support, and among 319 claims with no order.
This check tests only whether changing the unit (object, whole sermon) repairs that. It does not test salience across a corpus,
other objects, other pastors, Jev verification or production admission.

## 2. Frozen inputs (chosen before any output exists)

- Sermon: video 281, profile 318, "The American Experiment: Success or Failure?" (Pastor John Bradshaw, July 4, 2026), source text
  and block coordinates exactly as in pilot v1's `strata.json` source (`source_sha256` recorded at freeze).
- Object: "the American experiment", taken from the sermon title, not from any output.
- Producer: DeepSeek V4 Pro, reasoning off, the same pinned model, executor and streaming recovery as the pilot. No model switch.
- Exposure disclosure: the seven components below were written after reading this sermon's pilot claims. This is exposed
  development material, not independent validation, and a pass licenses nothing beyond what section 8 says.

## 3. The question and record (demonstrated defect, change, check)

One request. Output: a list of records in the existing `BoundClaim` shape (same fields, same anchor check by code against the
sermon text). Only the instruction differs, and each difference answers a defect seen in the 40 labeled claims:

| Defect shown in labeling | Change in the instruction | Where it is checked |
| --- | --- | --- |
| Illustrations, retold stories, prayers and recited documents became "claims" | Return only statements the preacher makes as their own position on the object; exclude retellings, prayers and recitations | Relevance and component checks (§5) |
| "us"/"they" widened or left unresolved; sarcasm lifted out of context | Each proposition must be self-contained and name its referents; keep ironic statements with the framing that makes them ironic | "no flipped or unresolved record" (§5) |
| Qualification in the neighboring block, barred as support | The whole sermon is the source; qualifications and reasons may come from anywhere in it, each with its own anchor in `qualifications`/`reasons` text | Component 1 must carry its qualification (§5) |
| Polarity convention undefined for negated propositions | Polarity is the preacher's stance toward the proposition as written | "no flipped record" (§5) |
| 10.6 claims per block, no order | Only records that bear on the object; no per-sermon quota | One-third irrelevant limit (§5) |

The instruction text is written during implementation, reviewed by Brian, and sealed by hash in the frozen plan before the run.

## 3a. Pre-registered components

Each is judged present only if a returned record states it faithfully, with the stated polarity convention, from the preacher's own
voice, anchored at (or overlapping) the literal source span shown.

1. It works as an experiment in self-government. "...the American experiment is working brilliantly. It has succeeded beyond
   anybody's wildest dreams." and "an experiment in self-government" (b92, b93). Must carry component 4 as its qualification.
2. It was a cultural and political experiment, not a religious one (b93).
3. Government of the people has the people doing what they want and electing who they want (b93).
4. "from a religious point of view, it's a massive failure" (b93).
5. It is failing to live up to its original promise (b113).
6. Cause: "because of the sinful human heart", not Republicans, Democrats, independents or one policy (b113).
7. "there is, thank God, a solution for that predicament", with the predicament identified as the sinful human heart (b113).

## 4. Cost, ceilings and stops

- One request over the sermon text. `--check-only` reports the token estimate first. If the sermon exceeds the model's context, stop;
  no chunking or retrieval variant is added.
- Ceiling for the whole check: $0.50 and 2 physical attempts (the second is the bounded whitespace/transport recovery only). No
  semantic retry, no second prompt, no second run to resolve an unfavorable result.
- New ledger and plan under `<base>/evaluation/object-position-check-v1/`; pilot v1's ledger and receipts are untouched.
- Stop and report on: schema failure, ceiling, output over 40 records, or any unresolved usage.

## 5. Acceptance, frozen before execution

All of the following, judged by Brian from the source text, with the record list presented with no model identity:

1. All 7 components present as defined in §3a.
2. Component 1 carries the religious-view qualification (the relation the block unit could not hold).
3. At least two thirds of returned records bear on the object's position, as Brian judges them (the pilot baseline is under 10%).
4. No returned record is flipped, unresolved in a way that changes its meaning, or attributes a view to the wrong speaker or scope.
5. Every anchor passes the literal check by code.

Baseline for comparison (pilot v1, same sermon): 6 of 7 components present, component 1 unqualified, 15 or fewer of 319 claims about
the object, 3 of the position claims duplicated across producers.

## 6. If it passes, if it fails

- Pass: engineering evidence that an object-centered unit repairs these defects on one exposed case. It is not validation,
  production admission or a product result. Any further step (a second object, a second sermon, a Jev verification pass,
  aggregation) needs a separate decision by Brian with its own criteria.
- Fail: the unit of extraction is not the fix. Report which component or criterion failed and stop this line; do not launch a revised
  prompt. A fail on criteria 3 or 4 alone points back to the contract, not the unit, and is reported that way.
- Either way: no automatic expansion, no threshold change and no next experiment follows from the result.

## 7. Implementation sketch (after approval only)

Reuse the pilot's DeepInfra executor, ledger (new instance), anchor check and frozen-plan machinery. New: an `object-position`
prompt version, a one-request runner and a review packet. CLI tie-in:

```bash
pte analysis object-position check --base-dir <base> --object "the American experiment" --video 281 --check-only
pte analysis object-position check --base-dir <base> --object "the American experiment" --video 281
pte analysis object-position review --base-dir <base>
```

Focused offline tests only; no corpus or fixture runs. Commit in coherent steps. Brian runs the paid command.

## 8. Decisions for Brian

1. Approve the frozen inputs (§2), the seven components (§3a) and the acceptance (§5), or edit them now. They cannot change after
   an output exists.
2. Approve the $0.50 / 2-attempt ceiling.
3. Approve writing the instruction text (reviewed by Brian before sealing) and the implementation in §7.
