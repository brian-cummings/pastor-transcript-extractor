# G3 V1: observable pastoral address

Status: **approved design; bounded feasibility PASS** as of Brian's 2026-10-14
review of V2. [Decision and limitations](../../../evaluation/g3-address/feasibility-stage-gate-v2.md).
Construct tuning is closed. Full collection, automatic candidate recall, pastor
projection, empathy/effectiveness/quality scoring remain unestablished. G1
implementation/expansion stays held; G4 is deferred.

## Accepted V2 relationship clarification

The V1 design's generic circumstance binding is refined into **circumstance
relevance** and **human-recipient circumstance binding**. An utterance may concern
grief while addressing God; it is then relevant but not bound to a human recipient.
A reported address can bind to its reported recipient without becoming adopted
current-listener address. The seven acts, source voice and adoption remain separate.
Current-listener evidence composes observed act, demonstrated relevance and recipient
binding, current-listener addressee, own/adopted stance and sufficient local evidence.
Context may resolve identity but cannot supply treatment. The [exact V2 questions](../g3-feasibility-v2/questions-v2.json)
implement this distinction in the isolated feasibility harness; the authored V1
fixture expectations below remain historical design examples, not regraded results.

The product question is: **How does this pastor address people in particular circumstances?**
C12 should distinguish observed ways of acknowledging, reassuring, challenging, inviting,
warning and giving care, including qualifications and variation. The system observes address;
it does not infer inner empathy, personal virtue or actual effects on listeners.

## Downstream statement contract for C12

Desired future statement: “In the reviewed grief material, this pastor acknowledges
listeners' difficulty, reassures without promising immediate relief, and offers qualified
concrete care,” with independent evidence, scope, coverage, counterexamples and uncertainty.
Another supported profile could describe a different mix of challenge, warning, invitation
and acknowledgment. These are meaningful differences without declaring one globally better.

Insufficient evidence yields “This passage shows an adopted address act; recurring posture
in this circumstance is not characterized.” Missing circumstance/binding yields “Thematic
or listener-action evidence is present, but the corresponding pastoral address is unresolved.”
A general profile must not become “empathetic pastor” from a compassion topic or service appeal.
Human reading can judge noteworthy address using explicit examples; the model does not certify
compassion, harmfulness, motive, emotional state or benefit.

Current topic signals (`T:suffering_adversity_death`, relationships, compassion), actions
(`L:serve`, `repent`, `trust`) and `H:practical_application` locate candidates. They do not
establish the relation between an adopted address act and the person/circumstance addressed.
G3 must observe that missing relation. A preacher's claim to care is a reported self-description,
not automatically a demonstrated circumstance-sensitive address.

## Collection contract: AddressEpisode, circumstance and address acts

Input: exact target text with source identifiers and bounded context; source-backed candidates
for addressee, circumstance and utterance; content-role/identity/eligibility provenance; optionally
existing G1/G2 nodes as reusable references. No pastor traits or cross-sermon characterization
supplies an answer. Sermon language establishes the circumstance **as addressed/presented**;
it does not establish that real listeners have it.

| Record/field | Required meaning and evidence |
| --- | --- |
| AddressEpisode | Code-owned episode ID, target/source hash and bounds, proposed-boundary/completeness status, subject candidates, source node references. Not a reviewed emotional episode or a diagnosed listener condition. |
| Addressee | God in prayer, no address, direct current listener, present listeners through explicitly applied inclusive “we,” hypothetical/general person, reported/historical person, or unresolved. Exact referent evidence is retained. |
| Circumstance | Source wording (grief, uncertainty, moral failure, hardship or another bounded authored case), stated person/referent, span, and whether target-grounded or context-resolved. No diagnosis or invented vulnerability. |
| AddressAct | Act ID, type, exact target utterance span, voice/adoption, addressee/circumstance IDs, and separate target evidence that this act addresses that circumstance. Independent acts may share spans. |
| Circumstance relevance | Exact utterance concerns this specified circumstance, independent of addressee; retain target-grounded/context-resolved identity and unresolved/negative states. Relevance alone is not an address act. |
| Human-recipient circumstance binding | Target shows address to the human recipient in that recipient’s circumstance. Reports may bind; prayer to God and wrong-recipient treatment do not. Current-listener status and preacher adoption are separate. |
| Qualification | Source-bound condition, limit or exception attached to the particular address act; empty means no explicit qualifier observed in that candidate, not unconditional advice. |
| Link to G2 | Optional response/reason/application node IDs. Advice development and relational address are independent; neither implies the other. Shared evidence is counted once for independence. |
| Observation state | Supported local observation, unresolved relation/voice/addressee, not observed in a complete candidate, partial/continuation required, candidate-coverage unknown, or not evaluated. |
| Production envelope | Actual source segment/time hashes, context roles, membership/eligibility, candidate/question/model identities, raw answers, grounding/semantic-review status. Authored fixtures supply no provider answers or real sermon IDs. |

The proposed act distinctions are:

