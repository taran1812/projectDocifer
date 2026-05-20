from docifer_backend.config.settings import get_settings
from docifer_backend.providers.base import GroundingEvidence


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

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        response = self.client.embeddings.create(
            model=self.embedding_model,
            input=texts,
        )
        return [item.embedding for item in response.data]

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
