# TypeSafe Sermon Topic Analysis Plan

Status: Stage 1 through Stage 4 validation and immutable sermon/profile topic
projection are implemented. The broad question pack remains
`topics-v3-mission-discourse-boundary`. **Salvation question-set readiness: PASS;
measurement development is complete as of Brian's 2026-10-13 review.** The nine
approved leaves, definitions/questions, routing, thresholds, V9 observation
policy, and measurement semantics are frozen for broader use. The completed
provider-free uncertainty packet uses 11/10/12 measured independent sermons.
Pastor-level inference must retain sampling, period/series, and denominator
uncertainty; no universal sermon-count sufficiency threshold is established.
The three unresolved salvation leaves remain excluded. **Listener-directive question-set readiness: PASS; validation is closed.
Public-life treatment-question readiness: PASS.
Next: develop the source/material question set**, following the existing enrichment order and
[handoff below](#next-iteration). Do not continue salvation calibration or send
additional salvation material through TypeSafe to complete this milestone.

## Purpose

Add a broad topic-prominence layer to the existing TypeSafe fine localization
pass. For each approximately one-minute fine block, Jev will independently
score how prominently twenty sermon topics are discussed. The raw observations
will be stored for future analysis when the recording is ultimately accepted as
a sermon and projected through effective reviewed speaker-profile membership.

The topic layer answers:

> What subjects receive meaningful attention in this part of the sermon, and
> how central is each subject to the block?

It does not by itself answer what position the preacher takes, how two
theological concepts are related, what source material is used, or what the
listener is directed to do.

## First field observation: video 4548

The first naturally processed result, **Accepted in the Beloved**, was
directionally encouraging. Its retained sermon blocks emphasized salvation,
God's action, Jesus, and sin. Specific blocks also surfaced the expected
eschatology, suffering, and spiritual-conflict signals. The broad inventory is
therefore useful enough to continue without adding, removing, or merging topics.

The run also exposed three distinctions that the next iteration must preserve:

1. **Text topic is not preacher attribution.** Song lyrics genuinely contain
   subjects such as God, Jesus, and salvation. Raw topic observations may record
   those subjects, but a music-role block must not become evidence about the
   preacher's topical emphasis. Code owns that attribution through the final
   retained sermon and projection policy.
2. **A performed song is not automatically the church/worship topic.** Lyric
   blocks 52–55 scored only `0.08`–`0.24` on
   `church_worship_community`, even while several theological subjects scored
   higher. This is the desired distinction: performing worship is a content
   role; discussing corporate worship or church life is a topic.
3. **Correct topic observations cannot repair an incorrect sermon boundary.**
   Closing-prayer blocks 80–81 had strong
   `sermon_integrated_prayer_or_scripture` probabilities, but sparse intervening
   captions split the component and left them with zero retained-sermon overlap.
   Boundary recovery must be fixed before projection or valid closing material
   will be omitted.

Block 69 also showed why topic and source/material must remain separate. A
prodigal-son illustration produced elevated relationship and compassion scores
even though salvation and acceptance organized the point. Preserve that case in
bounded review; do not expand or collapse the taxonomy in response to one
illustration.

## Analytical layers

Keep these layers distinct even when they overlap in the same block:

| Layer | Question | Examples |
|---|---|---|
| Topic prominence | What is being discussed, and how centrally? | salvation, eschatology, public life |
| Homiletic treatment | What is the preacher doing rhetorically? | exposition, illustration, doctrinal argument, application |
| Source or material | What material carries the point? | biblical narrative, personal testimony, Ellen White quotation |
| Listener directive | What response is requested? | trust, repent, serve, give, take civic action |
| Theological proposition | What relationship or stance is affirmed? | obedience as consequence rather than condition of salvation |

The existing four semantic dimensions remain homiletic-treatment observations.
They must not be interpreted as topic-specific treatment. Topic and treatment
co-occurring in one block establishes block-level co-occurrence, not that the
treatment applies to that topic.

## `topics-v1` inventory

The stable key, definition, inclusions, and exclusions form part of the
question contract. Changing their meanings requires a new topic-pack version.

### 1. `god_character_action`

**Label:** God: character, will & action

Discussion of God's attributes, character, purposes, will, sovereignty,
providence, or actions.

- Include: divine love, justice, holiness, faithfulness, judgment, providence,
  creation, governance, and action in history or individual lives.
- Exclude: undeveloped references to God; a passage involving Jesus without a
  developed claim about God or divine character and action.
- Allowed overlap: Jesus, salvation, creation, suffering.

### 2. `jesus_person_work`

**Label:** Jesus Christ: person & work

Discussion of Jesus's identity, character, incarnation, ministry, teachings,
death, resurrection, mediation, reign, or return.

- Include: Christology, the cross, resurrection, earthly ministry, teachings,
  priestly or mediatorial work.
- Exclude: Jesus merely appearing in a quotation or story without meaningful
  development of his person, teaching, or work.
- Allowed overlap: God, salvation, Scripture, eschatology.

### 3. `holy_spirit_person_work`

**Label:** Holy Spirit: person & work

Discussion of the Spirit's identity, presence, conviction, transformation,
guidance, gifts, empowerment, or activity.

- Include: indwelling, fruit or gifts of the Spirit, inspiration, conviction,
  guidance, empowerment.
- Exclude: generic divine action not attributed to the Holy Spirit.
- Allowed overlap: God, discipleship, church, Scripture.

### 4. `scripture_revelation`

**Label:** Scripture & revelation

Discussion of Scripture or revelation itself: its inspiration, authority,
reliability, interpretation, canon, disclosure, or hermeneutics.

- Include: how to interpret the Bible, why Scripture is authoritative, divine
  revelation, inspiration, reliability.
- Exclude: merely quoting, retelling, or expounding a biblical passage without
  discussing Scripture or revelation as a subject.
- Allowed overlap: church, Adventist doctrine, prophecy.

Biblical narrative remains a future source/material signal rather than a topic.

### 5. `sin_fallenness_human_need`

**Label:** Sin, fallenness & human need

Discussion of sin, guilt, rebellion, fallenness, moral corruption, alienation
from God, or the human need created by sin.

- Include: original or inherited fallenness, guilt, idolatry, rebellion,
  consequences of sin, inability or need before God.
- Exclude: ordinary mistakes, suffering without developed moral or spiritual
  brokenness, resisting temptation when the focus is Christian growth.
- Allowed overlap: salvation, human nature, discipleship, ethics.

### 6. `salvation_gospel`

**Label:** Salvation & gospel

Discussion of God's saving work and the human reception or experience of
salvation.

- Include: grace, atonement, forgiveness, justification, conversion,
  reconciliation, adoption, assurance, and sanctification as saving work.
- Exclude: general growth or spiritual practice after salvation when saving
  work is not being discussed.
- Allowed overlap: Jesus, sin, discipleship, eschatology.

### 7. `discipleship_spiritual_formation`

**Label:** Discipleship & spiritual formation

Discussion of lived Christian growth, trust, obedience, prayer, spiritual
disciplines, resistance to temptation, character, and formation.

- Include: prayer practice, faith and trust as lived response, obedience,
  habits, growth, spiritual disciplines, Christian character.
- Exclude: salvation itself; moral evaluation without formation or lived
  discipleship.
- Allowed overlap: salvation, ethics, relationships, mission.

### 8. `relationships_family_interpersonal`

**Label:** Relationships, family & interpersonal life

Discussion of marriage, family, parenting, friendship, forgiveness, conflict,
sexuality, loneliness, or interpersonal responsibilities.

- Include: reconciliation between people, family roles, friendship, relational
  boundaries, interpersonal sexuality.
- Exclude: church community when ecclesiology is the subject; abstract moral
  principles without a developed interpersonal setting.
- Allowed overlap: ethics, discipleship, church, compassion.

### 9. `church_worship_community`

**Label:** Church, worship & community

Discussion of the nature, purpose, practices, leadership, unity, fellowship,
membership, worship, ordinances, or gifts of the church.

- Include: ecclesiology, congregational life, corporate worship, church
  leadership, unity, sacraments or ordinances, spiritual gifts in community.
- Exclude: merely addressing the congregation or referring to the local church
  without developing it as a subject.
- Allowed overlap: Holy Spirit, mission, relationships, Adventist identity.

`topics-v2-performed-worship-boundary` makes the already intended boundary
explicit: music, lyrics, prayer, or another act of worship merely being
performed does not establish this topic unless worship or church life is itself
discussed. Because question wording participates in cache identity, the
clarification uses a new pack version rather than silently rewriting stored
`topics-v1` observations.

### 10. `mission_evangelism_witness`

**Label:** Mission, evangelism & witness

Discussion of proclaiming the gospel, witnessing, disciple-making, missions,
or communicating faith outwardly.

- Include: personal witness, evangelistic proclamation, cross-cultural mission,
  disciple-making.
- Exclude: kindness or service whose principal purpose is not proclamation or
  disciple-making.
- Allowed overlap: church, discipleship, compassion and service.

### 11. `compassion_generosity_service`

**Label:** Compassion, generosity & service

Discussion of mercy, generosity, direct aid, care for vulnerable people, or
practical service to others.

- Include: helping people in need, charitable giving, hospitality, mercy,
  volunteering, direct care.
- Exclude: evangelism whose principal purpose is proclamation; structural or
  public justice when society is the developed subject; abstract moral
  evaluation without concrete care or service.
- Allowed overlap: relationships, mission, ethics, society and public life.

### 12. `suffering_adversity_death`

**Label:** Suffering, adversity & death

Discussion of grief, illness, persecution, tragedy, hardship, mortality,
endurance, or consolation amid suffering.

- Include: bereavement, chronic illness, persecution, trials, disaster,
  mortality, lament, endurance.
- Exclude: sin merely producing consequences; the doctrinal state of the dead
  when suffering or mortality is not the developed concern.
- Allowed overlap: God, salvation, discipleship, eschatology.

### 13. `ethics_moral_conduct`

**Label:** Ethics & moral conduct

Discussion that explicitly evaluates actions, practices, choices, or norms as
morally right, wrong, just, unjust, faithful, or sinful.

- Include: honesty, integrity, sexual ethics, violence, substance use, moral
  responsibility, individual justice.
- Exclude: spiritual growth without explicit moral evaluation; daily-life
  subjects discussed without a moral claim.
- Allowed overlap: relationships, discipleship, stewardship, public life.

### 14. `vocation_stewardship_daily_life`

**Label:** Vocation, stewardship & daily life

Discussion of work, money, possessions, time, health, education,
decision-making, responsibilities, or stewardship in everyday life.

- Include: vocation, budgeting, use of time, physical health, education,
  possessions, planning and ordinary responsibilities.
- Exclude: explicit moral evaluation without meaningful daily-life development;
  generosity as care for others may additionally or primarily be compassion.
- Allowed overlap: ethics, discipleship, compassion and service.

### 15. `human_nature_identity`

**Label:** Human nature & identity

Theological discussion of what human beings are, their dignity, purpose,
freedom, embodiment, identity, or creaturely status.

- Include: image of God, free will, body and soul, human worth, purpose, nature,
  identity before God.
- Exclude: personal biography or generic self-esteem; sin specifically as the
  human problem; relationships without theological anthropology.
- Allowed overlap: creation, sin, salvation, relationships.

### 16. `creation_origins_created_order`

**Label:** Creation, origins & created order

Discussion of creation, origins, the natural world, created order, or humanity's
responsibility toward creation.

- Include: creation accounts, origins, design, nature, environmental
  stewardship, order in creation.
- Exclude: human nature unless meaningfully tied to creation; generic references
  to God as Creator without developing creation.
- Allowed overlap: God, human nature, Scripture, Adventist doctrine.

### 17. `society_public_life`

**Label:** Society & public life

Discussion of government, politics, nations, public policy, elections,
patriotism, social structures, church-state relations, or religious liberty.

- Include: political actors and parties, law or public policy, nationalism,
  civic life, structural social questions, religious liberty.
- Exclude: private moral conduct merely occurring in society; a passing current
  event used without developing its public significance.
- Allowed overlap: ethics, compassion and service, church, Adventist doctrine.

### 18. `eschatology_prophecy`

**Label:** Eschatology & prophecy

Discussion of the Second Coming, final judgment, resurrection, heaven or new
earth, millennium, prophetic interpretation, or end-time events.

- Include: apocalyptic interpretation, signs of the end, final events,
  resurrection, afterlife, consummation.
- Exclude: death itself when mortality or grief is the subject; Jesus's return
  mentioned without meaningful end-time development.
- Allowed overlap: Jesus, salvation, Scripture, spiritual conflict, Adventist
  doctrine.

### 19. `adventist_doctrine_identity`

**Label:** Adventist doctrine & identity

Explicit discussion of denominationally distinctive Adventist teachings,
identity, history, authorities, or self-understanding.

- Include: Sabbath as distinctive doctrine, sanctuary, state of the dead,
  remnant, Great Controversy as an Adventist framework, Ellen White's prophetic
  role or authority, denominational history and identity, distinctive health
  teaching.
- Exclude: generic Christianity taught by an Adventist; merely quoting Ellen
  White without discussing her authority, role, or denominational significance.
- Allowed overlap: church, Scripture, eschatology, creation, spiritual conflict.

### 20. `spiritual_conflict_unseen_realm`

**Label:** Spiritual conflict & unseen realm

Sustained discussion of personal or cosmic supernatural beings, powers,
conflict, or opposition other than God, Jesus Christ, and the Holy Spirit.

- Include: Satan or the devil, demons, angels, spiritual warfare, supernatural
  evil, cosmic conflict between good and evil, demonic temptation or oppression,
  angelic activity.
- Exclude: ordinary temptation without developed supernatural agency; God's or
  the Holy Spirit's supernatural action; end-time events without developed
  supernatural conflict.
- Allowed overlap: Jesus, discipleship, eschatology, Adventist doctrine.

## Universal prominence rubric

Every topic uses the same five ordered Score levels:

| Level | Name | Standalone criterion |
|---:|---|---|
| 0 | Absent | The center block gives this topic no meaningful attention. |
| 1 | Incidental | The center block names, assumes, or briefly references this topic without developing it. |
| 2 | Supporting | The center block meaningfully develops this topic, but it remains subordinate to another concern. |
| 3 | Substantial | The center block sustains this topic as one of its main concerns. |
| 4 | Dominant | This topic is the primary organizing concern through most of the center block. |

All topic Scores are independent. Never lower one topic merely because another
topic also describes the passage or is more specific. The topic values are not
a composition and must not be normalized to sum to one.

Store the complete TypeSafe response for each Score: expected numeric score,
probability at every level, and confidence. The expected score alone is not an
adequate record of uncertainty. See the TypeSafe documentation for
[Score](https://docs.typesafe.ai/primitives/score.md) and
[structured question fields](https://docs.typesafe.ai/primitives/advanced.md).

## Organizational domains

The twenty topics may be displayed in four navigational domains. Domains are
not questions, measurements, rollups, or claims and must never be scored:

1. **Theology & spiritual reality:** God; Jesus; Holy Spirit; Scripture;
   spiritual conflict.
2. **Human condition & redemption:** sin; salvation; discipleship; human nature;
   suffering.
3. **Church & lived community:** relationships; church; mission; compassion and
   service; vocation and stewardship.
4. **Moral, created, public & future order:** ethics; creation; society and public
   life; eschatology; Adventist doctrine and identity.

These groupings only make the inventory easier to navigate. They do not imply
mutual exclusivity or a higher-order ontology.

## Block and context contract

- The scored target is one existing fine transcript block, normally targeting
  about 60 seconds and at most 3,200 characters.
- Structured state exposes only `leading_context`, `target_text`, and
  `trailing_context`. The unchanged `target_text` remains the measurement
  interval; the other fields are context only.
- A versioned internal context builder selects bounded leading and trailing text
  from the canonical transcript. Its current policy completes a sentence cut by
  the arbitrary target boundary and, when reliably available, includes one
  additional complete sentence on that side. Do not attach a complete adjacent
  minute.
- Outside-target context is capped at 400 characters per side. The internal
  builder records completeness and punctuation diagnostics, and must not present
  an arbitrary truncation as a complete sentence. Empty context is allowed at
  recording edges or when reliable context cannot be recovered.
- Questions must refer to the exact `target_text` field. Recording metadata,
  recording outline, `leading_context`, and `trailing_context` are not
  independent topic evidence; they may only clarify language that occurs inside
  `target_text`.
- Captions, repeated fragments, stage directions, rhetorical questions, and
  quotations must not independently manufacture a developed topic without
  sufficient center-block evidence. Lyrics may truthfully carry theological
  subjects in the raw observation; their content role and eligibility for
  preacher-level projection are separate decisions.
- Only timestamped source segments participate. Exact source segment indexes and
  the overlap with the final retained sermon window remain durable provenance.

## Content role, topic meaning, and analytical eligibility

Keep three decisions separate:

| Decision | Owner | Meaning |
|---|---|---|
| Content role | TypeSafe role pack plus localization policy | Whether the block is principal sermon, sermon-integrated prayer or Scripture, music/service prayer, administration, education, or unclear |
| Topic observation | `topics-v3-mission-discourse-boundary` | Which subjects are present and how prominent they are in the target text |
| Analytical eligibility | Deterministic projection policy | Whether and how the observation may contribute to a sermon or pastor measurement |

The role label `worship_music_or_service_prayer` includes music and song lyrics.
The topic `church_worship_community` does not include a song merely because it
is sung in worship. A sermon discussing hymnody, congregational singing, or the
theology and practice of worship may score that topic; ordinary praise lyrics
need not.

Zero retained-sermon overlap makes a block ineligible for sermon or profile
projection, but the raw observation remains stored. Simple time weighting is
not enough when excluded lyrics and retained preaching share a one-minute
target, because the topic Score is not span-attributed. Projection therefore
requires full retained coverage of the block and excludes partial or mixed
blocks. It also excludes sparse evidence and non-sermon content roles under the
versioned projection policy.

## Density and evidence reliability

TypeSafe topic prominence and transcript evidence density are separate signals.
Do not rewrite or attenuate a raw Score because a block is sparse.

Derive a versioned deterministic reliability record from the source block:

- analyzable lexical word count after recognized stage/noise markers;
- block duration and analyzable words per minute;
- retained-sermon overlap seconds and retained source segment indexes; and
- a sparse or non-analyzable flag.

Future aggregation may downweight or exclude blocks that cannot independently
support a claim. The raw topic Score must remain inspectable. A short but clear
statement may be real evidence; density affects its analytical contribution,
not the historical model answer.

## Request size and question scheduling

For a 33-block fine pass such as video 4548, twenty topic Scores add 660
questions. Together with 33 role questions and 132 existing semantic-mode
Nouls, that produces 825 question objects across the enriched fine pass. The
general block batch ceiling is six, but the declared 75-question fine-pass
budget reduces a full role+treatment+topic request to at most three blocks:
three role Choices, 12 semantic-mode Nouls, and 60 topic Scores. The last
partial batch may be smaller. Transcript state is shared within each provider
request, but question definitions and answer distributions still consume
tokens. A provider `max_tokens_exceeded` response recursively splits only the
failed batch; provider batch composition remains outside per-block cache
identity.

Coarse discovery and fine analysis remain sequential provider stages. The
coarse answers determine the plausible ranges from which fine blocks are
selected, so the fine question set does not exist until the coarse response has
been consumed. Sending both stages together would require either scoring every
minute in the recording or preselecting fine minutes without the coarse result,
defeating the coarse pass's token-saving and recovery roles.

Therefore taxonomy and scheduling are separate concerns:

- The canonical inventory contains all twenty topics.
- No topic is removed merely to reach a round number or hide request cost.
- Provider usage, latency, timeout behavior, and response completeness must be
  recorded before leaf packs are added.
- Fine batching must be controlled by a declared maximum question budget. The
  current 75-question budget produces at most three full-pack blocks and may be
  split further without changing per-block cache identity.
- TypeSafe speculative fan-out is useful for independent questions, but all
  questions in one request are evaluated. A genuine conditional leaf pack
  requires a later request over qualifying blocks.
- Do not attach the complete leaf inventory to every minute merely to reuse its
  state tokens. The repeated target/context for a bounded set of routed blocks
  is preferable to evaluating mostly irrelevant leaves across the full sermon.

See TypeSafe's
[speculative fan-out guidance](https://docs.typesafe.ai/patterns/fan-out.md).

### First-run token-efficiency goal

Cache replay is necessary but does not make an uncached sermon efficient. The
request planner must also minimize transcript-derived input sent on the first
run. Treat this as an architectural constraint before expanding the broad topic
inventory or adding more leaf packs:

- Send each coarse target block once during coarse discovery.
- Send each fine target block once in a combined role, treatment, and broad-topic
  request. Do not serialize the same target text under separate role and topic
  state keys merely because different question packs refer to it.
- A conditional leaf request may resend only its routed target blocks and bounded
  context. It must not resend the entire sermon or non-routed fine blocks.
- Do not attach the complete recording outline to every provider batch. Replace it
  with bounded batch-relevant recording context or another constant-size summary
  whose size does not grow with both sermon length and batch count.
- Adding a broad topic may add its question and answer tokens, but must not increase
  transcript/context bytes per block. If a larger question inventory reduces the
  blocks per request, shared-context repetition must remain bounded rather than
  growing once per smaller batch.
- Record provider request count, input/output tokens, block count, question count,
  and transcript/context character counts by request stage. Aggregate those fields
  per sermon so first-run efficiency is observable independently of cache hits.

The target uncached data path is therefore one coarse transcript pass, one fine
pass over coarse-selected ranges, and one additional pass only over blocks routed
to a leaf pack. Boundary refinement and recording verification may use bounded
excerpts, but not another full-transcript representation. Focused request-shape
tests must fail if fine target text is duplicated, a full length-dependent outline
is repeated per batch, or adding questions increases transcript-derived input
other than explicitly bounded context.

#### Implemented and validated on a bounded sermon (2026-10-13)

The first-run request planner now shares each fine target across role, treatment,
and topic questions; topic state carries context only. Role context uses at most
one bounded sentence excerpt on either side, and batch-relevant outline context
is bounded. Conditional salvation questions use a separately cached leaf pack
over routed blocks only. Per-stage request shape, token usage, and transcript/
context character counts are persisted with the classification, including
rejected batch attempts when the provider supplies no token count. Per-block
cache identities remain independent of provider batch composition.

Brian ran video 1046, *What Does Easter Have to Do with the Second Coming?*,
with an empty isolated inference cache and then repeated the identical forced
reclassification against that cache. The uncached run made 10 provider requests:

| Stage | Requests | Blocks | Questions | Target characters | Context characters | Input tokens | Output tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Recording gate | 1 | 0 | 1 | 0 | 254 | 815 | 91 |
| Coarse discovery | 1 | 5 | 5 | 15,197 | 314 | 7,339 | 478 |
| Fine role, treatment, topics | 7 | 19 | 475 | 15,183 | 15,931 | 221,811 | 11,979 |
| Conditional salvation leaf | 1 | 2 | 24 | 2,779 | 354 | 8,089 | 676 |
| **Total** | **10** | | | **33,159** | **16,853** | **238,054** | **13,224** |

There were no failed requests and all ten input/output token measurements were
present. The leaf pass covered two of the nineteen fine blocks; it did not send
the other seventeen. The sermon remained a high-confidence accepted sermon with
828 retained segments, no uncertain blocks, and no warnings. The exact replay
reported 65 cache hits, zero misses, and **zero provider requests**, with the
same disposition, confidence, selected window, and segment count. All 65 saved
cache identities matched their content-addressed filenames. Focused tests for
the adapter, classifier, and request shape passed (137 tests).

A provider-free comparison of the previous and implemented request states for
these persisted blocks measured 97,542 versus 44,880 state-string characters,
a 53.99% reduction. This is a structural character comparison, **not** a
measured provider-token saving against an old live run. The fine stage still
evaluated 475 questions and used 221,811 input tokens, so the character
reduction should not be read as an equal token reduction. This bounded case
proves the intended selective fan-out; another sermon could route every fine
block to a conditional leaf pass.

## Leaf-pack policy

The broad topics are routing observations, not the final theological analysis.
The architecture should support leaves now through independent pack identities,
but `topics-v1` must not contain the leaf questions themselves.

A leaf pack is a separately versioned, separately cached set of narrow
judgments over a qualifying block. It may be requested only after the broad
answer exists, because questions in one TypeSafe request cannot depend on other
answers in that request. The later request resends the selected minute and its
bounded context, but it does not resend or invalidate the role, treatment, or
twenty-topic packs.

Routing must use the stored Score distribution and declared code policy. Do not
use TypeSafe confidence as if it were topic presence: confidence measures the
concentration of the ordered-level distribution. A concentrated absent answer
can have high confidence, and a genuine topic split across neighboring levels
can have lower confidence. Candidate routing signals include expected Score and
probability mass at `Supporting` or above; thresholds remain uncommitted until
reviewed against bounded evidence.

Tentative enrichment order after projection eligibility is stable:

1. **Salvation relationships:** grace, atonement, forgiveness,
   justification, sanctification, assurance, judgment, and explicitly asserted
   relationships such as obedience as consequence versus condition.
2. **Listener directives:** trust, repent, change behavior, undertake a
   spiritual practice, witness, serve, give, participate, or take civic action.
3. **Public-life treatment:** descriptive, illustrative, theological, moral,
   critical, supportive, prescriptive, or advocative treatment.
4. **Source/material:** biblical narrative, testimony, historical example,
   quotation, and denominational source use where those distinctions solve
   reviewed ambiguity.

Do not create a universal subtopic tree simply because a leaf can be named.
Add a pack when it supports a concrete downstream statement and its triggering
broad evidence can be inspected.

### Current unresolved salvation leaves

Three of the twelve salvation relationship questions are finalized as
`block_level_unresolved`, not discarded and not awaiting an ordinary numeric
threshold:

| Relationship | Why the current detector is unresolved | Current handling |
| --- | --- | --- |
| `repentance_as_receiving_response` | Repeated calibration could recognize repentance and surrender language but did not reliably rank salvation-entry or restoration response above general confession, surrender, or spiritual response. | Preserve the raw probability; exclude it from sermon/pastor projection. |
| `obedience_as_condition_or_means` | Reviewed affirmatives occur around `0.30`–`0.51`, interleaved with reverse-direction or negative evidence around `0.36`–`0.40`. No threshold separates conduct presented as necessary for obtaining or retaining salvation from conduct presented as its evidence. | Preserve the raw probability; exclude it from sermon/pastor projection. |
| `obedience_as_consequence_or_evidence` | Fresh held-out affirmatives at `0.55` and `0.61` ranked below fresh negatives at `0.56` and `0.63`, reproducing the causal-direction inversion after the V9 wording improvement. | Preserve the raw probability; exclude it from sermon/pastor projection. |

These failures are semantic-ordering failures, not merely a shortage of examples.
Do not lower a threshold, treat an unresolved value as zero, or infer that a pastor
rejects the relationship. Ordinary classification may continue caching all three
raw judgments so naturally occurring held-out evidence remains available for
research, but they must not block repeatability testing of the nine measurable
leaves.

Reopen one of these relationships only under a separately versioned measurement
design with fresh held-out evaluation. Candidate designs include a Choice that
compares causal directions directly, a two-stage claim-extraction then direction
judgment, more bounded sermon context, or a newly validated model. More examples
under the unchanged detector may quantify its error rate, but cannot by themselves
repair an observed positive/negative ordering inversion. Of the three, revisit
`obedience_as_consequence_or_evidence` first, then repentance response, then
condition/means; this priority records tractability, not analytical importance.

## First-class cache architecture

The per-block answer cache keeps logical answer packs under independent
identities:

- sermon role pack;
- homiletic-treatment pack;
- the independently versioned broad-topic pack; and
- future leaf, directive, framing, and proposition packs.

For a new block, the request planner may batch every missing pack into one
TypeSafe call and write each returned pack separately. For an existing block,
adding or changing a topic pack must not invalidate cached role or treatment
answers.

Each topic-pack cache identity includes:

- requested and resolved model identifiers;
- exact broad-topic inventory and prominence rubric digest;
- center block text, timestamps, and source segment indexes;
- exact leading/trailing context, completeness diagnostics, and context-builder
  policy version;
- relevant recording context and question instructions; and
- density-policy version only if density affects request construction. A
  projection-only density policy does not invalidate inference.

Provider batch composition does not participate in per-block identity.
Unchanged replay must make no provider call.

## Persistence contract

Persist the raw observations under a versioned topic-analysis artifact without
changing sermon classification or boundaries. The artifact records:

- schema and question-pack versions;
- policy effect `none`;
- activation requirement
  `accepted_sermon_with_effective_reviewed_profile_membership`;
- requested and resolved model identifiers;
- block, timestamps, segment indexes, final-sermon overlap, and context identity;
- expected Score, all level probabilities, and confidence for all twenty topics;
- deterministic density/reliability fields and their version; and
- provider usage and request provenance where available.

An abstained TypeSafe-first attempt must retain topic observations just as it
retains current semantic observations. Later fallback classification cannot
silently discard already-paid-for topic data.

## Derived sermon and profile measurements

Topic observations are reusable evidence, not profile claims. A later,
separately versioned projection will:

1. intersect blocks with the final retained sermon segments;
2. apply the declared density/reliability policy;
3. derive sermon-level measurements before any profile aggregation;
4. project only through effective reviewed speaker-profile membership; and
5. aggregate sermons with an explicit equal-sermon or other declared estimand.

Candidate sermon-level measurements include:

- normalized expected prominence (`score / 4`);
- probability mass on substantial or dominant (`P(level 3) + P(level 4)`);
- reliable sermon-time coverage by topic; and
- evidence links to representative and contradictory blocks.

Do not report a percentage without naming its denominator. Topic values may
overlap and must not be presented as slices of a pie. Long sermons must not
silently dominate a pastor profile, and absence in sparse or missing analysis
must not be interpreted as absence in the preaching.

## Validation plan

### Stage 1: behavior contract

Create a small reviewed block fixture covering:

- clear absent, incidental, supporting, substantial, and dominant examples;
- routine overlaps such as Jesus with salvation and prophecy with Adventist
  doctrine;
- nearest-neighbor boundaries such as sin versus discipleship, mission versus
  service, ethics versus public life, and human nature versus creation;
- sparse captions, lyrics, quotations, negation, rejected alternatives, and
  context-only mentions;
- a performed song whose lyrics discuss God, Jesus, and salvation but do not
  discuss church or corporate worship as a subject;
- a biblical illustration whose narrative relationships are subordinate to a
  salvation point;
- a closing sermon prayer separated from the sermon by sparse caption
  fragments; and
- spiritual-conflict positives and exclusions.

Use focused unit tests and a bounded reviewed fixture only. Do not run a broad
corpus reclassification while developing.

### Stage 2: prospective sanity review

Allow normal future TypeSafe extractions to accumulate topic observations. From
those naturally collected results, prepare a bounded evidence packet showing
the center block, adjacent context, all Score distributions, density fields,
and final-sermon overlap. Review disagreements and boundary failures rather
than tuning against unlabeled aggregate distributions.

Video 4548 is the first observation in this stage, not a validation set. Preserve
its lyric blocks 52–55, prodigal-son block 69, and closing-prayer blocks 80–81
as named regression cases. Do not infer thresholds or taxonomy accuracy from a
single sermon.

### Stage 3: whole-sermon analytical validation

Before pastor-level comparison, follow the existing analytical roadmap: review
12 whole sermons across at least 4 pastors, double-review at least 4, search for
missed topic episodes, freeze model and question versions, and evaluate coverage
and boundary behavior. Topic-specific positive support must be adequate; sparse
topics remain descriptive or unsupported rather than being forced into a
comparison feature.

### Stage 4: cross-sermon stability

Only after whole-sermon validity is credible, evaluate repeatability across
independent sermon series and periods. Control topic/source confounding and keep
sermon sampling visible. A stable topic prevalence does not establish a
theological stance.

## Implementation sequence

### Completed foundation

1. A shared `topics-v1` specification generates TypeSafe questions, persisted
   inventory, display labels, and test expectations.
2. The TypeSafe block cache has independently versioned answer packs and a
   missing-pack request planner.
3. The fine pass asks twenty Score questions per target minute with bounded
   leading and trailing context.
4. The artifact persists expected Scores, complete distributions, confidence,
   provenance, density fields, usage, and request provenance with no topic
   policy effect.
5. Focused tests cover request composition, cache separation, replay, partial
   reuse, fallback retention, sparse blocks, overlap, and schema completeness.
6. One naturally processed sermon has received an initial sanity review.
7. Sparse-gap recovery rejoins a two-block integrated closing prayer across at
   most three non-separator sparse caption blocks, with explicit recovery
   provenance.
8. `topics-v2-performed-worship-boundary` clarifies that performing music does
   not establish the church/worship topic. Its cache identity is independent,
   so existing role and treatment answers remain reusable.
9. A deterministic read-only sermon projection admits only fully retained,
   non-sparse blocks with sermon content roles. It reports its eligible-time
   denominator, exclusions, and representative and counterevidence block links.
10. Final rule/semantic/verifier and identity-boundary arbitration refreshes
    overlap and projection eligibility without rerunning TypeSafe.
11. A fingerprinted JSON/Markdown review-packet generator preserves all Score
    distributions, confidence, context, density, role, overlap, and projection
    fields for the named video 4548 lyric, illustration, and closing-prayer
    cases. Unchanged packet preparation makes no provider call and reuses the
    existing artifact.
12. A deterministic profile-projection activation gate now exercises the full
    `accepted_sermon_with_effective_reviewed_profile_membership` contract. It
    binds current topic evidence to the exact sermon-window observation, follows
    direct or superseded reviewed membership to one canonical active/provisional
    profile, rejects ambiguous or missing membership, and fingerprints all
    effective inputs. The review packet exposes the result, but the gate does not
    write an aggregate or change classifier policy.
13. A frozen 21-case synthetic Stage 1 fixture covers all named prominence,
    overlap, nearest-neighbor, artifact, lyric, illustration, closing-prayer,
    and spiritual-conflict behaviors with 41 specification-derived score ranges. Its evaluator
    requests only the independently cached topic pack, validates and preserves
    complete Score distributions, fingerprints reports, and makes cached reruns
    provider-free. The reviewed `jev-1.13.0` result passes all 21 cases and all
    41 expectations. The two initial range failures were reviewed as fixture-spec
    errors under independent overlapping-topic scoring; correcting expectations
    reused all 21 cached answers and made zero additional provider requests.
14. The Stage 2 review command now works for every naturally processed sermon,
    not only the named video 4548 regression. Its versioned deterministic sampler
    selects a bounded packet of projection transitions, meaningful broad Score
    distributions, and domain-diverse positive evidence from persisted observations.
    Selection is fingerprinted, carries no pre-assigned human interpretation, and
    never calls TypeSafe. Named regression cases remain stable and independently
    selectable.
15. A separate whole-sermon selection mode reuses the same packet schema and
    cached observations while including every observed block in timeline order.
    Its independent policy version and filename preserve bounded packets and make
    missed-episode, false-positive, sparse-evidence, and projection-boundary review
    possible without another inference path. This is review infrastructure, not a
    claim that the required 12-sermon Stage 3 validation has occurred.
16. Topic review adjudication is stored separately from cached evidence. A
    deterministic draft is bound to both the packet fingerprint and exact file
    hash, protects edits from regeneration, supports compact topic-level and
    projection corrections, and freezes reviewer provenance under an independent
    review fingerprint. Whole-sermon finalization explicitly confirms selected
    block review, missed-episode search, and projection-boundary review; it does
    not silently treat packet creation as human validation.
17. Four prospective field runs exposed provider `max_tokens_exceeded` failures
    before topic observations could be persisted. The scheduler now caps full
    fine requests at 75 questions and recursively splits only token-rejected
    batches down to one block. Pack identities remain per block and independent
    of batch composition, so successful work is reusable and unrelated provider
    failures still fail fast instead of being retried as size errors.
18. The four bounded prospective packets now exist for videos 1200, 4394, 4430,
    and 4589 across four pastors. Their boundary samples and distinct topic
    profiles are broadly coherent, and eligible reviewed-profile activation works
    for 1200, 4394, and 4430 while correctly remaining unavailable for 4589.
    Video 1200 also exposed an unversioned rolling-caption artifact with 65.3%
    duplicate tokens. Reclassification now routes only legacy caption artifacts
    through the shared caption normalizer before coarse, fine, topic-context, and
    segment-boundary prompts; canonical and local-ASR inputs are not normalized
    again. Boundary choices are capped at 24 and cannot cross a separately ranked
    competing sermon component. The final verification run reused 148 cached
    judgments, made one new boundary-selection request, safely abstained on an
    unclear opening transition, and reused the unchanged topic packet. The
    conservative 197.68-second start omits roughly seven seconds of the opening
    illustration and remains explicitly medium-confidence rather than being
    forced to an unsupported boundary.
19. Four concrete Stage 2 adjudication proposals are checked in for those exact
    packet fingerprints. The shared draft workflow validates their topic and
    projection corrections, records the proposal content hash, and pre-fills a
    protected review draft without completing any human-review check. Proposal
    preparation and replay are deterministic and provider-free; stale packets or
    invalid corrections fail closed. Finalization re-resolves both the packet and
    proposal source paths and verifies their exact hashes before freezing a
    path-independent logical review fingerprint; cached TypeSafe observations
    remain immutable. The draft Markdown reuses the packet renderer to provide a
    self-contained decision guide, proposal-to-Score comparison, transcript context,
    projection evidence, and every cached distribution rather than asking the
    reviewer to infer meaning from correction JSON.
20. Stage 2 review found the general topic classification strong and isolated a
    symmetric semantic-boundary defect in `mission_evangelism_witness`: a direct
    gospel appeal to the current hearer could be mistaken for evangelism as a
    topic, while teaching that Christians are commanded to preach to the nations
    or serve as witnesses could be underestimated. `topics-v3-mission-discourse-boundary`
    changes only that topic definition: it includes teaching about the Christian
    task of witness and excludes merely performing a conversion appeal. The other
    nineteen topic definitions remain unchanged. The broad topic analysis stays
    one coherent cached pack: every block must still be evaluated against the
    changed question, and splitting one question into a separate physical cache
    would add coordination and migration complexity without avoiding that work.
21. All four protected Stage 2 adjudications were finalized against their exact
    v2 packet and proposal fingerprints. The bounded v3 validation then passed all
    23 synthetic cases and all 43 reviewed expectations on `jev-1.13.0`. The
    direct conversion appeal scored 0.02 for
    `mission_evangelism_witness` with 0.99 probability on absent, while the command
    to witness and preach to the nations scored 3.99 with 1.00 probability on
    dominant. The four-sermon replay also matched the human review: video 4394's
    appeal blocks 49, 52, and 53 fell to 0.03, 0.11, and 0.15; video 4430's
    commanded-witness block 18 rose to 2.50; and video 1200's reviewed supporting
    or incidental mission blocks landed at 1.41, 1.84, and 0.83. All four
    classifications and prospective packets carry the v3 pack identity. This is
    sufficient evidence to retain the clarified question without modifying the
    other nineteen topic definitions.
22. The Stage 3 cohort is frozen in
    `evaluation/sermon-topics/stage3-whole-sermon-cohort-v1.json`: twelve accepted
    sermons, three each for David P Ryder, Rusty Williams, Ron Clouzet, and John
    Bradshaw. Selection requires an existing extraction, explicit title attribution
    or reviewed speaker evidence, no duplicate selected recording, and useful topic
    and recording-context variation. The four Stage 2 sermons are the designated
    double-review set. Eight additional sermons require a v3 refresh before all
    twelve whole-sermon packets can be generated.
23. All twelve frozen-cohort v3 packets now exist. A read-only adversarial audit
    of their 618 blocks found no second semantic-boundary defect warranting a
    question revision. `discipleship_spiritual_formation` remains a monitoring
    boundary because one projection-ineligible children's exhortation and a few
    mixed blocks are plausibly high by one level, while the wider high-score set
    consistently develops growth, surrender, prayer, practice, or
    transformation. `adventist_doctrine_identity` keeps artifact and
    institutional mentions incidental while its supporting evidence develops
    actual distinctives or identity. `vocation_stewardship_daily_life` has an
    expected level-1 baseline from ordinary daily-life language, but its
    supporting-or-higher mass remains selective. The latter is an aggregation
    interpretation constraint, not a question defect: future profile summaries
    must use supporting-or-higher probability as the primary developed-emphasis
    measure and retain expected prominence as a secondary sensitivity measure.
    The evidence and decision are frozen in
    `evaluation/sermon-topics/stage3-topic-boundary-audit-v1.md`; no provider
    call, cache invalidation, or rerun was needed.
24. The first topic profile projection now reuses the generic immutable sermon-
    and profile-analysis cache instead of introducing a topic-specific store.
    Each eligible cached topic artifact materializes once under its exact topic
    fingerprint, retains representative and counterevidence excerpts, and is
    reused until that topic evidence changes. The profile layer is fingerprinted
    over exact effective membership, every in-scope projection gate (including
    blocked sermons), the aggregation policy, and the content fingerprints of
    its sermon inputs. It fails closed on mixed question-pack or projection
    versions and reports blocked sermons rather than silently dropping them.
    `pte analysis topic-summarize-profile --profile-id ...` uses an equal-sermon
    mean, makes supporting-or-higher probability the primary developed-emphasis
    measurement, preserves normalized expected prominence only as a sensitivity
    measure, and reuses both cache layers on unchanged replay. Its stored and CLI
    status remains `exploratory_stage4_repeatability_pending`, with comparative
    use explicitly disabled until Stage 4.
25. `pte analysis topic-stability-readiness` now audits the frozen cohort without
    inference or analytical writes. It binds the result to the exact cohort and
    current per-video projection-gate fingerprints, requires one reviewed
    effective speaker profile per pastor, requires every selected sermon to be
    projection-eligible on the frozen question pack, and requires at least two
    declared series and periods without inventing missing dates. The Stage 3
    manifest now records the known series and title-supported period strata and
    accurately marks all twelve v3 analyses present. The current read-only audit
    blocks Stage 4 for concrete reasons: David P Ryder spans profiles 117 and
    268; Rusty Williams spans 80 and 273; Ron Clouzet spans 130 and 263; John
    Bradshaw's videos 4312 and 4317 have `review_required` dispositions while
    4589 lacks effective profile membership. Ryder, Clouzet, and Bradshaw also
    lack enough trustworthy period metadata. These are identity, disposition,
    and sampling prerequisites; the implementation does not bypass them by
    grouping titles or pastor names.
26. `pte analysis evaluate-topic-stability` is prepared behind that readiness
    gate. It materializes or reuses only the immutable sermon-topic cache entries
    already admitted by reviewed profile membership, binds its report to their
    content fingerprints and the readiness fingerprint, and exactly reuses an
    unchanged JSON/Markdown report. For every topic and pastor it keeps the
    individual sermon values and declared sampling strata visible, then reports
    equal-sermon means, leave-one-sermon sensitivity, between-series deltas, and
    between-period deltas for both the primary supporting-or-higher probability
    and the expected-prominence sensitivity measure. The evaluator deliberately
    emits `diagnostic_only_threshold_not_calibrated` and leaves comparative use
    disabled: no stability cutoff is invented before the reviewed cohort is
    ready and its observed diagnostics can be interpreted.
27. Stage 4 preserves the immutable Stage 3 cohort and uses a separate explicit,
    fingerprinted twelve-sermon snapshot. The snapshot records the Stage 3 source
    hash, source-backed period evidence for every sermon, and every deliberate
    replacement. Video 1037 supplies Ron Clouzet coverage from an independent H1
    series, while same-half video 1033 remains in the reviewed Stage 3 cohort.
    Replacement sermons receive no eligibility from their titles or cohort slot:
    disposition, reviewed effective identity, the current question pack, and
    whole-sermon review evidence must still pass the same readiness gate. Cohort
    and readiness fingerprints bind date and exact review-evidence hashes plus
    every current projection gate.
28. The readiness handoff now preserves dependent topic work when a refreshed
    sermon is no longer disposition-eligible. Its single boundary-review action
    carries any pending topic-evidence reasons and prints the existing
    whole-sermon packet command only after the approved fixture-correction
    command. This keeps the review order fail-closed, avoids an otherwise
    redundant readiness round trip, and reuses the same packet generator and
    immutable TypeSafe cache rather than creating a special recovery path.
29. Transcript inspection invalidated Stage 4's two Hope for Humanity selections
    as John Bradshaw samples before Brian spent time approving their boundaries.
    Video 4312's preacher refers to Bradshaw in the third person and is addressed
    as Pastor Brian after the sermon; video 4317 contains the same preacher and a
    post-sermon handoff to Wes Peppers. The Stage 3 review remains immutable, while
    the separate Stage 4 snapshot initially replaced those recordings with
    explicitly dated and attributed videos 599 (`Separation`, 2026 H1) and 3973
    (`The Shaking`, 2026 H2). Those titles are candidate provenance, not identity
    approval. Both replacements still required refresh, review, and exact-span
    speaker adjudication with video 4589.
30. A currently accepted legacy classification can become `review_required` when
    refreshed on the frozen TypeSafe workflow, as replacement video 1037 did.
    Readiness therefore no longer presents whole-sermon packet generation as an
    unconditional second refresh step. The existing packet command is shown only
    for an `accepted_sermon` result; a `review_required` result routes back through
    the boundary-first action so the cached topic packet is generated once against
    the final reviewed classification fingerprint.
31. Stage 4 readiness now enforces ordinary production video eligibility before
    projection or review-action planning and fingerprints the duration/date inputs
    behind that decision. This exposed video 599 as a four-hour recording above
    the three-hour production ceiling; it must not have been selected or offered
    for reclassification. The frozen Stage 4 snapshot replaces it with eligible,
    explicitly dated and attributed video 281 (`The American Experiment`, 2026
    H2), preserving three independent Bradshaw series and the required two period
    strata without weakening the identity or topic-evidence gates.
32. Stage 4 readiness now distinguishes missing TypeSafe observations from
    missing human adjudication of observations that are already current. Only a
    question-pack mismatch or absent topic analysis schedules reclassification;
    a missing or stale whole-sermon review instead schedules provider-free packet
    reuse and protected draft preparation. The readiness-policy fingerprint was
    advanced so the old inference-heavy handoff cannot be mistaken for the new
    cache-aware plan.
33. Review of the replacement whole-sermon packets keeps all twenty v3 topic
    questions unchanged. The strongest apparent `god_character_action` /
    `jesus_person_work` overlap occurred in performed lyrics and therefore
    exposed a role-attribution defect before a repeatable topic-boundary defect.
    Fine-block role judgments now receive a bounded, content-addressed two-block
    neighborhood on each side so every cache identity carries stable transition
    evidence independent of provider batch composition. The generic role boundary states
    that performer identity, instrumentation, thematic alignment, and appeal
    function do not turn performed lyrics into preacher discourse; it also
    distinguishes an immediate same-preacher continuation of the concluding
    appeal from a prayer after a handoff or intervening service material. Only
    the role pack depends on this new context. Existing topic answer packs retain
    their identities. Homiletic-treatment packs now use the target block and
    question inventory rather than role-sensitive recording context; the former
    contextual identity is migrated provider-free on first access. The classifier
    prompt version makes the changed projection input fail closed until a bounded
    reclassification is run. Tests bind the semantic policy, bounded neighborhood,
    provider state, migration, and pack-isolated cache invalidation without naming
    a recording or block.
34. The bounded validation passed both sides of the role distinction. In video
    1037 the song introduction and three continuing performed blocks are now
    `worship_music_or_service_prayer` with probabilities 0.84, 0.92, 0.92, and
    0.63, so their still-valid theological topic scores are no longer preacher
    evidence. In clean control 281, the immediate concluding prayer remains
    `sermon_integrated_prayer_or_scripture` and eligible, while the subsequent
    hymn and later service prayer remain excluded. All sixty cached 1037 topic
    packs and all seventy-six cached 281 topic packs were reused. The validation
    also exposed that homiletic-treatment identities still inherited changed
    coarse-role context; the context-independent identity and migration above
    remove that accidental coupling without another provider run.
35. Follow-up review showed that the remaining excluded closing prayers were not
    caused by full-block projection. The reviewed version-1 windows themselves
    ended at 3254.0 for video 1037, before its prayer begins at 3256.0, and at
    4083.0 for video 3973, where only 9.961 seconds of the 65.67-second final
    block remained inside. The approved version-2 fixtures extend through the
    same-preacher integrated prayers to 3346.92 and 4138.709 respectively; the
    latter ends at amen immediately before the following song. The conservative
    full-block projection policy remains unchanged. The stale no-correction
    proposals for those two old packet fingerprints were withdrawn pending
    fixture application and refreshed packets; clean control 281 remains valid.
36. Applying those version-2 fixtures produced the intended semantic boundary.
    Video 1037 now retains blocks 71-72, including the preacher's immediate
    appeal and closing prayer, while the preceding song-to-appeal mixed block
    remains conservatively excluded. Video 3973 now retains block 100 through
    amen and excludes block 101, where the following song begins. The refreshed
    packets expose no warranted modal topic corrections. New no-correction
    proposals bind these conclusions to packet fingerprints `d7602e72fa87...`
    and `d91f37e1cd1f...`; 3973's separate profile-level projection gate remains
    blocked until effective reviewed identity membership is available.
37. Brian approved and finalized the corrected 1037 and 3973 packets and clean
    control 281 with all required checks complete and no topic or projection
    corrections. Their reviewed packet fingerprints are `d7602e72fa87...`,
    `d91f37e1cd1f...`, and `e4b208c89661...` respectively.
38. `stage4-replacement-topic-reviews-v1.json` now preserves the three compact
    reviewed decisions separately from the cached observations. The frozen
    cohort maps videos 281, 1037, and 3973 to that evidence bundle and pins its
    SHA-256 `bb431800d495...`. The bundle retains source-packet, source-review,
    and review fingerprints without duplicating the block-level TypeSafe data.
39. Structured Stage 4 review evidence is now validated as well as hash-pinned.
    The cohort's `topic-review-bundle-v1` format requires exactly its declared
    videos, finalized review status, all three whole-sermon checks, reviewer
    provenance, correction lists, and packet/review hashes. Legacy narrative
    audit evidence remains supported without duplicating its established path.
40. Readiness fingerprint `4d5b0e3a8396...` confirms that topic evidence is now
    current for all twelve sermons. Ron Clouzet advanced from 2/3 to 3/3; David
    P Ryder, Rusty Williams, and Ron Clouzet are blocked only by two effective
    profiles each. John Bradshaw's three sermons remain unbound. The five
    requested current-fingerprint pair reviews have no existing exact draft,
    review, or fixture to reuse. They are the minimum identity handoff: one
    bridge for each split pastor and two edges connecting Bradshaw's three
    components. No topic reclassification is scheduled.
41. The first identity handoff exposed offline archive storage, not an
    ineligible cohort sermon: all nine pair members have authoritative audio on
    `/Volumes/home/SermonExtractorAudio`, and that mount was unavailable. The
    pair-review command now resolves audio inside its existing CLI error boundary,
    converting `archived_media_unavailable` into a normal actionable parameter
    error instead of a traceback. It neither reconstructs nor redownloads audio;
    the immutable archive remains authoritative and the review retries after the
    mount is restored.
42. Brian approved all five exact-span identity pairs as `same_speaker`. Their
    first registry synchronization exposed a lineage-reuse defect: the reviewed
    current observations were placed in new profiles while readiness also
    inherited the older reviewed profile from each reclassified video, producing
    artificial ambiguity despite zero pair conflicts. Reviewed-component sync
    now includes each current observation's single canonical inherited profile,
    merging cached lineage instead of manufacturing a parallel identity. It
    still fails closed when one observation inherits multiple canonical profiles
    or when a different-speaker constraint blocks the merge. Replaying the same
    immutable reviews added no profiles, reconciled five profile lineages, and
    made all twelve sermons ready under one profile per pastor. Readiness
    fingerprint `3b8763eea4ec...` is `ready`: David P Ryder profile 117, Rusty
    Williams profile 80, Ron Clouzet profile 130, and John Bradshaw profile 318.
    The remaining `ron clouzet`/`ron couzet` warning is an explicit-attribution
    spelling conflict, not an identity, eligibility, or topic-analysis blocker.
43. The cached Stage 4 evaluator completed without a provider call and wrote
    fingerprint `7f693aec7881...`. It shows both kinds of behavior the broad
    layer must preserve: several developed core themes have small deletion
    sensitivity, while known sermon-specific subjects produce isolated spikes
    (Ron Clouzet video 1037 on eschatology, John Bradshaw video 281 on public
    life, and video 4589 on spiritual conflict). This supports sermon discovery
    and deterministic conditional leaf routing. It does not support stable
    pastor comparison: every declared series has one sermon, and one of each
    pastor's two periods has only one sermon. The fingerprint-bound interpretation
    is frozen in `stage4-topic-stability-audit-v1.md`; report status remains
    `diagnostic_only_threshold_not_calibrated` and comparative use remains
    disabled.
44. Salvation-routing calibration v1 reused all 518 projection-eligible cached
    blocks and called no provider. Its clear route and incidental strata
    validated `P(salvation_gospel >= Supporting)` as the conditional leaf
    signal, but the proposed `0.70` boundary rejected two genuine leaf cases at
    `0.69` and `0.67`. Audit fingerprint `3a296603f350...` therefore retains
    the signal, rejects the boundary, and leaves routing inactive. The v2
    proposal lowers the boundary to `0.65` and samples only four new boundary
    cases; it does not repeat the eight already-resolved clear anchors.
45. Salvation-routing calibration v2 found all four boundary cases at `0.64` to
    `0.66` warrant the leaf pack. Fingerprint `530364ff1050...` therefore rejects
    `0.65` while retaining the signal and leaving routing inactive. Instead of
    continuing in five-point increments, v3 performs one cached descending
    search with two deterministic, previously unused cases near each of `0.60`,
    `0.55`, `0.50`, and `0.40`. It also reports the projected request count at
    each level so semantic recall and provider cost can be assessed together.
46. Salvation-routing calibration v3 located the transition region. All probes
    at `0.54` or above warrant the leaf pack, both `0.50` probes are primarily
    narrative setup or discipleship, and the two `0.40` probes split. Fingerprint
    `79871cce90a5...` approves the untuned `0.55` operating boundary, routing
    126/518 eligible blocks. Rusty Williams video 590 block 26 is frozen as a
    known `0.40` false negative, not a production exception, because another
    `0.40` block is correctly excluded. The versioned
    `salvation-relationships-v1` inventory now defines twelve independent
    relationship judgments and a deterministic route decision; provider
    execution remains disabled until its bounded review workflow is ready.
47. The first twelve-case leaf review found the `0.55` router serviceable but
    imperfect: three of four threshold cases warrant the leaf, while David P
    Ryder video 4052 block 103 is a false positive. Raising the route would lose
    reviewed useful cases, so the boundary remains fixed and the false positive
    is frozen. The leaf judgments are useful overall, but four evidence boundaries
    require a paired revision: sanctification must not be inferred from repentance,
    surrender, healing, or forgiveness alone; justification must not be inferred
    from forgiveness, grace, or non-merit alone; divine initiative must not be
    inferred from forgiveness alone; and direct sin-bearing must count as atoning
    work. The other eight questions remain unchanged. V2 reruns the identical
    twelve targets under a new leaf-only cache identity.
48. The paired v2 leaf review passed. The four revised questions corrected the
    observed overclaims and atonement miss while preserving strong relationships
    in the clearest passages. The known false route at David P Ryder video 4052
    block 103 produced no leaf probability above `0.44`, supporting a
    recall-oriented router followed by a more discriminating leaf pack. V3 keeps
    the exact `salvation-relationships-v2-evidence-boundaries` questions and
    `0.55` route but excludes all twelve development cases, selecting fresh
    threshold, median, and strongest blocks per pastor for an out-of-sample check.
49. The unchanged leaf pack and `0.55` route passed the twelve-case out-of-sample
    review. The retained questions discriminate among salvation relationships,
    and a marginal broad false route produced no specialized probability above
    `0.36`. Three debatable leaf scores remain observations for collection-policy
    calibration, not reasons for more prompt tuning. The questions and broad route
    are now frozen. A provider-free boundary packet combines the v2 and v3 raw
    probabilities and pairs the nearest judgment below `0.70` with the nearest
    judgment at or above it for each leaf. This calibrates only the code-owned
    affirmative-observation threshold and does not rerun TypeSafe.
50. The universal `0.70` observation-threshold hypothesis failed. Independent
    Noul questions exhibit different empirical probability ranges: a defensible
    `obedience_as_consequence_or_evidence` observation scored `0.62`, while other
    leaves show clean semantic separation around `0.70`. Seven leaves retain a
    provisional `0.70` boundary. A second provider-free packet restricts review
    to five ambiguous leaves and their relevant cached probability windows:
    grace, final destiny, faith, assurance, and obedience as consequence. Final
    thresholds will be stored per relationship while raw probabilities remain
    policy-independent cached evidence.
51. The focused per-relationship review settles eleven boundaries: atonement,
    forgiveness, justification, conversion, sanctification, repentance, and
    obedience-as-condition at `0.70`; divine grace, final destiny, and faith at
    `0.65`; and assurance at `0.55`. Obedience-as-consequence remains unresolved
    because its reviewed scores intermix positives and negatives. The existing
    cache contains no unreviewed v2 leaf answers, so a final cache-first command
    deterministically selects twelve fresh routed blocks with explicit
    consequence/evidence cues, caps selection at three per pastor, and presents
    at most six new answers in the `0.55`–`0.65` window. It changes no production
    policy and replays from the normal per-video cache after the first run.
52. The final obedience-as-consequence calibration settles the last boundary at
    `0.55`. Although only two fresh cases fell inside `0.55`–`0.65`, both were
    affirmative, and the wider fresh sample supplied strong positive anchors at
    `0.80` and above. The complete policy is frozen as
    `salvation-relationship-observation-thresholds-v1`: seven leaves at `0.70`,
    divine grace/final destiny/faith at `0.65`, and assurance plus
    obedience-as-consequence at `0.55`. Ordinary TypeSafe reclassification now
    routes projection-eligible salvation blocks at `0.55`, evaluates the existing
    independently cached leaf pack, persists every raw probability, and derives
    affirmative observations through the per-leaf map. These remain
    observation-only and make no profile-level theological claim.
53. Collected relationship evidence has a provider-free review path. It reads the
    ordinary classification artifacts, rejects missing or stale question/policy
    versions, verifies every stored observation by recomputing the frozen
    per-leaf threshold decision from raw probabilities, and selects the strongest
    rejected plus weakest collected judgment for each leaf. This yields at most
    twenty-four boundary probes across the twelve-sermon cohort without rerunning
    TypeSafe or pre-approving sermon- or pastor-level aggregation.
54. Production collection and provider-free verification now call the same frozen
    per-leaf policy function. It validates the complete twelve-leaf probability
    inventory and the `[0, 1]` range before returning observations in canonical
    relationship order, preventing the writer and auditor from drifting while
    leaving the raw cached judgments untouched. The production and review commands
    are documented together so the normal TypeSafe defaults, conditional routing,
    observation-only effect, and zero-provider replay contract are explicit.
55. Relationship-pack cache replay now validates the frozen question version,
    complete twelve-leaf probability inventory, probability ranges, and stored
    context before counting a hit. A malformed or partial leaf cache is treated as
    one missing pack and repaired through the existing bounded request path; its
    valid role, treatment, and topic sibling packs remain reusable. The repaired
    pack then replays without another provider request. The same validator runs
    before writes, so an incomplete provider response fails explicitly and is never
    persisted as reusable evidence.
56. An abstained TypeSafe-first attempt now preserves its cached relationship
    artifact beside the already-preserved semantic and broad-topic artifacts when
    Ollama supplies the final classification. Every direct or fallback relationship
    artifact is then reconciled deterministically against the final refreshed topic
    projection: raw leaf probabilities remain unchanged, observations from blocks
    no longer routed by the final sermon window are deactivated, and newly routed
    blocks without leaf evidence are reported explicitly as incomplete. The review
    command can construct this same effective view in memory for a batch produced
    immediately before this change and fingerprints both stored and reconciled
    artifacts, avoiding an otherwise unnecessary provider rerun.
57. The collected-observation packet is self-contained for external review. Its
    fingerprinted JSON embeds the frozen meaning and true/false evidence boundary
    for every leaf, and its Markdown repeats those definitions beside each probe,
    explains that a Noul value is a yes probability rather than doctrinal intensity
    or a separate confidence score, and specifies the exact review response needed.
    This prevents reviewers from reconstructing semantics from terse relationship
    ids and does not duplicate the definitions outside the canonical pack inventory.
58. Collected-observation review schema/policy v2 normalizes repeated evidence.
    Each selected leaf judgment references a stable `video_id:block_id` case, while
    transcript context and recording metadata appear once in a deduplicated case
    table. The JSON and Markdown retain the same bounded strongest-rejected and
    weakest-collected decisions with materially less repeated transcript text. This
    changes only the provider-free review artifact and leaves inference and block
    cache identities untouched.
59. Collected-observation review now reports the shared Stage 4 readiness table
    and its bounded remediation commands before failing closed. The command passes
    that same immutable readiness snapshot into packet evaluation, so diagnostics
    neither duplicate readiness logic nor repeat the database audit. No TypeSafe
    request is made when an ineligible or non-accepted cohort sermon blocks review.
60. Human-reviewed sermon windows now participate in the initial topic projection
    used to plan conditional salvation-leaf fan-out. Automatic boundary discovery
    remains independent and unchanged, but a reviewed window can make additional
    already-scored topic blocks profile-eligible; those blocks now receive only the
    missing leaf pack during the same classification pass. The per-block pack cache
    remains authoritative, so a replay makes no provider request. This closes the
    gap where final reconciliation correctly exposed a newly routed block but an
    identical forced reclassification could not populate its leaf evidence.
61. The first ordinary-classification collection review does not approve the full
    threshold table. Eight leaves are frozen at their existing boundaries;
    sanctification stays at `0.70` with `4589:50` retained as a false-negative
    watch fixture. Assurance, receiving faith, receiving repentance, and obedience
    as consequence remain unsettled. Their reviewed boundary anchors include false
    positives in all four leaves and a repentance inversion (`0.69` affirmative
    below a `0.71` negative), so no blanket numeric adjustment is applied. A
    provider-free follow-up selects eighteen fresh cached judgments: two per side
    for three leaves and three per side for repentance, preferring pastor diversity
    and excluding the eight already reviewed anchors. The follow-up is fingerprinted
    to the reviewed packet and current source artifacts and changes no inference
    policy.
62. The four-leaf follow-up localizes the remaining work without changing any
    numeric boundary. Assurance keeps its question and will search upward from
    `0.59` using unused cached v2 judgments. Receiving faith, receiving repentance,
    and obedience as consequence receive narrower evidence boundaries in
    `salvation-relationships-v3-receiving-and-fruit-boundaries`: faith must be the
    means of receiving a saving benefit; repentance must be repentant confession
    or turning rather than generic decision, surrender, or perseverance; and
    consequence-obedience must identify conduct, works, holiness, or changed
    behavior as fruit or evidence rather than generic transformation. A single
    bounded calibration command reuses the shared pack cache and evaluator, reruns
    the fourteen reviewed semantic probes, adds twelve fresh held-out boundary
    probes, and presents six provider-free assurance candidates. Thresholds and
    production observation policy remain unchanged until that packet is reviewed.
63. Semantic calibration v1 approves two leaves and narrows the final check to two.
    Assurance moves from `0.55` to `0.62` under
    `salvation-relationship-observation-thresholds-v2-assurance`, based on reviewed
    negatives through `0.59` and the first clear affirmative at `0.62`.
    Obedience-as-consequence freezes the v3 wording at `0.55`. Receiving-faith keeps
    the v3 wording but remains provisional because every regression and held-out
    probe was negative. Repentance v3 failed its ordering criterion, so v4 restores
    surrender or yielding only when explicitly contrasted with surrender to sin or
    tied to entering God's kingdom, receiving God's indwelling presence, or another
    saving benefit. The final bounded packet evaluates two reviewed affirmative
    faith anchors plus four strongest prior candidates and reruns the three decisive
    affirmative and three negative repentance cases. No cohort reclassification is
    authorized until both checks pass.
64. Final calibration passes both remaining checks and freezes the relationship
    layer. Receiving-faith preserves clear affirmative recall at `0.76`–`0.88`
    while leaving a preacher-identified repentance/surrender case below its `0.65`
    boundary. Repentance v4 restores correct ordering: reviewed affirmatives score
    `0.57`, `0.58`, and `0.87`, all above reviewed negatives at `0.26`, `0.42`,
    and `0.55`. Freeze repentance at `0.57`, assurance at `0.62`,
    obedience-as-consequence at `0.55`, grace/final-destiny/faith at `0.65`, and
    the remaining seven leaves at `0.70` under
    `salvation-relationship-observation-thresholds-v3-final`. The broad route stays
    `0.55`, the raw probabilities remain policy-independent, and no more prompt
    tuning should use this calibration corpus.
65. The refreshed ordinary-classification review reopens only four localized
    boundaries. Grace initiative, conversion/new birth, obedience as condition,
    and obedience as consequence each show a reviewed affirmative or questionable
    rejection at or below a questionable collected case; threshold movement alone
    cannot resolve those orderings. Seven other leaves pass, including the newly
    calibrated faith, repentance, and assurance boundaries. Final destiny retains
    one likely affirmative `0.62` rejection as a watch case because its `0.66`
    collected boundary is also affirmative. A provider-free follow-up keeps all
    questions and thresholds unchanged, combines the eight named boundary anchors
    with two fresh cached judgments on each side of each affected threshold, and
    includes final destiny only as a non-authorizing watch probe.
66. Fresh cached neighbors confirm semantic-ordering defects in all four reopened
    leaves, so no threshold changes are authorized. V5 sharpens divine initiative
    to the divine origin or supply of saving benefit; conversion to entry through
    new-heart/new-life/Christ-entering language rather than the later life of the
    already saved; condition-obedience to conduct causally necessary for salvation,
    justification, retention, or final acceptance rather than sanctification or
    discipleship prerequisites; and consequence-obedience to an explicit saving
    benefit-to-subsequent-conduct chain rather than conversion, generic
    transformation, or non-conduct evidence. The other eight questions and every
    threshold remain frozen. A bounded cache-first packet reruns all twenty-four
    labeled v4 probes and adds sixteen fresh held-out neighbors before any policy
    adjustment.
67. V5 review freezes all four revised question meanings. Divine initiative now
    separates divine supply from human response, conversion separates entry into
    saving life from later conduct, condition-obedience cleanly rejects surrender
    and discipleship prerequisites, and consequence-obedience recognizes its
    canonical salvation-to-conduct case. Conversion's `0.70` boundary is rejected
    because reviewed affirmative evidence extends to `0.54`; the other three
    boundaries remain plausible but unapproved. A final provider-free packet reads
    fingerprint `b7e52b68d97c...`, includes every conversion judgment from `0.45`
    through `0.70`, and adds four nearest boundary judgments for each other revised
    leaf. It changes neither inference nor collection policy.
68. Final numeric review freezes the v5 observation policy. Divine initiative
    remains `0.65` and obedience-as-condition remains `0.70`. Conversion moves
    from `0.70` to `0.54` to retain the clearest new-life transition evidence,
    knowingly leaving one affirmative `0.51` case uncollected and accepting noisy
    negatives above the boundary. Obedience-as-consequence moves from `0.55` to
    `0.60`, excluding the reviewed `0.54` negative while accepting that one
    affirmative and one negative both score `0.61`. These overlaps are frozen as
    measurement limitations, not prompt-rewrite targets. The production policy is
    versioned as `salvation-relationship-observation-thresholds-v4-v5-final`; raw
    probabilities and the v5 question pack remain unchanged.
69. The first ordinary-classification pass under v5 validates eight leaves but
    does not yet approve collection. Repentance shows a semantic inversion between
    `4394:45` (`0.55`, affirmative rejected) and `350:50` (`0.57`, negative
    collected). Conversion's first collection at `4394:51` (`0.54`) is too weak,
    while forgiveness `4430:44` (`0.68`) and assurance `4458:69` (`0.61`) are
    material numeric misses. A final provider-free packet keeps the other eight
    leaves frozen, adds three fresh repentance neighbors per policy side, and
    samples only conversion `0.54`–`0.58`, forgiveness `0.68`–`0.70`, and assurance
    `0.61`–`0.62`. Justification `4589:48`, sanctification `3973:75`, and the known
    consequence false positive `4430:47` remain non-authorizing watch fixtures.
70. The provider-free final collection check at fingerprint
    `20c92d3e4f674771ac62b668403abba079c98fe3d69a23bc4e43e83e69d52624`
    authorizes only three numeric adjustments: conversion `0.54` to `0.55`,
    forgiveness `0.70` to `0.68`, and assurance `0.62` to `0.61`. Fresh cases
    confirm that repentance has a semantic-ordering defect rather than a numeric
    boundary problem. V6 therefore revises only repentance: the affirmative must
    function as entry into, receipt of, or restoration of saving relationship;
    later surrender, yielding, resistance to sin, and Christian growth are not
    sufficient. The other eleven questions remain frozen. Before any cohort
    reclassification, a bounded cache-first check reruns eight labeled regressions
    and tests eight genuinely fresh, pastor-diverse cases around the prior `0.57`
    boundary. The observation policy is provisional until that check passes.
71. V6 at fingerprint
    `8162cfddecbe574217364e88e86186edc0b748522fb20cd2c54b756f372f13a7`
    substantially improves the post-conversion boundary, but it still ranks two
    salvation-context negatives above an explicit restoration-oriented repentance
    positive. No threshold can repair that inversion. V7 makes the final authorized
    semantic change: observe whether repentance, confession, turning, or surrender
    is presented as the human response within a salvation-entry or restoration appeal
    or explanation. It explicitly forbids inference from nearby sin, forgiveness,
    salvation, or coming-to-Christ language and continues to exclude post-conversion
    growth. All sixteen V6 cases become labeled regressions and eight new cases are
    held out. If clear fresh positives do not rank above clear fresh negatives, stop
    prompt tuning and record the block-level measurement limitation.
72. V7 at fingerprint
    `74962cf53f10205904aa19c7409ac8475d11c97fd36a61c69f938b05c00ed5e2`
    fails that terminal ordering criterion. Known negatives at `0.75` and `0.82`
    overlap or exceed a clear affirmative at `0.76`; no numeric boundary can
    represent the intended construct. Stop repentance prompt tuning. Retain the raw
    V7 Noul probability with measurement status `block_level_unresolved`, but exclude
    it from collected and pastor-level observations. Freeze the other eleven leaves:
    assurance `0.61`, atonement `0.70`, conversion `0.55`, divine grace `0.65`,
    receiving faith `0.65`, forgiveness `0.68`, final destiny `0.65`, justification
    `0.70`, obedience-as-condition `0.70`, obedience-as-consequence `0.55`, and
    sanctification `0.70`. This final policy supersedes the earlier provisional
    consequence boundary and is versioned as
    `salvation-relationship-observation-thresholds-v7-eleven-leaf-final`.
73. The first deduplicated ordinary-classification audit under that policy, at
    fingerprint
    `79ff2192909c0137c98529893a3460409997416f4685e2bd569b066b5714a047`,
    reopens only `conversion_new_birth`. Its reviewed positive `590:34` scores
    `0.54` and is rejected while reviewed negative `350:42` scores `0.55` and is
    collected. Keep the configured `0.55` threshold unchanged while a provider-free
    packet checks four fresh cached neighbors on each side in `0.45`–`0.65`. Freeze
    the other ten thresholded leaves. Record their six isolated misses or false
    positives as watch-only fixtures that cannot authorize changes in this packet.
    If the fresh conversion evidence does not reveal a systematic repairable
    ordering defect, accept local measurement noise, freeze `0.55`, and proceed to
    pastor-level aggregation.
74. The conversion-only packet at fingerprint
    `767d08880a0ced5c2ba4bd519f4944d6a1728c799d905c0a5d076ae374f04003`
    reproduces a systematic semantic-ordering defect. All four fresh cases below
    `0.55` are negatives, while fresh negatives at `0.55`, `0.56`, and `0.58`
    precede a strong affirmative at `0.60`; the prior strong affirmative at `0.54`
    prevents a numeric repair. V8 therefore revises only `conversion_new_birth` to
    require an asserted entry or state transition into saving life. Forgiveness,
    freedom from sin, surrender, prayer for salvation, baptism, repentance, or the
    word converted do not establish conversion without that transition. Regressions
    are positives `590:34` and `350:41`, and negatives `350:42`, `4430:21`,
    `4589:51`, and `4430:53`. Validate them with eight fresh held-outs selected from
    saved V7 probabilities. Keep `0.55` provisional, the other ten thresholded
    leaves frozen, and unresolved repentance excluded.
75. V8 at fingerprint
    `39555a590061e1f93342983d2a0030dde847b28369a8693651be0a6fe2fd56e7`
    passes and is frozen. The two affirmative regressions rise to `0.75` and `0.71`;
    all four negative regressions fall to `0.23`–`0.46`. Seven of eight held-outs
    are cleanly ordered for policy purposes: the clear positive `4052:91` is `0.78`,
    every clear negative and both ambiguities are below `0.55`. Keep the conversion
    threshold at `0.55`. Record `4394:43` at `0.20` as a false-negative watch and
    `590:52` / `4589:50` as ambiguity watches; none authorizes more prompt tuning.
    Version the frozen collection policy as
    `salvation-relationship-observation-thresholds-v8-eleven-leaf-final`, archive
    V8 calibration, and refresh the twelve-sermon cohort through ordinary cache-aware
    reclassification before pastor aggregation.
76. The post-V8 ordinary-classification review at fingerprint
    `f948ffcb5940a79dee4469afdb6b1cb43067243792cb644f06f2361468ad3491`
    confirms conversion V8 at `0.55`, but does not approve the whole collection
    policy. Reopen atonement numerically only in `0.66`–`0.71`: `281:124` at `0.68`
    is a material affirmative miss. Check judgment provider-free in `0.62`–`0.68`,
    with `4394:43` at `0.66` labeled negative, before deciding whether its single
    false positive is tolerable overlap. Revise only consequence-obedience in V9:
    count baptism or union with Christ leading to walking in newness of life or
    Christ living through the person, but exclude declared freedom or changed status
    without named subsequent conduct. Regressions are affirmative `4589:41` at
    `0.54` and negative `4430:28` at `0.56`, plus eight fresh held-outs. Keep
    `1037:58` condition-obedience ambiguous until the garbled audio phrase is
    resolved. All other measurable leaves remain frozen.
77. The final bounded packet at fingerprint
    `557f9742ddb820e4079ec90f26f3a835e7ddfdeda235c2cff63d5038ba1957a7`
    passes V9 consequence-obedience semantics: affirmative regression `4589:41`
    rises from `0.54` to `0.84`, while negative `4430:28` falls from `0.56` to
    `0.17`. Freeze that wording at `0.60`, accepting the subtle affirmative
    `590:38` at `0.52` as a retained raw false negative and `350:62` at `0.67` as
    borderline overlap. Move atonement from `0.70` to `0.68`; retain judgment at
    `0.65` and record negative `4394:43` at `0.66` as a known false positive.
    Archive the calibration command. Version the collection policy as
    `salvation-relationship-observation-thresholds-v9-pending-condition-transcription`
    until the garbled `1037:58` audio is adjudicated; do not reclassify before then.
78. The exact corrupted word in `1037:58` is “usurp.” In context, the preacher says
    that spiritual sleep can override or defeat God's intended saving outcome, so
    the case is affirmative for `obedience_as_condition_or_means`. Its `0.51`
    probability is the strongest cached judgment and exposes a numeric miss against
    the current `0.70` boundary. Do not revise the unchanged question or call the
    provider. Build one provider-free packet from the twelve highest cached V8
    probabilities, with `1037:58` as the reviewed affirmative anchor, before
    finalizing this last measurable leaf.
79. The provider-free condition/means review at fingerprint
    `935cf0b8183f149f4080247f90cdda6268ebdb68d81ee8f1c66d165f336e0b63`
    does not support a numeric projection boundary. Affirmatives occur at `0.51`,
    `0.42`, `0.36`, `0.34`, and `0.30`, while reverse-direction evidence occurs at
    `0.40` and a negative occurs at `0.36`. Mark
    `obedience_as_condition_or_means` as `block_level_unresolved`, alongside
    repentance. Preserve both raw probabilities, exclude both from pastor-level
    projection, and never interpret unresolved as zero or theological opposition.
    Do not create V10. Freeze the remaining ten leaves under
    `salvation-relationship-observation-thresholds-v9-ten-leaf-final` and archive
    the condition-boundary command.
80. The refreshed ordinary-classification review at fingerprint
    `a9f8f419dd4b61c84ac0f997b62fc1e3f4d874a0ec5e55354b53d2e59287e02a`
    freezes nine measurable leaves but reopens
    `obedience_as_consequence_or_evidence` only. Regression `4394:52` is a clear
    affirmative rejected at `0.59`; `350:42` is generic transformation collected
    at `0.61` despite not naming subsequent conduct. Keep V9 wording and `0.60`
    unchanged while building one provider-free packet with those two anchors and
    eight fresh cached neighbors in `0.45`–`0.70`. Version the interim policy as
    `salvation-relationship-observation-thresholds-v9-pending-consequence-review`.
    If fresh ordering repeats the inversion, mark this leaf unresolved; if it
    separates cleanly, make one final numeric decision. Do not reopen the other nine
    measurable leaves.
81. The provider-free consequence/evidence review at fingerprint
    `9543eae8eac75482b9430069d5b9905a114ae0ee5513e34184d1ed4930134ad5`
    reproduces the ordering inversion on eight fresh cases. Clear affirmatives at
    `0.55`, `0.61`, and `0.67` interleave with clear negatives at `0.49`, `0.50`,
    `0.56`, and `0.63`; `0.53` is ambiguous. No threshold can recover the positives
    without admitting the negatives. Mark
    `obedience_as_consequence_or_evidence` as `block_level_unresolved`, preserve its
    raw V9 probability, and exclude it from pastor projection without treating it as
    absent or opposed. Do not create V10. Freeze the nine remaining measurable leaves
    under `salvation-relationship-observation-thresholds-v9-nine-leaf-final` and
    archive the consequence-boundary command.
82. The refreshed ordinary-classification packet at fingerprint
    `7865d2213837191ea50764fddfa93df591434e19911e13d6a6c097a5a16aa8fd`
    passes final human review across 1,134 cached judgments and 126 routed blocks.
    Freeze the nine-leaf collection policy. Record
    `590:34:faith_as_receiving_response` at `0.64` as an isolated affirmative miss
    below the `0.65` boundary, not as authority to fit the threshold to the known
    sample. End salvation leaf calibration and proceed to provider-free,
    equal-sermon aggregation and repeatability diagnostics. Keep the three
    unresolved leaves unavailable rather than zero-valued.
83. The first three-sermon profile diagnostic validates equal-sermon aggregation but
    does not validate repeatability. Zero detections are insufficient positive
    evidence, not stable absence. Series deltas are sermon ranges because every
    series is a singleton, and period deltas confound time with a one-versus-two
    sermon split. Preserve those values as descriptive diagnostics while marking
    their replication insufficient. Build a provider-free candidate inventory for
    a twelve-sermon-per-pastor convergence cohort, targeting at least three series
    with within-series replication and multiple replicated periods. Estimate
    convergence per relationship at sample sizes `3, 4, 5, 6, 8, 10, 12`; do not
    calibrate a repeatability threshold from the three-sermon sample.
84. The first expansion inventory at fingerprint
    `211d807550464b837dfa832f10cc7a8cdbc6b0349756b8014faf0d400ac190e3`
    is blocked on data availability: three pastors expose only the three baseline
    candidates, and Ron Clouzet exposes four. Keep the twelve-sermon replicated
    series/period design unchanged. Do not infer dates from titles. Carry reviewed
    baseline period evidence forward when database `published_at` is null, then run
    a provider-free discovery audit that separates ingestion, canonical identity
    linkage, production eligibility, analytical gate failures, query parity, and
    metadata provenance before considering new acquisition or reclassification.
85. The candidate-discovery audit at fingerprint
    `0a9074ef6546e7613d00cae42491192ca7d65a0dc1c81470f8729f9ff084e40e`
    confirms downstream analytical scarcity rather than source scarcity or query
    filtering. Exactly 32 production-eligible, canonically linked recordings for
    profiles 117, 80, and 130 are blocked solely by
    `topic_analysis_unavailable`; prepare a cache-aware forced reclassification plan
    for those recordings only. Profile 318 has no linked analytical-gate targets and
    will remain short after this phase. Do not include configured-but-unlinked videos,
    infer series, or change identity. Refresh the inventory and audit after the
    backfill, then decide whether a separate bounded identity phase is necessary.
86. The 32-video analytical backfill is complete. The refreshed provider-free
    inventory at fingerprint
    `013fcb89dc906d5fc124742ce81fea4872e1f971451501e8b94aaabd4e088084`
    exposes 12 candidates for profile 117, 13 for profile 80, 15 for profile 130,
    and 3 for profile 318. These are candidate counts, not yet independent-sermon
    cohort counts: matching-title pairs such as Ryder `418`/`419` and Williams
    `587`/`588`, `595`/`597`, and `3981`/`3983` require explicit duplicate or
    same-service adjudication, while most added candidates still lack reviewed
    series and period evidence. Do not make another provider call merely to prepare
    the cohort. Profile 318 is non-blocking for the initial three-pastor experiment.

### Exact-cohort integrity review and contract revision

The provider-free [v2 proposal](../evaluation/sermon-topics/salvation-exact-cohort-proposal-v2.json),
[integrity review](../evaluation/sermon-topics/salvation-exact-cohort-integrity-review-v1.json),
and [targeted gate review](../evaluation/sermon-topics/salvation-exact-cohort-targeted-gaps-v1.md)
established the independence and provenance facts. Ryder 418/419 are consecutive
parts of one sermon despite low transcript overlap. Three Williams pairs remain
conservatively grouped. All three pastors have two periods with at least three
sermons each. The v2 requirement for **three series with at least two sermons
per series** left Ryder two series short, Williams two short, and Clouzet one
short. It was selecting for archive organization and prompting unrelated gate
work. That series rule is **superseded**, not retroactively changed in v2.

The [v3 proposal](../evaluation/sermon-topics/salvation-exact-cohort-proposal-v3.json)
(input fingerprint
`1197f1504cc1171a4ec620582b041f8619dd4d900815350561466bd2a02ee70c`)
uses this preregistered, auditable stage gate per pastor:

1. Twelve independently counted sermons, preserving the three reviewed
   baseline sermons and counting at most one recording per unresolved or
   probable equivalence group.
2. At least two source-backed periods, each represented by at least three
   independent sermons.
3. No **documented** series contributes more than six of the twelve sermons.
   At least three distinct normalized source titles must sit outside the
   largest documented series. Unassigned series membership is displayed, not
   presumed to be a distinct series. Bounded human integrity review must check
   whether those unassigned recordings conceal a concentration risk before
   approving an exact cohort.

The series rule is a sampling diversity guard, not a claim that titles prove
independent series. The diagnostic will compare within-series and
outside-series convergence for each documented series with at least two
sermons; it will report where that comparison is unavailable. It will also
retain sermon-order and period sensitivity. Do not infer pastor-level stability
from an untested series or from zero detections. No universal stability
threshold is calibrated from the three-sermon baseline.

The v3 packet was regenerated entirely from the existing fingerprinted
artifact-evidence cache, without rereading transcripts, running a corpus job,
or calling TypeSafe. The cache identity is now independent of the cohort-policy
version so future contract-only revisions reuse it. Its current counts are:

| Pastor | Independent sermons | Replicated periods | Largest documented series | Other distinct titles | Remaining gate |
| --- | ---: | ---: | ---: | ---: | --- |
| Ryder (117) | 11 | 2 | Joseph 2/11 | 9 | One independent sermon |
| Williams (80) | 10 | 2 | Unexpected 2/10 | 8 | Two independent sermons |
| Clouzet (130) | 12 | 2 | Hurtling to the End 6/12 | 6 | None before bounded human cohort approval |

The [v2 integrity review](../evaluation/sermon-topics/salvation-exact-cohort-integrity-review-v2.json)
adds source-backed `Hurtling to the End` assignments for 1038, 1039, 1044,
and 1051, corroborated by the source titles and the 1045/1051 self-references.
Clouzet's archaeology recording 4432 remains excluded; its speaker and sermon
gates are not relaxed to satisfy a sampling rule. The three unresolved
salvation leaves remain `block_level_unresolved` and outside nine-leaf
projection and convergence. Profile 318 remains outside this initial
experiment. `analytical_credit` remains `none` before bounded human approval.

### Partial-checkpoint convergence stage gate

Freeze the v3 selection fingerprint above. The twelve-sermon target remains the
full design, but it no longer withholds the already-supported checkpoints:
Ryder has 11 independent sermons, Williams 10, and Clouzet 12. The
provider-free `pte analysis salvation-nine-leaf-convergence` command reads
their cached classification artifacts and computes nine-leaf equal-sermon
rates at every *measured* `N=3,4,5,6,8,10,12` checkpoint. Ryder and Williams
have an explicit unavailable N=12 result. A focused cached-artifact check found
that Clouzet 1033 has six currently routed topic blocks but no cached
salvation-relationship artifact. His selected N=12 therefore yields only 11
measured sermons and also has N=12 explicitly unavailable. This is an evidence
availability gap, not a reason to score 1033 as zero or silently replace it.
Ryder's N=11 is retained as a full
available-sample reference, not inserted as a new preregistered checkpoint.
The primary order starts with the three reviewed baseline sermons. A fixed
128-order permutation diagnostic checks dependence on sermon order. Period and
replicated-series inside/outside means test temporal and archive concentration
sensitivity; unknown labels stay visible. Zero detections remain insufficient
positive evidence. Five selected sermons have zero salvation-routed blocks:
Ryder 4056, Williams 597, and Clouzet 1044, 1045, and 1051. They remain in
the cohort with an explicitly zero-extended observed rate; the report identifies
them so this denominator convention can be examined. No stability cutoff is
fitted from these cohorts.

The convergence report is a diagnostic artifact and retains its original
`analytical_credit_granted: false` field as a record of the state before
interpretation. It does not silently substitute candidate recordings or call
TypeSafe. The separate stage-gate decision below gives the nine questions
broader-analysis credit without declaring these cohort sizes sufficient for
pastor-level theological claims.

### Nine-question stage gate passed

Brian's bounded review of the provider-free
[convergence report](../evaluation/sermon-topics/salvation-nine-leaf-convergence-v1.json)
(fingerprint
`3a08c5bab1f60e6d84932c0050f39b1648429bd89dc159ab296ff3a403f828f2`)
approves the **nine measured salvation relationship questions for broader
analysis**. The versioned
[decision](../evaluation/sermon-topics/salvation-nine-leaf-stage-gate-v1.json)
records this as `salvation_relationship_questions: ready_for_broader_analysis`.
Its scope is question-level use only. The three unresolved leaves remain
excluded, zero detections mean insufficient positive evidence rather than
theological absence, and pastor-level sample-size sufficiency remains a
separate calibration problem. Do not tune the nine questions or their frozen
`salvation-relationship-observation-thresholds-v9-nine-leaf-final` policy from
this experiment. No numerical convergence cutoff is retrofitted.

At the time of the stage-gate decision, Ryder contributed 11 measured
independent sermons, Williams 10, and Clouzet 11 of 12 selected. Clouzet
1033 then had six routed topic blocks but no cached leaf artifact; that
availability gap has since been closed without reopening the stage gate.
Likewise, do not seek Ryder 1194 or additional Williams sermons merely to
manufacture N=12. The convergence data show that three-sermon pastor
estimates can be misleading, notably Williams's faith response, and that
additional sermons narrow order sensitivity. That is a sampling result, not
a reason to recalibrate the nine questions.

### Cache-first broader-corpus rollout inventory

The provider-free `pte analysis salvation-broader-rollout-inventory` command
accepts only the fingerprint-valid approved nine-question stage-gate decision.
It enumerates the production-eligible corpus using the existing topic/profile
projection gate while reporting **content readiness separately from pastor
profile linkage**. Profile membership is not required for question-level sermon
analysis. It checks each content-eligible recording against the frozen V9 leaf
pack and currently routed topic blocks. It separates reusable stored
leaf evidence, legitimately zero-routed recordings, missing/partial/stale leaf
evidence, and upstream gate blockers. The JSON records video IDs, gate reason
codes, classification/topic/leaf hashes, and missing routed block IDs.

The work estimate counts missing routed leaf blocks and target-text characters.
It reports a structural zero-to-recursive-split request range because exact
local answer-pack cache hits are unknown until replay; it also reports the
minimum batch count if all packs miss, before token-driven splitting. This
range excludes transport retries and other failures. Upstream-blocked
recordings are counted but not assigned a speculative leaf cost. This is not a
token or dollar quote, and the inventory command makes **zero provider
requests**. It reuses its fingerprinted report when the database/WAL signature,
approved decision, policy, and all recorded source-file signatures match; a
changed input forces a fresh read-only inventory.

### Video 1033 completion and refreshed rollout inventory

Brian reclassified video 1033 (*Jesus and the Devil: The Archenemy*) with
`pte reclassify --video-id 1033 --recording-verifier-backend typesafe --force
--jobs 1 --base-dir /Users/briancummings/Documents/PastorSearchData` using its
per-video cache. The accepted, high-confidence classification retained 1,484
segments and recorded 97 cache hits, 65 misses, and 12 provider request
attempts: two coarse, eight fine, one boundary-selection, and one leaf. The
leaf request evaluated the six routed blocks (43, 49, 50, 54, 56, 57; 4,749
target characters), with 23,004 measured input tokens and 2,020 output
tokens. The stored leaf artifact contains all six block answers, two
collected observations, no missing currently routed blocks, and a reconciled
projection. These numbers describe the full forced reclassification; the
existing older role-pack identities caused additional coarse/fine work.

The subsequent provider-free
[`salvation-broader-rollout-inventory-v1`](../evaluation/sermon-topics/salvation-broader-rollout-inventory-v1.json)
refresh has fingerprint
`74362458ba8792db9d682f7eff541fb5f560c54065f51fcfb4b44359cce4db8d`.
All 43 content-eligible videos are now ready: 37 have reusable leaf artifacts
and six have zero routed blocks. There are no missing leaf blocks and the
inventory made zero provider requests. One immediate inventory attempt
rejected a changing application database; rerunning after it stabilized
produced this fingerprinted report. The convergence report at the time of the rollout inventory still recorded
the pre-backfill state, with Clouzet 1033 unmeasured.

### Refreshed nine-leaf convergence

Brian refreshed the provider-free
[`salvation-nine-leaf-convergence-v1`](../evaluation/sermon-topics/salvation-nine-leaf-convergence-v1.json)
report against the same frozen cohort proposal. Its fingerprint is
`86b7f88b6ba43aa09d7be460f2a517df09835696fb53ba11ef1b25517b61a53e`;
it made zero provider requests. Ryder and Williams remain fully measured at
11 and 10 independent sermons, respectively, with N=12 unavailable by design.
Clouzet is now fully measured at 12 of 12, with no unavailable sermons and
all nine N=12 checkpoints available. His full equal-sermon rates include
divine grace 0.189, atonement 0.079, forgiveness 0.150, and judgment 0.196.
The 1033 backfill added observations for divine grace and atonement. His
justification rate remains 0.000 with 0 of 12 sermons observed; this is
insufficient positive evidence, not an absence claim.

Three Clouzet sermons (1044, 1045, 1051) have zero routed leaf blocks and
contribute observed-zero rates under the frozen equal-sermon denominator.
One selected sermon lacks period and series provenance. The report retains
order, period, and replicated-series sensitivity diagnostics. For example,
Clouzet's N=10 judgment rate spans 0.135–0.235 across the report's 5th–95th
order percentiles before the N=12 full mean of 0.196. The N=12 order spread
collapses because every selected sermon is included; that identity is not a
stability finding. The original stage-gate approval still concerns the nine
questions for broader analysis. The refreshed report's
`analytical_credit_granted: false` preserves the prior diagnostic state and
does not revoke that separate decision or grant pastor-level sufficiency.

### Completed pastor uncertainty increment

The provider-free uncertainty packet is implemented as
`pte analysis salvation-pastor-uncertainty`. It uses the frozen 11/10/12-sermon
proposal by default and reuses the convergence calculations for primary rates,
checkpoints, order sensitivity, and period/replicated-series comparisons. Each
leaf adds positive-sermon IDs/counts, signed movement between available primary
checkpoints, exact leave-one-sermon-out results and their range, and a clearly
labeled routed-sermon-only denominator comparison. The approved equal-sermon
rate remains primary. Missing leaf evidence stays unmeasured; zero-routed
sermons remain observed-zero in the primary denominator. Conditional rates are
unavailable when there are no routed sermons. Unknown provenance remains
visible, and zero detections mean insufficient positive evidence. Omission
ranges describe sample sensitivity, not statistical confidence intervals.

Both convergence and uncertainty commands share
`salvation-cohort-measurements-v1.json`, with an optional `--measurement-cache`
override. A hit skips classification reads and projection work. Its contract
includes the frozen proposal, measurement version, approved review, topic and
leaf packs, routing/projection policies, thresholds, database/WAL signatures,
and UTC eligibility hour. Each source classification's size/mtime signature
must still match, and the cached payload must pass its content fingerprint.
Changed evidence or policy invalidates the cache; a malformed cache is rebuilt.
Changes during collection reject the snapshot without writing it. Diagnostic
policies are separate from the measurement cache, so changing the packet does
not require reprojecting unchanged evidence. Output pairs are reused only when
their complete contents match; damaged JSON or Markdown is repaired. No
provider client is constructed. Current profile membership must still match
the frozen pastor, and stale routed leaf question packs are rejected.

Completed packet command, retained for reproduction from the repository root:

```bash
.venv/bin/pte analysis salvation-pastor-uncertainty \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The command has been run and its completed
[JSON packet](../evaluation/sermon-topics/salvation-pastor-uncertainty-v1.json)
and [Markdown companion](../evaluation/sermon-topics/salvation-pastor-uncertainty-v1.md)
are retained as evidence. The packet fingerprint is
`9db5d4dd1c31cdf188da1c42a25885bc27cfe39c1d4658bbbba488d2588f10da`,
bound to the frozen proposal
`1197f1504cc1171a4ec620582b041f8619dd4d900815350561466bd2a02ee70c`
and refreshed convergence
`86b7f88b6ba43aa09d7be460f2a517df09835696fb53ba11ef1b25517b61a53e`.
It records zero provider requests and fully measured cohorts: Ryder 11/11,
Williams 10/10, and Clouzet 12/12. The shared
[cohort measurement cache](../evaluation/sermon-topics/salvation-cohort-measurements-v1.json)
retains the exact contract and per-sermon evidence. Repeating the command on
unchanged evidence within its freshness contract reports `measurement_cache=hit`
and reuses the outputs. The implementation passed 34 focused tests and
`git diff --check`; no corpus evaluation was run during development.

### Salvation measurement completion decision — 2026-10-13

Brian's explicit review in this chat accepts the completed uncertainty packet
and records **Salvation question-set readiness: PASS**. The nine leaves are
validated sufficiently as measurements for broader use. This closes the
salvation measurement increment; the next development work is a new question
set. It does not supersede or rewrite the original fingerprinted stage-gate
and diagnostic artifacts. Their pending-interpretation or sufficiency-false
fields describe their original diagnostic scope; this dated decision records
the subsequent human acceptance of measurement readiness.

Freeze the following contract:

- Nine measured leaves: `divine_grace_initiative`, `atonement_as_basis`,
  `forgiveness_pardon`, `justification_right_standing`, `conversion_new_birth`,
  `sanctification_transformation`, `assurance_security`,
  `judgment_final_destiny`, and `faith_as_receiving_response`.
- Definitions/questions: `salvation-relationships-v9-consequence-conduct-boundary`
  and its question-pack digest. Preserve independent raw probabilities and
  cached answers rather than reinterpreting this review as a prompt revision.
- Routing: `salvation-route-supporting-mass-v1`, with the existing `0.55`
  Supporting-or-above broad-topic probability threshold and eligibility rules.
- Per-leaf thresholds and observation policy:
  `salvation-relationship-observation-thresholds-v9-nine-leaf-final`.
- Measurement semantics: each sermon's observed fraction of routed blocks;
  equal-sermon aggregation remains primary, including observed-zero sermons
  with no routed blocks. Missing evidence remains unmeasured. Routed-sermon-only
  rates are a labeled sensitivity comparison, not a replacement denominator.

The packet exposes sampling dependence worth retaining, rather than tuning
away. Ryder's `sanctification_transformation` primary rate is `0.202117`,
with Joseph-series inside/outside means `0.395834`/`0.159069`. Williams's
`faith_as_receiving_response` inside/outside means are `0.500000`/`0.096682`.
Clouzet's faith response is observed in 1/12 sermons and justification in 0/12.
These are cohort-conditional measurements; series/period differences and sparse
positives do not establish defective leaves or theological absence.

Pastor-level sample-size sufficiency remains **not established**. Do not infer
that 10 or 12 sermons universally characterize a pastor, interpret omission
ranges as confidence intervals, erase unknown provenance, eliminate series
or period effects through tuning, or infer theological absence from zeros.
`repentance_as_receiving_response`, `obedience_as_condition_or_means`, and
`obedience_as_consequence_or_evidence` remain unresolved and excluded from the
nine-leaf analysis. Completing them is not a prerequisite for moving on.

### Listener-directive first increment — 2026-10-13

The first listener-directive development increment is implemented for bounded
review. The [behavior contract and exact handoff commands](LISTENER_DIRECTIVES_BEHAVIOR_CONTRACT.md)
cover nine independent action questions, a candidate router over every final
projection-eligible block, up to twelve natural blocks from videos 1200/590/4430,
and twenty-four prepared boundary probes. Excluded content controls remain
unevaluated. This starts a new question set; it does not activate production
collection or claim validated measurement readiness.

The new registry reuses the existing per-block answer-pack cache, provider
batching/splitting, persistence, and output-pair writer. Complete provider question
semantics form the new digest. Raw answers are independent of batch composition,
routing and display thresholds; existing salvation cache identities are unchanged.
Read-only preparation records source and database/WAL signatures and rejects
changed evidence. The provider client remains lazy on cache hits.

Next: Brian runs `pte analysis listener-directives-review --evaluate` with the
base directory in the linked handoff. Codex interprets the resulting prepared
packet and proposes approval or targeted revisions. No dataset validation or
provider calls were performed during this development increment. Keep the route,
taxonomy, and provisional display cutoff pending bounded review.

### Listener-directive V1 review and V2 refinement — 2026-10-13

Brian's bounded review of the V1 packet (fingerprint
`14d24e6f12e2a4e67fb69860782a4a7b47f23aefd2f57696496e989e4a6aea48`)
passes the eligible-block router and target-only directive evidence contract.
Trust, repent, spiritual practice, witness, participate, and civic action pass
provisionally. Change behavior, give, and serve require revision; the unchanged
nine-leaf contract is not approved. The [stage-gate record](../evaluation/sermon-topics/listener-directive-stage-gate-v1.json)
preserves that scope. Repent at .69 is not treated as failure against the
provisional .70 display cutoff.

`listener-directives-v2-conduct-donation-care` narrows the three definitions to
specific personal moral conduct, financial/material donation, and direct help
or care. The same-case rerun requests only these three revised questions, reuses
six semantically unchanged baseline probabilities, and persists a provenance-rich
composed nine-leaf V2 cache entry through shared composition code. V1 evidence
and salvation identities remain unchanged. The report checks all revised-leaf
probe expectations, the four original overlap failures, and the reviewed natural
appeals at 590:64 and 4430:22. No larger cohort or repent calibration is planned.

Next: Brian reruns the same command in the [handoff](LISTENER_DIRECTIVES_BEHAVIOR_CONTRACT.md).
It now writes `listener-directives-review-v2.json` and its Markdown companion.
Codex interprets that result and recommends broader-analysis readiness if the
localized overlap failures clear without damaging the independently requested
natural actions. This refinement has not been sent to TypeSafe during development.

### Listener-directive V2 review and V3 serve-only refinement — 2026-10-13

Brian's V2 review (fingerprint
`5aa669ea4324bd96a157e554eac51aba10c2bb83ad2e9e3b2aa82f0de7188bc2`)
finds all four overlap regressions resolved but withholds question-set approval:
serve on the natural multi-action appeal at 590:64 dropped from .84 to .13.
The [V2 gate record](../evaluation/sermon-topics/listener-directive-stage-gate-v2.json)
authorizes one targeted serve revision with every other definition, router,
threshold, and case preserved.

`listener-directives-v3-help-people-in-need` changes only serve to include explicit
appeals to help or beneficially impact people in material, social, or spiritual
need without requiring a concrete care task. Mere participation, donation,
prayer, witness, or joining an organization remains insufficient. The serve-only
refinement asks 36 new questions on the exact same 36 cases and reuses eight
fingerprint- and semantics-checked V2 probabilities through the existing shared
composition cache. The original V1/V2 packs, answers, reports, and salvation
identities remain preserved.

Next: Brian runs the unchanged command in the [handoff](LISTENER_DIRECTIVES_BEHAVIOR_CONTRACT.md),
which now writes `listener-directives-review-v3.json` and `.md`. Codex interprets
590:64 recovery and retention of the four clean overlap cases before proposing
broader-analysis readiness. No cohort expansion, threshold tuning, or provider
calls were performed during this serve-only development increment.

### Listener-directive measurement completion — 2026-10-13

Brian accepts the nine V3 listener-directive measurement questions for broader
analysis. The [decision](../evaluation/sermon-topics/listener-directive-stage-gate-v3.json)
is bound to V3 review fingerprint
`d117434e432c36596e1bc39a22942543e59f9cc9980e483cea850dcf666cff30`
and frozen question digest
`471c8c59cbcdb248d7b7af71fb20669a09836c505cda46aaae7cc867a13079d9`.
All four overlap regressions and all 24 authored overlap checks remain clean.
The revised interpretation of 590:64 expects participation, spiritual practice,
and witness; serve=.42 is reasonable secondary ambiguity rather than a failed
strong positive. The .70 display cutoff and repent question remain unchanged.
No prompt revision, threshold tuning, additional listener inference, or larger
cohort is required. Original V1/V2/V3 reports and caches remain unchanged;
the provider-free completion companion records subsequent acceptance.

### Public-life V1 assessment and V2 refinement — 2026-10-13

The cached V1 review (fingerprint
`4134e90dd540f5f8bb0d263091ee44605b1dee37944633c472dc1ef15d714b77`)
exposes two targeted issues: descriptive under-recognizes reporting another
public actor's praise without endorsement, while prescriptive over-infers public
ought-claims from moral condemnation and listener advocacy. Preserve useful
moral, theological, critical, supportive, illustrative, and advocative dimensions;
correct the incomplete moral expectations in probes 14/16 rather than weakening
those questions or tuning .69 observations against a display cutoff.

The [assessment](../evaluation/sermon-topics/public-life-v1-semantic-assessment-v1.md)
and updated [contract](PUBLIC_LIFE_TREATMENT_BEHAVIOR_CONTRACT.md) prepare only
descriptive/prescriptive revisions. The same 28 cases yield 56 new judgments,
reusing the other six raw answers and shared composition cache. The V1 raw report
is preserved; V2 question readiness awaits Brian's bounded run. The .55 route
remains unapproved for coverage because 1200:26 and 4430:34 have meaningful
below-route treatment. Keep that sampling policy unchanged during this rerun;
consider eligibility-only broader routing separately. No cohort expansion or
collection threshold change is needed to resolve these semantic issues.

The overarching contract remains block-level treatment and expressed perspective.
These leaves do not bind stance to a named object/proposition; do not derive
which policy a pastor endorses from topic/treatment co-occurrence alone. No
single-label classifier or blanket ban on supportive/critical co-occurrence is
introduced. Readiness should follow semantic interpretation, not validation for
its own sake.

### Public-life measurement completion and routing proposal — 2026-10-13

Brian approves the eight V2 public-life treatment questions for broader analysis.
The [completion decision](../evaluation/sermon-topics/public-life-treatment-stage-gate-v2.json)
is bound to V2 review fingerprint
`8930a9ad6776bf3267a6593776cd5e1028ce74895211eca871433c666f092048`
and question digest
`81bb09e1b660cbd3aa4838b1c528a16ea20bbd66806bca7526856de81d39f079`.
Freeze V2, including six reused V1 leaves, target-only attribution, legitimate
multidimensional overlap, and .69 boundary observations. There is no treatment
V3, threshold tuning, or additional treatment-validation inference to perform.
Original diagnostic artifacts remain immutable.

The separate [provider-free routing comparison](../evaluation/sermon-topics/public-life-routing-comparison-v2.md)
compares .55 Supporting-or-above routing with strict current projection
eligibility on ten saved natural cases. Old routing includes four blocks;
eligibility-only includes ten and recovers both reviewed misses while excluding
all saved ineligible controls. Three absent-topic controls have no displayed
treatment. The extra theological result at 590:60 remains an interpretation case,
not an independently reviewed third miss. This stratified sample is not a corpus
recall or workload estimate. Historical source `eligible_block_count` fields
counted candidate routes; future preparation now distinguishes eligible and routed
counts. Do not use those archived counts as broader-collection cost evidence.

### Public-life routing handoff

The provider-free comparison is complete. Recommend
`public-life-route-eligible-v2-candidate`: use current final content projection
eligibility as the inference gate and public-topic support only as a
prioritization/sampling diagnostic. The .55 Supporting-or-above policy is not
suitable as a coverage gate for these treatment measurements. The implemented
eligibility-only candidate remains a routing proposal; broader collection is
inactive until that policy is accepted. This does not block development of the
next question set or require further treatment calibration.

The [routing handoff](PUBLIC_LIFE_TREATMENT_BEHAVIOR_CONTRACT.md) reproduces the
comparison and completion decision without a provider or database. Routing does
not enter answer-pack identity; frozen V2 probabilities and per-leaf provenance
remain reusable. Do not reopen treatment questions, alter the display cutoff,
or run a broader collection job to move to source/material.

### Next iteration

Move to **source/material**, the next question set in the established enrichment
order. Brian's direction in this chat advances development to this set. The
concrete downstream question is: *What source or material carries the preacher's
point in this block?* Begin with the planned candidates: biblical narrative,
testimony, historical example, quotation, and explicitly identifiable
denominational source use. These are candidates for the smallest useful behavior
contract, not an approved taxonomy or a requirement to implement every distinction.

Keep source/material distinct from topic, rhetorical treatment, listener action,
and theological position. Biblical narrative or quotation does not establish the
Scripture/revelation topic. Using a public historical example does not by itself
establish support or criticism of its actors. An explicitly identified
Ellen White or other denominational source does not establish the preacher's
identity, affiliation, or doctrinal agreement. Distinguish the preacher's own
experience from reported testimony where that distinction is independently useful.
Do not invent an attribution from familiar wording or nearby religious vocabulary.

Prepare concrete positive, negative, overlap, attribution, and context-boundary
cases with default inputs and a proposed decision. Preserve target-only evidence;
adjacent context may resolve references but cannot independently supply a source
or material absent from the target. Keep independently evidenced source and form
dimensions observable rather than forcing one exclusive source label. Quotation
and a biblical or denominational source may legitimately coexist.

Use current content-role and final projection eligibility. Start from a
coverage-conscious routing proposal and inspect bounded cached evidence; do not
inherit a broad-topic cutoff as a source-presence gate. In particular, do not gate
biblical narrative or quotation solely on the Scripture/revelation topic. Routing
and source-question readiness must be evaluated separately.

Keep the implementation DRY and cache-first. Reuse the shared pack registry,
preparation, provider adapter, independent per-block answer cache, composition,
and output-pair writer. Give new question semantics their own version and digest;
keep raw probabilities independent of batch composition, routing, and downstream
thresholds. Reuse existing role/treatment/topic observations. A new source pack
must not invalidate or rerun frozen salvation, listener-directive, or public-life
treatment measurements. If only some source questions change after review,
recompute only those and retain the other answers with their original provenance.

Run focused unit tests and inexpensive static checks during development. Hand
Brian the exact bounded validation command and prepared cases; do not run or
monitor corpus jobs or ask him to design experiments or author annotations.
Interpret the results and recommend approval or a narrow revision. Do not tune
prompts merely to cross a provisional display cutoff, infer pastor-level stance
from block co-occurrence, or expand into a universal source/subtopic tree.

## Non-goals for `topics-v1`

- Selecting one primary topic per block.
- Normalizing topic Scores to sum to one.
- Inferring theology from keyword or topic co-occurrence.
- Labeling a pastor legalistic, nationalist, political, doctrinal, practical,
  orthodox, heterodox, or similar.
- Treating public-life references as advocacy without direct evidence.
- Treating an Ellen White quotation as denominational identity by itself.
- Building all topic leaves or topic-treatment cross-products into the broad
  pass.
- Treating a performed song as the church/worship topic merely because it is
  music, or treating its theological lyrics as pastor-profile evidence.
- Backfilling the full corpus before the observation contract passes bounded
  review.

## Decision record

- Freeze twenty broad topics for `topics-v1`.
- Include spiritual conflict and the unseen realm as topic 20.
- Keep the four organizational domains navigational and unscored.
- Keep coarse discovery and fine analysis sequential, and do not add adjacent
  minute text to the fine request. At most one complete context-only sentence
  on either side is allowed.
- Use independent five-level TypeSafe Scores rather than Nouls or one exclusive
  taxonomy Choice.
- Preserve full Score distributions, confidence, raw evidence, and deterministic
  density separately.
- Treat content role, topic meaning, and analytical eligibility as separate
  decisions. Raw observations may describe lyrics; projection must not attribute
  excluded music to the preacher.
- Keep leaves out of the one-minute broad request. Add them as independently
  cached, second-stage packs over qualifying blocks. The nine approved salvation
  relationships, listener directives, and public-life treatment questions are
  complete and frozen; source/material is next. Public-life eligibility-only
  routing is the evaluated recommendation before broader collection.
- Exclude zero-overlap, partial or mixed, sparse, and non-sermon-role blocks from
  read-only projection; preserve their raw observations for inspection.
- Keep topic inference observation-only until accepted-sermon and reviewed-profile
  projection, whole-sermon validity, and cross-series stability support a more
  specific use.
- Let reviewed misclassifications—not further abstract taxonomy expansion—drive
  changes after v1.

## Related project contracts

- [Evidence-backed sermon style analysis](SEMANTIC_STYLE_ANALYSIS.md)
- [Sermon analysis and profile projection](SERMON_ANALYSIS.md)
- [Analytical review implementation plan](analytical-review/IMPLEMENTATION-PLAN.md)
