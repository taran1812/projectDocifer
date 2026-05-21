from docifer_backend.config.settings import get_settings
import json

from docifer_backend.providers.base import CitationGroundingVerdict, GroundingEvidence


class OpenAIProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        embedding_model: str | None = None,
        answer_model: str | None = None,
    ) -> None:
        settings = get_settings()
        resolved_api_key = api_key or settings.openai_api_key
        if not resolved_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the OpenAI provider.")

        from openai import OpenAI

        self.client = OpenAI(api_key=resolved_api_key)
        self.embedding_model = embedding_model or settings.openai_embedding_model
        self.answer_model = answer_model or settings.openai_answer_model
        self.embedding_batch_size = settings.openai_embedding_batch_size

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.embedding_batch_size):
            batch = texts[start:start + self.embedding_batch_size]
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=batch,
            )
            embeddings.extend(item.embedding for item in response.data)
        return embeddings

    def generate_grounded_answer(
        self,
        *,
        question: str,
        evidence: list[GroundingEvidence],
    ) -> str:
        evidence_text = "\n\n".join(
            f"[{item.citation_id}] Source: {item.source}\n{item.text}"
            for item in evidence
        )
        response = self.client.responses.create(
            model=self.answer_model,
            instructions=(
                "You are Docifer's text RAG baseline. Answer only from the "
                "provided evidence. Cite every factual claim with citation IDs "
                "like [C1]. If the evidence is insufficient, say you do not "
                "have enough evidence from the indexed document."
            ),
            input=(
                f"Question:\n{question}\n\n"
                f"Evidence:\n{evidence_text}\n\n"
                "Write a concise grounded answer."
            ),
            max_output_tokens=500,
        )

        output_text = getattr(response, "output_text", None)
        if output_text:
            return output_text.strip()
        return str(response).strip()

    def verify_citation_grounding(
        self,
        *,
        question: str,
        answer: str,
        evidence: list[GroundingEvidence],
    ) -> CitationGroundingVerdict:
        evidence_text = "\n\n".join(
            f"[{item.citation_id}] Source: {item.source}\n{item.text}"
            for item in evidence
        )
        response = self.client.responses.create(
            model=self.answer_model,
            instructions=(
                "You are Docifer's citation-grounding verifier. Compare the "
                "answer against the evidence. Return only valid JSON with keys: "
                "verdict, supported_citation_ids, weak_citation_ids, "
                "unsupported_claims, reasoning, revised_answer. Verdict must be "
                "supported, partially_supported, or unsupported. If revision is "
                "not needed, revised_answer must be null."
            ),
            input=(
                f"Question:\n{question}\n\n"
                f"Answer:\n{answer}\n\n"
                f"Evidence:\n{evidence_text}\n\n"
                "Verify whether the answer's cited claims are semantically supported."
            ),
            max_output_tokens=700,
        )

        output_text = (getattr(response, "output_text", None) or "").strip()
        try:
            payload = json.loads(_strip_json_fence(output_text))
        except json.JSONDecodeError:
            return CitationGroundingVerdict(
                verdict="partially_supported",
                supported_citation_ids=[],
                weak_citation_ids=[],
                unsupported_claims=[],
                reasoning=f"Verifier returned non-JSON output: {output_text[:500]}",
                revised_answer=None,
            )

        return CitationGroundingVerdict(
            verdict=str(payload.get("verdict") or "partially_supported"),
            supported_citation_ids=list(payload.get("supported_citation_ids") or []),
            weak_citation_ids=list(payload.get("weak_citation_ids") or []),
            unsupported_claims=list(payload.get("unsupported_claims") or []),
            reasoning=str(payload.get("reasoning") or ""),
            revised_answer=payload.get("revised_answer"),
        )


def _strip_json_fence(text: str) -> str:
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text
