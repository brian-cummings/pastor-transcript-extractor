"""Versioned TypeSafe topic-prominence questions and deterministic evidence metadata."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any, Collection, Mapping, MutableMapping, Sequence

from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_classification import TranscriptBlock


TOPIC_PACK_VERSION = "topics-v2-performed-worship-boundary"
TOPIC_CONTEXT_POLICY_VERSION = "topic-context-sentences-v1"
TOPIC_RELIABILITY_POLICY_VERSION = "topic-density-v1"
TOPIC_PROJECTION_POLICY_VERSION = "sermon-topic-full-block-role-density-v1"
PROFILE_ANALYSIS_ACTIVATION_REQUIREMENT = (
    "accepted_sermon_with_effective_reviewed_profile_membership"
)
TOPIC_ARTIFACT_SCHEMA_VERSION = 2
TOPIC_CONTEXT_MAX_CHARS = 400
TOPIC_PROMINENCE_LEVELS = (
    {"name": "Absent", "criterion": "The center block gives this topic no meaningful attention."},
    {"name": "Incidental", "criterion": "The center block names, assumes, or briefly references this topic without developing it."},
    {"name": "Supporting", "criterion": "The center block meaningfully develops this topic, but it remains subordinate to another concern."},
    {"name": "Substantial", "criterion": "The center block sustains this topic as one of its main concerns."},
    {"name": "Dominant", "criterion": "This topic is the primary organizing concern through most of the center block."},
)


@dataclass(frozen=True, slots=True)
class TopicSpec:
    label: str
    definition: str
    include: str
    exclude: str
    domain: str


def _topic(label: str, definition: str, include: str, exclude: str, domain: str) -> TopicSpec:
    return TopicSpec(label, definition, include, exclude, domain)


TOPIC_SPECS: dict[str, TopicSpec] = {
    "god_character_action": _topic("God: character, will & action", "God's attributes, character, purposes, will, sovereignty, providence, or actions.", "Divine love, justice, holiness, faithfulness, judgment, providence, creation, governance, and action in history or individual lives.", "Undeveloped references to God; a passage involving Jesus without a developed claim about God or divine character and action.", "theology_spiritual_reality"),
    "jesus_person_work": _topic("Jesus Christ: person & work", "Jesus's identity, character, incarnation, ministry, teachings, death, resurrection, mediation, reign, or return.", "Christology, the cross, resurrection, earthly ministry, teachings, priestly or mediatorial work.", "Jesus merely appearing in a quotation or story without meaningful development of his person, teaching, or work.", "theology_spiritual_reality"),
    "holy_spirit_person_work": _topic("Holy Spirit: person & work", "The Spirit's identity, presence, conviction, transformation, guidance, gifts, empowerment, or activity.", "Indwelling, fruit or gifts of the Spirit, inspiration, conviction, guidance, empowerment.", "Generic divine action not attributed to the Holy Spirit.", "theology_spiritual_reality"),
    "scripture_revelation": _topic("Scripture & revelation", "Scripture or revelation itself: inspiration, authority, reliability, interpretation, canon, disclosure, or hermeneutics.", "How to interpret the Bible, why Scripture is authoritative, divine revelation, inspiration, reliability.", "Merely quoting, retelling, or expounding a biblical passage without discussing Scripture or revelation as a subject.", "theology_spiritual_reality"),
    "sin_fallenness_human_need": _topic("Sin, fallenness & human need", "Sin, guilt, rebellion, fallenness, moral corruption, alienation from God, or the human need created by sin.", "Inherited fallenness, guilt, idolatry, rebellion, consequences of sin, inability or need before God.", "Ordinary mistakes, suffering without developed moral or spiritual brokenness, or resisting temptation when Christian growth is the focus.", "human_condition_redemption"),
    "salvation_gospel": _topic("Salvation & gospel", "God's saving work and the human reception or experience of salvation.", "Grace, atonement, forgiveness, justification, conversion, reconciliation, adoption, assurance, and sanctification as saving work.", "General growth or spiritual practice after salvation when saving work is not discussed.", "human_condition_redemption"),
    "discipleship_spiritual_formation": _topic("Discipleship & spiritual formation", "Lived Christian growth, trust, obedience, prayer, spiritual disciplines, resistance to temptation, character, and formation.", "Prayer practice, faith and trust as lived response, obedience, habits, growth, spiritual disciplines, Christian character.", "Salvation itself; moral evaluation without formation or lived discipleship.", "human_condition_redemption"),
    "relationships_family_interpersonal": _topic("Relationships, family & interpersonal life", "Marriage, family, parenting, friendship, forgiveness, conflict, sexuality, loneliness, or interpersonal responsibilities.", "Reconciliation between people, family roles, friendship, relational boundaries, interpersonal sexuality.", "Church community as ecclesiology; abstract moral principles without a developed interpersonal setting.", "church_lived_community"),
    "church_worship_community": _topic("Church, worship & community", "The nature, purpose, practices, leadership, unity, fellowship, membership, worship, ordinances, or gifts of the church.", "Ecclesiology, congregational life, corporate worship, church leadership, unity, ordinances, spiritual gifts in community.", "Merely addressing the congregation, referring to the local church, praying, or performing music or lyrics without discussing church life or corporate worship as a subject.", "church_lived_community"),
    "mission_evangelism_witness": _topic("Mission, evangelism & witness", "Proclaiming the gospel, witnessing, disciple-making, missions, or communicating faith outwardly.", "Personal witness, evangelistic proclamation, cross-cultural mission, disciple-making.", "Kindness or service whose principal purpose is not proclamation or disciple-making.", "church_lived_community"),
    "compassion_generosity_service": _topic("Compassion, generosity & service", "Mercy, generosity, direct aid, care for vulnerable people, or practical service to others.", "Helping people in need, charitable giving, hospitality, mercy, volunteering, direct care.", "Evangelism principally aimed at proclamation; structural public justice; abstract moral evaluation without concrete care or service.", "church_lived_community"),
    "suffering_adversity_death": _topic("Suffering, adversity & death", "Grief, illness, persecution, tragedy, hardship, mortality, endurance, or consolation amid suffering.", "Bereavement, chronic illness, persecution, trials, disaster, mortality, lament, endurance.", "Sin merely producing consequences; the doctrinal state of the dead without developed suffering or mortality.", "human_condition_redemption"),
    "ethics_moral_conduct": _topic("Ethics & moral conduct", "Explicit moral evaluation of actions, practices, choices, or norms.", "Honesty, integrity, sexual ethics, violence, substance use, moral responsibility, individual justice.", "Spiritual growth without explicit moral evaluation; daily-life subjects without a moral claim.", "moral_created_public_future"),
    "vocation_stewardship_daily_life": _topic("Vocation, stewardship & daily life", "Work, money, possessions, time, health, education, decision-making, responsibilities, or stewardship in everyday life.", "Vocation, budgeting, use of time, physical health, education, possessions, planning and ordinary responsibilities.", "Explicit moral evaluation without meaningful daily-life development; generosity as concrete care may primarily be compassion.", "church_lived_community"),
    "human_nature_identity": _topic("Human nature & identity", "Theological discussion of what human beings are, their dignity, purpose, freedom, embodiment, identity, or creaturely status.", "Image of God, free will, body and soul, human worth, purpose, nature, identity before God.", "Personal biography or generic self-esteem; sin specifically as the human problem; relationships without theological anthropology.", "human_condition_redemption"),
    "creation_origins_created_order": _topic("Creation, origins & created order", "Creation, origins, the natural world, created order, or humanity's responsibility toward creation.", "Creation accounts, origins, design, nature, environmental stewardship, order in creation.", "Human nature unless tied to creation; generic references to God as Creator without developing creation.", "moral_created_public_future"),
    "society_public_life": _topic("Society & public life", "Government, politics, nations, public policy, elections, patriotism, social structures, church-state relations, or religious liberty.", "Political actors and parties, law or policy, nationalism, civic life, structural social questions, religious liberty.", "Private moral conduct merely occurring in society; a passing current event without developed public significance.", "moral_created_public_future"),
    "eschatology_prophecy": _topic("Eschatology & prophecy", "The Second Coming, final judgment, resurrection, heaven or new earth, millennium, prophetic interpretation, or end-time events.", "Apocalyptic interpretation, signs of the end, final events, resurrection, afterlife, consummation.", "Death itself when mortality or grief is the subject; Jesus's return without meaningful end-time development.", "moral_created_public_future"),
    "adventist_doctrine_identity": _topic("Adventist doctrine & identity", "Explicitly denominational Adventist teachings, identity, history, authorities, or self-understanding.", "Sabbath as distinctive doctrine, sanctuary, state of the dead, remnant, Great Controversy framework, Ellen White's role, denominational history, distinctive health teaching.", "Generic Christianity taught by an Adventist; merely quoting Ellen White without discussing her role, authority, or denominational significance.", "moral_created_public_future"),
    "spiritual_conflict_unseen_realm": _topic("Spiritual conflict & unseen realm", "Sustained discussion of supernatural beings, powers, conflict, or opposition other than God, Jesus, and the Holy Spirit.", "Satan, demons, angels, spiritual warfare, supernatural evil, cosmic conflict, demonic temptation or oppression, angelic activity.", "Ordinary temptation without developed supernatural agency; divine action; end-time events without developed supernatural conflict.", "theology_spiritual_reality"),
}
TOPICS = tuple(TOPIC_SPECS)
TOPIC_DOMAIN_LABELS = {
    "theology_spiritual_reality": "Theology & spiritual reality",
    "human_condition_redemption": "Human condition & redemption",
    "church_lived_community": "Church & lived community",
    "moral_created_public_future": "Moral, created, public & future order",
}


def resolve_topic_analysis_artifact(
    classification: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return cached topic observations from either supported classifier layout."""
    search = classification.get("search")
    search = search if isinstance(search, Mapping) else {}
    direct = search.get("topic_analysis")
    if isinstance(direct, Mapping):
        return direct
    discovery = search.get("discovery")
    discovery = discovery if isinstance(discovery, Mapping) else {}
    attempt = discovery.get("typesafe_first_attempt")
    attempt = attempt if isinstance(attempt, Mapping) else {}
    fallback = attempt.get("topic_analysis")
    if isinstance(fallback, Mapping):
        return fallback
    raise ValueError("Classification has no cached TypeSafe topic analysis")


