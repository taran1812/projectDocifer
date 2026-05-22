from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GroundingEvidence:
    citation_id: str
    text: str
    source: str


@dataclass(frozen=True)
class CitationGroundingVerdict:
    verdict: str
    supported_citation_ids: list[str]
    weak_citation_ids: list[str]
    unsupported_claims: list[str]
    reasoning: str
    revised_answer: str | None = None


@dataclass(frozen=True)
class VisualEvidenceInput:
    citation_id: str
    visual_id: str
    artifact_path: str | None
    metadata_text: str
    source: str


@dataclass(frozen=True)
class VisualObservation:
    citation_id: str
    visual_id: str
    observation_type: str
    question_answered: bool
    extracted_facts: list[str]
    visible_entities: list[str]
    numeric_values: list[str]
    confidence: float
    limitations: list[str]
    abstain_reason: str
    supported: bool
    reasoning: str


@dataclass(frozen=True)
class VisualInterpretationResult:
    status: str
    answer: str
    observations: list[VisualObservation]
    used_citation_ids: list[str]
    abstain_reason: str
    reasoning: str


class AIProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...

    def generate_grounded_answer(
        self,
        *,
        question: str,
        evidence: list[GroundingEvidence],
    ) -> str:
        ...

    def verify_citation_grounding(
        self,
        *,
        question: str,
        answer: str,
        evidence: list[GroundingEvidence],
    ) -> CitationGroundingVerdict:
        ...

    def interpret_visual_evidence(
        self,
        *,
        question: str,
        visual_evidence: list[VisualEvidenceInput],
    ) -> VisualInterpretationResult:
        ...


class ProviderRateLimitError(Exception):
    """Raised when a provider rate limit is exceeded after all retries."""
