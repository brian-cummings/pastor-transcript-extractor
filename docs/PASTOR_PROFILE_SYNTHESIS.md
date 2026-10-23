# Local editorial synthesis: closed experiment status

**Current as of 2026-10-23: no active Ollama editorial synthesis increment.** The current product is the provider-free V8 [reviewed portrait workflow](PASTOR_PROFILE_DESCRIPTION.md). The [implementation plan](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md) is the active engineering authority.

Do not run `pte analysis profile-synthesis --run` as a follow-up to the current plan. The command remains implemented for historical development; a new source/configuration fingerprint could create a new request. Its presence is not authorization to retry, change prompts/schemas, switch models or run it against V8. Cached reconstruction also depends on matching historical inputs, so the current CLI is not advertised as a portable replay of old receipts after later source changes.

## Preserved results

| Experiment | Outcome | Meaning |
|---|---|---|
| S1 V1, `gemma3:4b` | One generation; 5,863 input / 147 output tokens; 26.409 seconds model duration. Missing portrait, rejected structurally. | Required in the prompt but optional in the generation schema. Two copied topic descriptions and an unsupported inference did not make a useful portrait. |
| S1 V2, same model | One generation; 5,872 input / 377 output tokens; 34.017 seconds model duration. Portrait present; semantic review rejected all six entries for unsupported additions. | Required-portrait correction worked structurally. Topic attention still became unsupported belief, consistency or alignment claims. No semantic acceptance. |

V1 panel: `d40b9159249df6f35bbe3e2afc3c66329b874cc4e633fed51713f3dd8756b855`.
V2 panel: `ada8c143376fda95d6deb741ee313e7b6b5c9fdb6deca99eb4c45cd3dad757ae`.
V2 semantic review: `7bb1c0b9ae7f3d0fad811b3bc56b482286b476c8aa7dc45cc07e0139e9d68d99`.

Requests, raw responses, pinned backend receipts, usage, drafts and reviews remain under the app base in `evaluation/pastor-profile-synthesis-v1/runs/<panel>/` and `evaluation/pastor-profile-synthesis-v2/runs/<panel>/`. The V2 `semantic-review-v1.md/json` is the reviewed verdict; its original HTML remains a structurally valid, explicitly unaccepted draft. No original response has been rewritten.

The experiment-time fallback was V5. Subsequent provider-free work produced V8; “keep V5” in old run reviews is historical, not the current delivery recommendation. No quality-parity percentage or measured economic advantage was established.

## Boundaries retained

The experiments used descriptions/proposals, not full transcripts, with one request per prepared packet, local model identity checks and no automatic retries, pulls or fallback. Those safeguards do not establish entailment. Future work must reuse supported meanings and expose interpretation, not ask a writer to repair missing upstream adoption or attribution.

Comparison/ranking, calibrated confidence, new measurements/admission, broader collection, ministry stability and Ollama quotation execution remain held. The new portability proposal adds no provider authorization.

The [exact pre-portability workflow snapshot](PASTOR_PROFILE_SYNTHESIS.historical-before-portability-2026-10-23.md) preserves the original implementation and execution instructions for history only. Use saved artifacts for inspection; historical commands are not an active task queue.
