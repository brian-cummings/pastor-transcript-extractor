"""Versioned TypeSafe topic-prominence questions and deterministic evidence metadata."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_classification import TranscriptBlock


TOPIC_PACK_VERSION = "topics-v1"
TOPIC_CONTEXT_POLICY_VERSION = "topic-context-sentences-v1"
TOPIC_RELIABILITY_POLICY_VERSION = "topic-density-v1"
TOPIC_ARTIFACT_SCHEMA_VERSION = 1
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
    "church_worship_community": _topic("Church, worship & community", "The nature, purpose, practices, leadership, unity, fellowship, membership, worship, ordinances, or gifts of the church.", "Ecclesiology, congregational life, corporate worship, church leadership, unity, ordinances, spiritual gifts in community.", "Merely addressing the congregation or referring to the local church without developing it as a subject.", "church_lived_community"),
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
                "artifacts": "Do not treat captions, repetitions, stage directions, lyrics, rhetorical questions, rejected alternatives, or quotations as the preacher's developed topic without sufficient target-block evidence.",
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


def topic_reliability(
    block: TranscriptBlock,
    *,
    retained_segment_indexes: set[int],
    selected_start_seconds: float | None,
    selected_end_seconds: float | None,
) -> dict[str, Any]:
    cleaned = _NOISE_MARKER.sub(" ", block.text)
    word_count = len(_LEXICAL_WORD.findall(cleaned))
    duration = max(0.0, block.end_seconds - block.start_seconds)
    overlap = (
        max(0.0, min(block.end_seconds, selected_end_seconds) - max(block.start_seconds, selected_start_seconds))
        if selected_start_seconds is not None and selected_end_seconds is not None
        else 0.0
    )
    retained = [index for index in block.segment_indexes if index in retained_segment_indexes]
    words_per_minute = word_count * 60.0 / duration if duration else 0.0
    return {
        "version": TOPIC_RELIABILITY_POLICY_VERSION,
        "analyzable_lexical_word_count": word_count,
        "block_duration_seconds": round(duration, 3),
        "analyzable_words_per_minute": round(words_per_minute, 3),
        "final_sermon_overlap_seconds": round(overlap, 3),
        "retained_source_segment_indexes": retained,
        "sparse": word_count < 20 or words_per_minute < 20.0,
        "non_analyzable": word_count == 0,
    }
