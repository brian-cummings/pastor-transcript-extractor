from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SEMANTIC_ANALYSIS_QUESTION_VERSION = "sermon-semantic-dimensions-v1"


@dataclass(frozen=True, slots=True)
class SemanticDimension:
    description: str
    true_criteria: str
    false_criteria: str


SEMANTIC_DIMENSION_SPECS: dict[str, SemanticDimension] = {
    "exegetical_exposition": SemanticDimension(
        description=(
            "Explains the meaning, context, wording, structure, or implications of a "
            "biblical text. A quotation or reference without explanation is insufficient."
        ),
        true_criteria=(
            "The target block actually explains a biblical text's meaning, language, "
            "context, structure, relationship, or implications."
        ),
        false_criteria=(
            "The target block only quotes, reads, names, or alludes to Scripture, makes "
            "an unsupported doctrinal claim, or does not explain a biblical text."
        ),
    ),
    "narrative_illustration": SemanticDimension(
        description=(
            "Recounts a concrete personal experience, observed event, or developed story "
            "to illuminate a sermon's point. A passing example or hypothetical is insufficient."
        ),
        true_criteria=(
            "The target block develops a concrete event or story with actors and actions "
            "and uses it to illuminate the message."
        ),
        false_criteria=(
            "The target block contains only a passing example, hypothetical, announcement, "
            "quoted biblical narrative, or no developed illustrative story."
        ),
    ),
    "doctrinal_argument": SemanticDimension(
        description=(
            "Develops a reasoned claim about Christian belief using premises, distinctions, "
            "support, consequences, or responses to alternatives. A bare assertion is insufficient."
        ),
        true_criteria=(
            "The target block reasons toward or supports a Christian doctrinal claim using "
            "premises, distinctions, consequences, or responses to alternatives."
        ),
        false_criteria=(
            "The target block merely states or mentions a belief, quotes Scripture without "
            "doctrinal reasoning, or does not develop a Christian doctrinal argument."
        ),
    ),
    "practical_application": SemanticDimension(
        description=(
            "Directs listeners toward a concrete action, practice, decision, relationship, "
            "or lived response. Generic encouragement without a specific response is insufficient."
        ),
        true_criteria=(
            "The target block directs listeners toward a specific action, practice, decision, "
            "relationship, or observable lived response."
        ),
        false_criteria=(
            "The target block offers only generic encouragement, a slogan, an abstract value, "
            "or no specific lived response."
        ),
    ),
}

# Existing style analysis and the TypeSafe fine pass share this exact inventory.
SEMANTIC_DIMENSIONS: dict[str, str] = {
    name: spec.description for name, spec in SEMANTIC_DIMENSION_SPECS.items()
}


def semantic_question_id(position: int, dimension: str) -> str:
    if dimension not in SEMANTIC_DIMENSION_SPECS:
        raise ValueError(f"Unknown semantic dimension: {dimension}")
    return f"semantic_{position}_{dimension}"


def semantic_question_inventory(position: int) -> dict[str, dict[str, Any]]:
    target = f"target_blocks[{position}].text"
    return {
        semantic_question_id(position, name): {
            "kind": "noul",
            "dimension": name,
            "instructions": {
                "task": f"Decide whether `{target}` contains {spec.description}",
                "scope": (
                    "Judge only the referenced target block. Recording metadata and the "
                    "surrounding recording outline are context, not evidence for this property."
                ),
                "caption_handling": (
                    "Do not treat duplicated captions, rhetorical questions, quoted dialogue, "
                    "or brief congregational responses as proof of the property."
                ),
            },
            "criteria": {
                "true": spec.true_criteria,
                "false": spec.false_criteria,
            },
        }
        for name, spec in SEMANTIC_DIMENSION_SPECS.items()
    }