| Act | Positive observable | Does not suffice |
| --- | --- | --- |
| `acknowledgment` | Explicitly recognizes a person's stated difficulty/experience as part of address. | Naming grief as a subject, mentioning sufferers, or a care self-description alone. |
| `perspective_taking` | Explicitly voices a possible perspective, constraint or concern of the addressed person without claiming omniscient access to feelings. | The analyst imagining how listeners probably feel. |
| `reassurance` | Offers comfort, support or a reassuring assurance addressed to the circumstance. | Hopeful doctrinal content unrelated to an identified circumstance. Accuracy or likely effect is a separate judgment. |
| `challenge` | Directly calls the addressed person to reconsider or change a specified response/conduct. | A general moral subject with no adopted address. |
| `warning` | Addresses a stated consequence/risk as a reason for attention/action. | Narrating punishment of historical people without applying it. Does not alone imply condemnation or manipulation. |
| `invitation` | Offers an addressed opening to respond, seek help or participate. | A bare description of available activities with no adopted invitation. |
| `concrete_care` | Offers or directs a specified act of care tied to the addressed circumstance. | Service/giving/participation vocabulary alone or unverified delivery of care. |

These are distinct address observations, not competing bins on a kindness/harshness axis.
An adopted passage can acknowledge grief, challenge harmful conduct, warn, and invite help.
Do not force exclusivity merely to simplify a pastor profile. Expressed uncertainty/qualification
may shape an act; its evidence can reuse G1 but is not inferred from an undecided model.

### Voice, target evidence and contextual reference rules

A quoted insensitive or comforting statement can be material in a sermon. Record voice/adoption;
only the preacher's own/adopted address can contribute to the pastor's address pattern. Rejection
of a quote does not synthesize an opposite comforting act; independently evidenced address does.
Address to God in prayer is not direct listener address. A biblical/historical act is not the
preacher's present address without explicit application. General/hypothetical address can be
retained with its type, but cannot establish an act directed to actual present listeners.

The act and evidence of its circumstance relation must be in the target. Context may resolve
who “you” means or which loss “this” refers to; it cannot supply missing acknowledgment or care.
Context-resolved circumstances are tagged as such, not counted as target circumstance treatment.
If the referent remains ambiguous, retain the utterance but abstain from circumstance-bound posture.
A grief topic near an imperative does not itself bind that imperative to grieving people.

Perspective-taking reports an expressed possible experience, not an empirical assertion that
listeners feel it. Kind words may be generic. Strong challenge may also acknowledge a real difficulty.
Collection records what is said, to whom and under what stated bounds; it must not infer “this
pastor is empathetic,” “the congregation felt supported” or “this advice was safe/effective.”

## Projection contract for C12

Project by circumstance and adopted address-act pattern, not by pooled positive-sentiment score.
Deduplicate utterances/blocks into independently reviewed episodes and independent sermons.
Retain hypothetical/general versus direct current-listener address as distinct populations.
Count only adequately bound adopted address evidence; plain reports/quotes remain material.

Declare both whole-measured-sermon occurrence and a circumstance/opportunity-conditional
estimand. The latter requires detection of **all relevant address opportunities**, including
those where a given act was not observed, rather than only act-positive examples. Circumstance
mention alone may not be an address opportunity. Its definition, completeness/coverage and
potential misses require their own review before rates are permissible.

Within a circumstance, show multi-act patterns, qualifications, concrete evidence and contrasting
passages. Acknowledgment without challenge and challenge with acknowledgment are different patterns,
not mutually exclusive ideological positions. Different treatment of grief and moral failure is
conditional variation, not automatically inconsistency. Unknown circumstance/opportunity/identity,
partial episode or missing measurement remains unavailable; it is not uncaring treatment.

A recurrent posture statement requires independent support, relevant opportunities, coverage,
series/period scope and sensitivity, with no approved universal sermon count. Temporal claims need
actual sermon dates and repeated evidence. Comparisons need matched circumstances/addressee types,
compatible semantics and demonstrated coverage. Human judgment remains responsible for whether
an expression is adequate, respectful or noteworthy in context; no occurrence rate establishes
inner empathy, personal benevolence or effect.

G3 may support future discovery cards for circumstance-sensitive address, with evidence and
limits. G2 supplies application development if observed. G1 supplies adopted claims/qualifiers
if relevant. Neither G3 nor their combination creates an overall pastoral-quality score.
G4 coherence is deferred and consumes G1/G2 relation evidence rather than G3 sentiment proxies.

## Prepared contrasts and remaining limits

[G3 cases in CASES.md](CASES.md#g3-cases) cover acknowledgment versus topic mention,
perspective-taking, qualified reassurance, challenge with acknowledgment, concrete care,
generic self-description, quoted/rejected address, historical and prayer address exclusions,
context resolution/leakage, and unanswered direct circumstance binding.
[Expected records](cases-v1.json) are authored designs, not measured sermon observations.
Structural checks establish source integrity, not candidate recall or semantic correctness.

This contract provides observation types for C12. It still requires candidate/act accuracy,
address-opportunity coverage, boundary review, sufficient independent support and qualitative
assessment before a pastor posture claim. Those gaps must remain visible alongside an eventual
profile of observed address, not disappear behind an empathy proxy.
