# TypeSafe Sermon Topic Analysis Plan

Status: observation and cache contract implemented. The taxonomy is frozen as
the `topics-v1` starting hypothesis, but it is not yet empirically validated and
does not authorize pastor-level conclusions. Prospective review and later
projection stages remain intentionally pending.

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
- Captions, repeated fragments, stage directions, lyrics, rhetorical questions,
  and quotations must not be treated as the preacher's developed topic without
  sufficient center-block evidence.
- Only timestamped source segments participate. Exact source segment indexes and
  the overlap with the final retained sermon window remain durable provenance.

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
current block batch size is six, so a full batch would contain at most 150
questions: six role Choices, 24 semantic-mode Nouls, and 120 topic Scores. The
last partial batch may be smaller. Transcript state is shared within each
provider request, but question definitions and answer distributions still
consume tokens.

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
  current six-block batch produces at most 150 questions after `topics-v1` and
  must be reducible without changing per-block cache identity.
- TypeSafe speculative fan-out is useful for independent questions, but all
  questions in one request are evaluated. A genuine conditional leaf pack
  requires a later request over qualifying blocks.

See TypeSafe's
[speculative fan-out guidance](https://docs.typesafe.ai/patterns/fan-out.md).

## First-class cache architecture

Refactor the current per-block answer cache before attaching `topics-v1`.
Logical answer packs require independent identities:

- sermon role pack;
- homiletic-treatment pack;
- `topics-v1`; and
- future leaf, directive, framing, and proposition packs.

For a new block, the request planner may batch every missing pack into one
TypeSafe call and write each returned pack separately. For an existing block,
adding or changing a topic pack must not invalidate cached role or treatment
answers.

Each topic-pack cache identity includes:

- requested and resolved model identifiers;
- exact `topics-v1` inventory and prominence rubric digest;
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
  context-only mentions; and
- spiritual-conflict positives and exclusions.

Use focused unit tests and a bounded reviewed fixture only. Do not run a broad
corpus reclassification while developing.

### Stage 2: prospective sanity review

Allow normal future TypeSafe extractions to accumulate topic observations. From
those naturally collected results, prepare a bounded evidence packet showing
the center block, adjacent context, all Score distributions, density fields,
and final-sermon overlap. Review disagreements and boundary failures rather
than tuning against unlabeled aggregate distributions.

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

1. Add a single shared `topics-v1` specification from which TypeSafe questions,
   persisted inventory, display labels, and test expectations are derived.
2. Split the current TypeSafe block cache into independently versioned answer
   packs and add a missing-pack request planner.
3. Generate the twenty Score questions for each fine block, using the universal
   rubric, target-minute-only evidence contract, and bounded leading/trailing
   context.
4. Parse and persist expected Scores, complete probability distributions,
   confidence, provenance, and density fields with no policy effect.
5. Add focused tests for request composition, cache separation, unchanged
   replay, partial pack reuse, fallback retention, sparse blocks, overlap, and
   schema completeness.
6. Record provider usage and surface topic collection in diagnostics without
   turning it into a classification gate.
7. Collect prospectively and prepare the bounded sanity-review packet.
8. Implement a read-only sermon/profile projection only after the observation
   and density contracts are stable.
9. Add smaller cached enrichment packs in this tentative order: source/material,
   listener directives, salvation relationships, public-life treatment, and
   other topic-specific propositions justified by reviewed failures or product
   needs.

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
- Keep topic inference observation-only until accepted-sermon and reviewed-profile
  projection, whole-sermon validity, and cross-series stability support a more
  specific use.
- Let reviewed misclassifications—not further abstract taxonomy expansion—drive
  changes after v1.

## Related project contracts

- [Evidence-backed sermon style analysis](SEMANTIC_STYLE_ANALYSIS.md)
- [Sermon analysis and profile projection](SERMON_ANALYSIS.md)
- [Analytical review implementation plan](analytical-review/IMPLEMENTATION-PLAN.md)
