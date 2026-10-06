# TypeSafe Sermon Topic Analysis Plan

Status: observation, cache, sparse-gap recovery, and read-only sermon projection
contracts implemented, with one naturally processed sermon reviewed as an
initial field observation. The broad taxonomy remains the `topics-v1` starting
hypothesis; the current clarified question pack is
`topics-v3-mission-discourse-boundary`. No version authorizes pastor-level
conclusions. Profile aggregation and leaf packs remain deferred.

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

### Next iteration

1. Finalize the four reviewed Stage 2 drafts against their protected proposals.
   This is deterministic and must not make another provider call.
2. Validate `topics-v3-mission-discourse-boundary` on the same four-sermon Stage 2
   cohort, checking the corrected mission boundary and guarding the other nineteen
   topics against regression.
3. After those adjudications and validation, prepare the bounded 12-sermon, four-pastor Stage 3
   cohort and whole-sermon packets from naturally accumulated cached evidence.
   Profile aggregation remains blocked until that review establishes credible
   analytical projection.
4. Once projection is credible, implement `salvation-relationships-v1` as the
   first routed leaf pack. Keep its cache and question identity independent of
   the broad topic pack and later revisions.

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
  cached, second-stage packs over qualifying blocks, beginning tentatively with
  salvation relationships.
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
