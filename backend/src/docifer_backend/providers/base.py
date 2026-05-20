from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GroundingEvidence:
    citation_id: str
    text: str
    source: str


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
