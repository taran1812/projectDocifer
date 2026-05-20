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
