from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from docifer_backend.evaluation.dataset import GoldenQuestion


ABSTENTION_MARKERS = (
    # First-person inability — requires "I" or system subject
    "i do not have enough evidence",
    "i don't have enough evidence",
    "i do not have sufficient evidence",
    "i don't have sufficient evidence",
    "i cannot answer",
    "i can't answer",
    "i cannot determine",
    "i can't determine",
    "i cannot provide",
    "i can't provide",
    "i cannot help",
    "i can't help",
    "i do not have",
    "i don't have",
    # System-level inability phrases
    "the retrieved evidence does not",
    "the retrieved evidence is insufficient",
    "the evidence does not contain",
    "no evidence was retrieved",
    "not provided in the evidence",
    "insufficient evidence to answer",
    "not enough evidence to answer",
    # Generic strong markers
    "unable to determine",
    "unable to answer",
)


@dataclass(frozen=True)
class TokenRecallResult:
    recall: float
    overlap_count: int
    expected_count: int


def token_recall(expected: str, observed: str) -> TokenRecallResult:
    expected_tokens = set(_tokens(expected))
    observed_tokens = set(_tokens(observed))
    if not expected_tokens:
        return TokenRecallResult(recall=0.0, overlap_count=0, expected_count=0)
    overlap = expected_tokens & observed_tokens
    return TokenRecallResult(
        recall=round(len(overlap) / len(expected_tokens), 4),
        overlap_count=len(overlap),
        expected_count=len(expected_tokens),
    )


@dataclass(frozen=True)
class EvaluationMetrics:
    answer_present: bool
    citation_count: int
    citation_presence: bool
    retrieved_evidence_count: int
    expected_answer_token_recall: float
    expected_answer_similarity: float
    abstention_detected: bool
    abstention_correct: bool | None
    top_score: float | None
    retrieved_evidence_token_recall: float | None = None
    answer_token_recall: float | None = None
    evidence_answer_gap: float | None = None
    retrieved_evidence_token_overlap_count: int | None = None
    answer_token_overlap_count: int | None = None
    expected_answer_token_count: int | None = None


def score_answer(
    *,
    question: GoldenQuestion,
    answer: str,
    citation_count: int,
    retrieved_evidence_count: int,
    retrieval_scores: list[float],
    retrieved_evidence_text: str = "",
) -> EvaluationMetrics:
    answer_text = answer.strip()
    abstention_detected = _detect_abstention(answer_text)

    evidence_recall = token_recall(question.expected_answer, retrieved_evidence_text)
    answer_recall = token_recall(question.expected_answer, answer_text)

    abstention_correct = None
    if question.should_abstain:
        abstention_correct = abstention_detected
    elif abstention_detected:
        abstention_correct = False

    return EvaluationMetrics(
        answer_present=bool(answer_text),
        citation_count=citation_count,
        citation_presence=citation_count > 0,
        retrieved_evidence_count=retrieved_evidence_count,
        expected_answer_token_recall=answer_recall.recall,
        expected_answer_similarity=round(
            SequenceMatcher(None, question.expected_answer.lower(), answer_text.lower()).ratio(),
            4,
        ),
        abstention_detected=abstention_detected,
        abstention_correct=abstention_correct,
        top_score=max(retrieval_scores) if retrieval_scores else None,
        retrieved_evidence_token_recall=evidence_recall.recall,
        answer_token_recall=answer_recall.recall,
        evidence_answer_gap=round(evidence_recall.recall - answer_recall.recall, 4),
        retrieved_evidence_token_overlap_count=evidence_recall.overlap_count,
        answer_token_overlap_count=answer_recall.overlap_count,
        expected_answer_token_count=evidence_recall.expected_count,
    )


def _detect_abstention(answer: str) -> bool:
    lowered = answer.lower()
    # normalise curly/smart apostrophes to straight before contraction replacement
    normalised = lowered.replace("’", "'").replace("‘", "'")
    normalised = (
        normalised
        .replace("don't", "do not")
        .replace("can't", "cannot")
        .replace("isn't", "is not")
        .replace("doesn't", "does not")
        .replace("won't", "will not")
        .replace("couldn't", "could not")
    )
    return any(marker in normalised for marker in ABSTENTION_MARKERS)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())