def topic_question_id(position: int, topic: str) -> str:
    if topic not in TOPIC_SPECS:
        raise ValueError(f"Unknown topic: {topic}")
    return f"topic_{position}_{topic}"


def topic_question_inventory(position: int) -> dict[str, dict[str, Any]]:
    target = f"topic_blocks[{position}].target_text"
    return {
        topic_question_id(position, name): {
            "kind": "score",
            "topic": name,
            "instructions": {
                "task": f"Score how prominently {spec.definition} is discussed in `{target}`.",
                "evidence_boundary": (
                    f"Only language in `{target}` is topic evidence. `topic_blocks[{position}].leading_context` "
                    f"and `topic_blocks[{position}].trailing_context` may clarify that language but cannot independently establish the topic."
                ),
                "independence": "Score this topic independently. Do not lower it because another topic also applies or is more specific.",
                "include": spec.include,
                "exclude": spec.exclude,
                "artifacts": (
                    "Captions, repetitions, stage directions, rhetorical questions, "
                    "rejected alternatives, and quotations must not independently "
                    "manufacture a developed topic. Lyrics may genuinely discuss a "
                    "theological subject, so score the subject present in the target "
                    "without treating performance itself as discussion of church or "
                    "corporate worship. These scores describe block content; separate "
                    "code decides whether it is attributable to the preacher."
                ),
            },
            "criteria": [dict(level) for level in TOPIC_PROMINENCE_LEVELS],
        }
        for name, spec in TOPIC_SPECS.items()
    }


