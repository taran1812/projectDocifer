from __future__ import annotations

from dataclasses import asdict

from docifer_backend.providers.base import (
    GroundingEvidence,
    VisualEvidenceInput,
    VisualInterpretationResult,
    VisualObservation,
)
from docifer_backend.retrieval.visuals.schemas import (
    VisualQueryResult,
    format_visual_query_result_for_interpretation,
)


def build_visual_evidence_inputs(
    visual_results: list[VisualQueryResult],
    *,
    limit: int,
) -> list[VisualEvidenceInput]:
    inputs: list[VisualEvidenceInput] = []
    for index, visual in enumerate(visual_results[:limit], start=1):
        citation_id = f"V{index}"
        inputs.append(
            VisualEvidenceInput(
                citation_id=citation_id,
                visual_id=visual.visual_id,
                artifact_path=visual.artifact_path,
                metadata_text=format_visual_query_result_for_interpretation(visual),
                source=_format_visual_source(visual),
            )
        )
    return inputs


def visual_observations_to_grounding_evidence(
    interpretation: VisualInterpretationResult | None,
) -> list[GroundingEvidence]:
    if interpretation is None:
        return []
    evidence: list[GroundingEvidence] = []
    for observation in interpretation.observations:
        evidence.append(
            GroundingEvidence(
                citation_id=observation.citation_id,
                text=_format_observation_text(observation),
                source=f"visual:{observation.visual_id}",
            )
        )
    return evidence


def visual_interpretation_debug(
    interpretation: VisualInterpretationResult | None,
) -> dict | None:
    return asdict(interpretation) if interpretation is not None else None


def _format_visual_source(visual: VisualQueryResult) -> str:
    if visual.page_start and visual.page_end and visual.page_start != visual.page_end:
        page_label = f"pages {visual.page_start}-{visual.page_end}"
    elif visual.page_start:
        page_label = f"page {visual.page_start}"
    else:
        page_label = "page unknown"
    return f"visual:{visual.visual_id}, {visual.filename}, {page_label}"


def _format_observation_text(observation: VisualObservation) -> str:
    lines = [
        f"Status: {'supported' if observation.supported else 'not supported'}",
        f"Observation Type: {observation.observation_type}",
        f"Question Answered: {observation.question_answered}",
        f"Confidence: {observation.confidence}",
    ]
    if observation.extracted_facts:
        lines.append("Facts: " + "; ".join(observation.extracted_facts))
    if observation.visible_entities:
        lines.append("Visible Entities: " + "; ".join(observation.visible_entities))
    if observation.numeric_values:
        lines.append("Numeric Values: " + "; ".join(observation.numeric_values))
    if observation.limitations:
        lines.append("Limitations: " + "; ".join(observation.limitations))
    if observation.abstain_reason:
        lines.append(f"Abstain Reason: {observation.abstain_reason}")
    if observation.reasoning:
        lines.append(f"Reasoning: {observation.reasoning}")
    return "\n".join(lines)
