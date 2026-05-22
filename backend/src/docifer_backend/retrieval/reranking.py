from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from docifer_backend.config.settings import get_settings
from docifer_backend.retrieval.vector_store import RetrievedChunk


@dataclass(frozen=True)
class RerankResult:
    chunk_id: str
    rerank_score: float
    original_rank: int
    reranked_rank: int


class RerankerUnavailableError(RuntimeError):
    """Raised when the optional local reranker runtime is not available."""


class CrossEncoderReranker:
    def __init__(
        self,
        *,
        model_name: str | None = None,
        device: str | None = None,
        batch_size: int | None = None,
        max_length: int | None = None,
    ) -> None:
        settings = get_settings()
        self.model_name = model_name or settings.reranker_model
        self.device = (device or settings.reranker_device).lower()
        self.batch_size = batch_size or settings.reranker_batch_size
        self.max_length = max_length or settings.reranker_max_length
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._torch: Any | None = None
        self._resolved_device: str | None = None

    def rerank(
        self,
        question: str,
        evidence: list[RetrievedChunk],
        *,
        top_k: int,
    ) -> list[RetrievedChunk]:
        if top_k < 1:
            return []
        if not evidence:
            return []

        scores = self._score(question=question, evidence=evidence)
        ranked = sorted(
            zip(evidence, scores, range(1, len(evidence) + 1), strict=True),
            key=lambda item: item[1],
            reverse=True,
        )
        return [
            replace(
                chunk,
                score=float(score),
                rerank_score=float(score),
                pre_rerank_rank=original_rank,
                post_rerank_rank=reranked_rank,
                reranker_model=self.model_name,
            )
            for reranked_rank, (chunk, score, original_rank) in enumerate(
                ranked[:top_k],
                start=1,
            )
        ]

    def _score(self, *, question: str, evidence: list[RetrievedChunk]) -> list[float]:
        tokenizer, model, torch, device = self._load()
        scores: list[float] = []
        for start in range(0, len(evidence), self.batch_size):
            batch = evidence[start : start + self.batch_size]
            encoded = tokenizer(
                [question] * len(batch),
                [chunk.text for chunk in batch],
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            encoded = {
                key: value.to(device)
                for key, value in encoded.items()
            }
            with torch.no_grad():
                outputs = model(**encoded)
                logits = outputs.logits
                if len(logits.shape) == 1:
                    batch_scores = logits
                elif logits.shape[-1] == 1:
                    batch_scores = logits[:, 0]
                else:
                    batch_scores = logits[:, -1]
                scores.extend(float(score) for score in batch_scores.detach().cpu().tolist())
        return scores

    def _load(self) -> tuple[Any, Any, Any, str]:
        if self._tokenizer is not None and self._model is not None and self._torch is not None:
            return self._tokenizer, self._model, self._torch, self._resolved_device or "cpu"
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except Exception as exc:  # pragma: no cover - exercised through fallback tests.
            raise RerankerUnavailableError(
                "Local reranker dependencies are unavailable. Install transformers and torch."
            ) from exc

        resolved_device = self.device
        if resolved_device == "auto":
            resolved_device = "cuda" if torch.cuda.is_available() else "cpu"

        try:
            tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
            model.to(resolved_device)
            model.eval()
        except Exception as exc:  # pragma: no cover - model downloads are integration-tested manually.
            raise RerankerUnavailableError(f"Could not load reranker model {self.model_name}.") from exc

        self._tokenizer = tokenizer
        self._model = model
        self._torch = torch
        self._resolved_device = resolved_device
        return tokenizer, model, torch, resolved_device


class FakeReranker:
    def __init__(
        self,
        *,
        scores_by_chunk_id: dict[str, float] | None = None,
        fail: bool = False,
        model_name: str = "fake-reranker",
    ) -> None:
        self.scores_by_chunk_id = scores_by_chunk_id or {}
        self.fail = fail
        self.model_name = model_name
        self.calls: list[dict[str, int | str]] = []

    def rerank(
        self,
        question: str,
        evidence: list[RetrievedChunk],
        *,
        top_k: int,
    ) -> list[RetrievedChunk]:
        self.calls.append(
            {
                "question": question,
                "candidate_count": len(evidence),
                "top_k": top_k,
            }
        )
        if self.fail:
            raise RuntimeError("fake reranker failed")
        ranked = sorted(
            zip(evidence, range(1, len(evidence) + 1), strict=True),
            key=lambda item: self.scores_by_chunk_id.get(
                item[0].chunk_id,
                float(len(evidence) - item[1]),
            ),
            reverse=True,
        )
        results: list[RetrievedChunk] = []
        for reranked_rank, (chunk, original_rank) in enumerate(ranked[:top_k], start=1):
            score = self.scores_by_chunk_id.get(chunk.chunk_id, float(len(evidence) - original_rank))
            results.append(
                replace(
                    chunk,
                    score=float(score),
                    rerank_score=float(score),
                    pre_rerank_rank=original_rank,
                    post_rerank_rank=reranked_rank,
                    reranker_model=self.model_name,
                )
            )
        return results