def topic_pack_inventory() -> dict[str, Any]:
    return {
        "version": TOPIC_PACK_VERSION,
        "topics": {name: asdict(spec) for name, spec in TOPIC_SPECS.items()},
        "domains": {
            domain: {
                "label": label,
                "topics": [
                    name for name, spec in TOPIC_SPECS.items() if spec.domain == domain
                ],
                "scored": False,
            }
            for domain, label in TOPIC_DOMAIN_LABELS.items()
        },
        "prominence_levels": [dict(level) for level in TOPIC_PROMINENCE_LEVELS],
    }


def topic_pack_digest() -> str:
    encoded = json.dumps(topic_pack_inventory(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class TopicBlockContext:
    leading_context: str
    target_text: str
    trailing_context: str
    diagnostics: Mapping[str, Any]

    def state_payload(self) -> dict[str, str]:
        return {
            "leading_context": self.leading_context,
            "target_text": self.target_text,
            "trailing_context": self.trailing_context,
        }


_SENTENCE_END = re.compile(r"[.!?][\"')\]]*(?:\s+|$)")


def _bounded_context(text: str, *, leading: bool) -> tuple[str, dict[str, Any]]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return "", {
            "available": False,
            "arbitrarily_truncated": False,
            "complete_outer_boundary": True,
            "adjacent_unit_complete": True,
            "sentence_end_count": 0,
            "source_characters": 0,
            "selected_characters": 0,
            "selected_sentence_units": 0,
        }
    units: list[tuple[str, bool]] = []
    cursor = 0
    for match in _SENTENCE_END.finditer(normalized):
        unit = normalized[cursor : match.end()].strip()
        if unit:
            units.append((unit, True))
        cursor = match.end()
    remainder = normalized[cursor:].strip()
    if remainder:
        units.append((remainder, False))
    if not units:
        units = [(normalized, False)]
    # The boundary-adjacent fragment/sentence plus at most one complete sentence
    # supplies enough clarification without attaching the neighboring minute.
    chosen = units[-2:] if leading else units[:2]
    selected = " ".join(unit for unit, _ in chosen)
    truncated = len(selected) > TOPIC_CONTEXT_MAX_CHARS
    if truncated:
        selected = (
            selected[-TOPIC_CONTEXT_MAX_CHARS:].lstrip()
            if leading
            else selected[:TOPIC_CONTEXT_MAX_CHARS].rstrip()
        )
    outer_complete = chosen[0][1] if leading else chosen[-1][1]
    complete = outer_complete and not truncated
    return selected, {
        "available": True,
        "arbitrarily_truncated": truncated,
        "complete_outer_boundary": bool(complete and not truncated),
        "adjacent_unit_complete": chosen[-1][1] if leading else chosen[0][1],
        "sentence_end_count": sum(1 for _, is_complete in chosen if is_complete),
        "source_characters": len(normalized),
        "selected_characters": len(selected),
        "selected_sentence_units": len(chosen),
    }


def build_topic_context(drafts: Sequence[SegmentDraft], block: TranscriptBlock) -> TopicBlockContext:
    indexes = set(block.segment_indexes)
    timed = [
        (index, draft)
        for index, draft in enumerate(drafts)
        if draft.start_seconds is not None
        and draft.end_seconds is not None
        and draft.end_seconds > draft.start_seconds
    ]
    before = " ".join(draft.text for index, draft in timed if index not in indexes and draft.end_seconds <= block.start_seconds)
    after = " ".join(draft.text for index, draft in timed if index not in indexes and draft.start_seconds >= block.end_seconds)
    leading, leading_diagnostics = _bounded_context(before, leading=True)
    trailing, trailing_diagnostics = _bounded_context(after, leading=False)
    return TopicBlockContext(
        leading,
        block.text,
        trailing,
        {
            "policy_version": TOPIC_CONTEXT_POLICY_VERSION,
            "max_characters_per_side": TOPIC_CONTEXT_MAX_CHARS,
            "leading": leading_diagnostics,
            "trailing": trailing_diagnostics,
        },
    )


_NOISE_MARKER = re.compile(r"\[(?:music|applause|laughter|inaudible|noise)\]", re.IGNORECASE)
_LEXICAL_WORD = re.compile(r"\b[^\W\d_]+(?:['’-][^\W\d_]+)*\b", re.UNICODE)


def topic_block_density(block: TranscriptBlock) -> dict[str, Any]:
    """Return deterministic density shared by localization and topic projection."""
    cleaned = _NOISE_MARKER.sub(" ", block.text)
    word_count = len(_LEXICAL_WORD.findall(cleaned))
    duration = max(0.0, block.end_seconds - block.start_seconds)
    words_per_minute = word_count * 60.0 / duration if duration else 0.0
    return {
        "analyzable_lexical_word_count": word_count,
        "block_duration_seconds": round(duration, 3),
        "analyzable_words_per_minute": round(words_per_minute, 3),
        "sparse": word_count < 20 or words_per_minute < 20.0,
        "non_analyzable": word_count == 0,
    }


def topic_reliability(
    block: TranscriptBlock,
    *,
    retained_segment_indexes: set[int],
    selected_start_seconds: float | None,
    selected_end_seconds: float | None,
) -> dict[str, Any]:
    density = topic_block_density(block)
    overlap = (
        max(0.0, min(block.end_seconds, selected_end_seconds) - max(block.start_seconds, selected_start_seconds))
        if selected_start_seconds is not None and selected_end_seconds is not None
        else 0.0
    )
    retained = [index for index in block.segment_indexes if index in retained_segment_indexes]
    return {
        "version": TOPIC_RELIABILITY_POLICY_VERSION,
        **density,
        "final_sermon_overlap_seconds": round(overlap, 3),
        "retained_source_segment_indexes": retained,
    }


def _projection_exclusion_reasons(
    observation: Mapping[str, Any],
    *,
    eligible_roles: Collection[str],
) -> list[str]:
    reliability = observation.get("reliability")
    reliability = reliability if isinstance(reliability, Mapping) else {}
    duration = float(reliability.get("block_duration_seconds") or 0.0)
    overlap = float(reliability.get("final_sermon_overlap_seconds") or 0.0)
    segment_indexes = {
        int(index)
        for index in observation.get("segment_indexes", [])
        if isinstance(index, int)
    }
    retained_indexes = {
        int(index)
        for index in reliability.get("retained_source_segment_indexes", [])
        if isinstance(index, int)
    }
    reasons: list[str] = []
    if overlap <= 0.0 or not retained_indexes:
        reasons.append("outside_final_sermon")
    elif overlap + 0.001 < duration or retained_indexes != segment_indexes:
        reasons.append("partial_or_mixed_retained_coverage")
    if observation.get("content_role") not in eligible_roles:
        reasons.append("non_sermon_content_role")
    if reliability.get("non_analyzable") is True:
        reasons.append("non_analyzable")
    elif reliability.get("sparse") is True:
        reasons.append("sparse_transcript_evidence")
    return reasons


def _topic_evidence_link(
    observation: Mapping[str, Any], topic: str
) -> dict[str, Any]:
    scores = observation.get("scores")
    scores = scores if isinstance(scores, Mapping) else {}
    score = scores.get(topic)
    score = score if isinstance(score, Mapping) else {}
    probabilities = score.get("probabilities")
    probabilities = probabilities if isinstance(probabilities, Mapping) else {}
    return {
        "block_id": observation.get("block_id"),
        "start_seconds": observation.get("start_seconds"),
        "end_seconds": observation.get("end_seconds"),
        "score": round(float(score.get("score") or 0.0), 6),
        "supporting_or_above_probability": round(
            sum(float(probabilities.get(str(level)) or 0.0) for level in (2, 3, 4)),
            6,
        ),
    }


def refresh_topic_analysis_projection(
    analysis: MutableMapping[str, Any],
    *,
    retained_segment_indexes: Collection[int],
    selected_start_seconds: float | None,
    selected_end_seconds: float | None,
    eligible_roles: Collection[str],
    final_disposition_status: str | None = None,
    window_source: str | None = None,
) -> MutableMapping[str, Any]:
    """Refresh final-window overlap and its deterministic read-only projection."""
    retained = {int(index) for index in retained_segment_indexes}
    raw_blocks = analysis.get("blocks")
    observations = raw_blocks if isinstance(raw_blocks, list) else []
    eligible: list[Mapping[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for observation in observations:
        if not isinstance(observation, MutableMapping):
            continue
        start = observation.get("start_seconds")
        end = observation.get("end_seconds")
        segment_indexes = [
            int(index)
            for index in observation.get("segment_indexes", [])
            if isinstance(index, int)
        ]
        overlap = (
            max(
                0.0,
                min(float(end), float(selected_end_seconds))
                - max(float(start), float(selected_start_seconds)),
            )
            if isinstance(start, (int, float))
            and isinstance(end, (int, float))
            and selected_start_seconds is not None
            and selected_end_seconds is not None
            else 0.0
        )
        reliability = observation.get("reliability")
        reliability = dict(reliability) if isinstance(reliability, Mapping) else {}
        reliability["final_sermon_overlap_seconds"] = round(overlap, 3)
        reliability["retained_source_segment_indexes"] = [
            index for index in segment_indexes if index in retained
        ]
        observation["reliability"] = reliability
        reasons = _projection_exclusion_reasons(
            observation,
            eligible_roles=eligible_roles,
        )
        observation["projection_eligibility"] = {
            "policy_version": TOPIC_PROJECTION_POLICY_VERSION,
            "eligible": not reasons,
            "exclusion_reasons": reasons,
        }
        if reasons:
            exclusions.append(
                {"block_id": observation.get("block_id"), "reasons": reasons}
            )
        else:
            eligible.append(observation)

    eligible_seconds = sum(
        float(item["reliability"].get("block_duration_seconds") or 0.0)
        for item in eligible
    )
    measurements: dict[str, Any] = {}
    for topic in TOPICS:
        weighted_score = 0.0
        weighted_support = 0.0
        for observation in eligible:
            duration = float(
                observation["reliability"].get("block_duration_seconds") or 0.0
            )
            score = observation["scores"][topic]
            probabilities = score["probabilities"]
            weighted_score += duration * float(score["score"]) / 4.0
            weighted_support += duration * sum(
                float(probabilities.get(str(level)) or 0.0)
                for level in (2, 3, 4)
            )
        ranked = sorted(
            eligible,
            key=lambda item: float(item["scores"][topic]["score"]),
            reverse=True,
        )
        measurements[topic] = {
            "mean_normalized_expected_prominence": (
                round(weighted_score / eligible_seconds, 6)
                if eligible_seconds
                else None
            ),
            "mean_supporting_or_above_probability": (
                round(weighted_support / eligible_seconds, 6)
                if eligible_seconds
                else None
            ),
            "representative_blocks": [
                _topic_evidence_link(item, topic) for item in ranked[:3]
            ],
            "counterevidence_blocks": [
                _topic_evidence_link(item, topic)
                for item in sorted(
                    eligible,
                    key=lambda item: float(item["scores"][topic]["score"]),
                )[:2]
            ],
        }
    analysis["sermon_projection"] = {
        "schema_version": 1,
        "policy_version": TOPIC_PROJECTION_POLICY_VERSION,
        "status": "read_only" if eligible else "insufficient_eligible_evidence",
        "policy_effect": "none",
        "scope": "final_retained_sermon",
        "final_disposition_status": final_disposition_status,
        "window_source": window_source,
        "eligible_content_roles": sorted(eligible_roles),
        "eligibility_rule": (
            "full retained block coverage, sermon content role, and non-sparse "
            "analyzable transcript evidence"
        ),
        "eligible_block_ids": [item.get("block_id") for item in eligible],
        "eligible_block_count": len(eligible),
        "eligible_sermon_seconds": round(eligible_seconds, 3),
        "excluded_blocks": exclusions,
        "denominator": "eligible_sermon_seconds",
        "profile_aggregation": "blocked_pending_reviewed_profile_membership",
        "measurements": measurements,
    }
    return analysis
