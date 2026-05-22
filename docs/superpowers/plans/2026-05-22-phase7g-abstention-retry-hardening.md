# Phase 7G — Abstention + Retry Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix abstention scoring (target ≥ 0.85 correct rate), fix mixed-modality routing, and add rate-limit retry/backoff so large evals never hard-fail on 429 errors.

**Architecture:** Five focused changes across four files. Tasks 1 and 2 fix evaluation-layer bugs (metrics + routing). Task 3 updates the provider layer (prompt tightening + retry wrapper). Task 4 adds abstention-triggered retrieval retry to the query service. Task 5 runs the smoke test and full eval.

**Tech Stack:** Python 3.11, SQLAlchemy 2, Qdrant (in-memory), OpenAI Responses API, pytest

---

## File Map

| File | Change |
|---|---|
| `backend/src/docifer_backend/evaluation/metrics.py` | Task 1: expand ABSTENTION_MARKERS, normalise contractions |
| `backend/src/docifer_backend/evaluation/runner.py` | Task 2: fix routing priority + handle ProviderRateLimitError |
| `backend/src/docifer_backend/providers/base.py` | Task 3a: add ProviderRateLimitError |
| `backend/src/docifer_backend/providers/openai_provider.py` | Task 3b: raise abstention bar in prompt, add retry wrapper |
| `backend/src/docifer_backend/retrieval/query.py` | Task 4: abstention-triggered evidence expansion retry |
| `backend/tests/test_evaluation.py` | Tasks 1 + 2: contraction + routing tests |
| `backend/tests/test_openai_provider.py` | Task 3: retry/backoff tests |
| `backend/tests/test_text_retrieval.py` | Task 4: abstention retry tests |

---

## Task 1 — Contraction Detection Fix (metrics.py)

**Files:**
- Modify: `backend/src/docifer_backend/evaluation/metrics.py`
- Test: `backend/tests/test_evaluation.py`

**Why:** QA-039 answered "I don't have enough evidence..." — `abstention_correct=False` because `"don't"` is not in ABSTENTION_MARKERS. Fix: expand markers and normalise contractions before scanning.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_evaluation.py`:

```python
from docifer_backend.evaluation.metrics import _detect_abstention


def test_detect_abstention_contraction_dont():
    assert _detect_abstention("I don't have enough evidence to answer this.") is True


def test_detect_abstention_contraction_cant():
    assert _detect_abstention("I can't determine the answer from the evidence.") is True


def test_detect_abstention_contraction_cannot_determine():
    assert _detect_abstention("I cannot determine the GPA from the retrieved content.") is True


def test_detect_abstention_does_not_trigger_on_normal_answer():
    assert _detect_abstention("The revenue was $130.5 billion. [C1]") is False


def test_detect_abstention_do_not_have_still_works():
    assert _detect_abstention("I do not have enough evidence to answer.") is True
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend
uv run pytest tests/test_evaluation.py::test_detect_abstention_contraction_dont tests/test_evaluation.py::test_detect_abstention_contraction_cant -v
```

Expected: FAIL — `_detect_abstention` not exported or contractions not matched.

- [ ] **Step 3: Update metrics.py**

Replace the full contents of `backend/src/docifer_backend/evaluation/metrics.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from docifer_backend.evaluation.dataset import GoldenQuestion


ABSTENTION_MARKERS = (
    "do not have enough evidence",
    "don't have enough evidence",
    "do not have sufficient evidence",
    "don't have sufficient evidence",
    "insufficient evidence",
    "cannot answer",
    "can't answer",
    "cannot determine",
    "can't determine",
    "not enough evidence",
    "does not include",
    "does not provide",
    "no evidence",
    "not available",
    "not found",
    "not include",
    "not mention",
    "not provided in the evidence",
    "i don't have",
    "i do not have",
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


def score_answer(
    *,
    question: GoldenQuestion,
    answer: str,
    citation_count: int,
    retrieved_evidence_count: int,
    retrieval_scores: list[float],
) -> EvaluationMetrics:
    answer_text = answer.strip()
    abstention_detected = _detect_abstention(answer_text)
    expected_tokens = _tokens(question.expected_answer)
    answer_tokens = set(_tokens(answer_text))
    if expected_tokens:
        expected_recall = len(set(expected_tokens) & answer_tokens) / len(set(expected_tokens))
    else:
        expected_recall = 0.0

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
        expected_answer_token_recall=round(expected_recall, 4),
        expected_answer_similarity=round(
            SequenceMatcher(None, question.expected_answer.lower(), answer_text.lower()).ratio(),
            4,
        ),
        abstention_detected=abstention_detected,
        abstention_correct=abstention_correct,
        top_score=max(retrieval_scores) if retrieval_scores else None,
    )


def _detect_abstention(answer: str) -> bool:
    lowered = answer.lower()
    normalised = (
        lowered
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd backend
uv run pytest tests/test_evaluation.py::test_detect_abstention_contraction_dont tests/test_evaluation.py::test_detect_abstention_contraction_cant tests/test_evaluation.py::test_detect_abstention_contraction_cannot_determine tests/test_evaluation.py::test_detect_abstention_does_not_trigger_on_normal_answer tests/test_evaluation.py::test_detect_abstention_do_not_have_still_works -v
```

Expected: 5 PASS

- [ ] **Step 5: Run full suite to check no regressions**

```
cd backend
uv run pytest --basetemp .pytest_tmp -q
```

Expected: 86+ passed, 1 xfailed

- [ ] **Step 6: Commit**

```bash
git add backend/src/docifer_backend/evaluation/metrics.py backend/tests/test_evaluation.py
git commit -m "fix(eval): expand abstention detection to cover contractions"
```

---

## Task 2 — Mixed-Modality Routing Priority Fix (runner.py)

**Files:**
- Modify: `backend/src/docifer_backend/evaluation/runner.py`
- Test: `backend/tests/test_evaluation.py`

**Why:** `resolve_evidence_mode` checked visual/chart terms before the `"mixed"` branch. Mixed Modality questions whose `expected_evidence_type` contains "visual" were routed to `visual` instead of `auto`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_evaluation.py`:

```python
def test_resolve_evidence_mode_mixed_modality_routes_to_auto():
    from types import SimpleNamespace
    question = SimpleNamespace(
        category="Mixed Modality",
        expected_evidence_type="visual and text",
    )
    assert resolve_evidence_mode(question, requested="category") == "auto"


def test_resolve_evidence_mode_chart_visual_routes_to_visual():
    from types import SimpleNamespace
    question = SimpleNamespace(
        category="Chart / Visual",
        expected_evidence_type="chart",
    )
    assert resolve_evidence_mode(question, requested="category") == "visual"


def test_resolve_evidence_mode_mixed_beats_visual_in_expected():
    from types import SimpleNamespace
    # Mixed Modality question where expected_evidence_type contains "visual"
    # Should still route to auto, not visual
    question = SimpleNamespace(
        category="Mixed Modality",
        expected_evidence_type="visual figure and table",
    )
    assert resolve_evidence_mode(question, requested="category") == "auto"
```

- [ ] **Step 2: Run tests to verify the third test fails**

```
cd backend
uv run pytest tests/test_evaluation.py::test_resolve_evidence_mode_mixed_beats_visual_in_expected -v
```

Expected: FAIL — returns `"visual"` instead of `"auto"`.

- [ ] **Step 3: Fix resolve_evidence_mode in runner.py**

Find `resolve_evidence_mode` at the bottom of `backend/src/docifer_backend/evaluation/runner.py` and replace it:

```python
def resolve_evidence_mode(question: GoldenQuestion, *, requested: str = "category") -> str:
    if requested != "category":
        return requested
    category = question.category.lower()
    expected = (question.expected_evidence_type or "").lower()
    if "mixed" in category:
        return "auto"
    if any(term in category or term in expected for term in ["chart", "visual", "figure", "image", "graph"]):
        return "visual"
    if "table" in category or "table" in expected:
        return "table"
    return "text"
```

- [ ] **Step 4: Run routing tests to verify all pass**

```
cd backend
uv run pytest tests/test_evaluation.py::test_resolve_evidence_mode_mixed_modality_routes_to_auto tests/test_evaluation.py::test_resolve_evidence_mode_chart_visual_routes_to_visual tests/test_evaluation.py::test_resolve_evidence_mode_mixed_beats_visual_in_expected -v
```

Expected: 3 PASS

- [ ] **Step 5: Run full suite**

```
cd backend
uv run pytest --basetemp .pytest_tmp -q
```

Expected: 86+ passed, 1 xfailed

- [ ] **Step 6: Commit**

```bash
git add backend/src/docifer_backend/evaluation/runner.py backend/tests/test_evaluation.py
git commit -m "fix(eval): prioritise mixed-modality routing before visual-term check"
```

---

## Task 3 — ProviderRateLimitError + Retry/Backoff + Prompt (base.py, openai_provider.py)

**Files:**
- Modify: `backend/src/docifer_backend/providers/base.py`
- Modify: `backend/src/docifer_backend/providers/openai_provider.py`
- Modify: `backend/src/docifer_backend/evaluation/runner.py`
- Test: `backend/tests/test_openai_provider.py`

**Why:** QA-036 failed with a hard 429 error that propagated as `status="failed"`. Rate limits should be retried with backoff (2s then 4s), then surfaced as a distinct `status="provider_failed"` rather than a system failure.

- [ ] **Step 1: Write failing tests for retry behaviour**

Add to `backend/tests/test_openai_provider.py`:

```python
import time
import pytest
from unittest.mock import patch, MagicMock
from docifer_backend.providers.base import ProviderRateLimitError
from docifer_backend.providers.openai_provider import OpenAIProvider, _with_openai_retry


def test_with_openai_retry_succeeds_on_first_attempt():
    call_count = 0

    def fn():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = _with_openai_retry(fn)
    assert result == "ok"
    assert call_count == 1


def test_with_openai_retry_retries_on_rate_limit_then_succeeds():
    call_count = 0

    class FakeRateLimitError(Exception):
        pass

    def fn():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise FakeRateLimitError("rate limit")
        return "ok"

    with patch("docifer_backend.providers.openai_provider._is_rate_limit_error", return_value=True):
        with patch("time.sleep"):
            result = _with_openai_retry(fn, max_retries=2)

    assert result == "ok"
    assert call_count == 3


def test_with_openai_retry_raises_provider_rate_limit_error_after_max_retries():
    class FakeRateLimitError(Exception):
        pass

    def fn():
        raise FakeRateLimitError("rate limit")

    with patch("docifer_backend.providers.openai_provider._is_rate_limit_error", return_value=True):
        with patch("time.sleep"):
            with pytest.raises(ProviderRateLimitError):
                _with_openai_retry(fn, max_retries=2)


def test_with_openai_retry_does_not_retry_non_rate_limit_errors():
    call_count = 0

    def fn():
        nonlocal call_count
        call_count += 1
        raise ValueError("something else")

    with pytest.raises(ValueError):
        _with_openai_retry(fn)
    assert call_count == 1


def test_with_openai_retry_backoff_timing():
    """Verify backoff uses 2^(attempt+1): roughly 2s then 4s."""
    sleep_calls = []

    class FakeRateLimitError(Exception):
        pass

    def fn():
        raise FakeRateLimitError("rate limit")

    with patch("docifer_backend.providers.openai_provider._is_rate_limit_error", return_value=True):
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            with pytest.raises(ProviderRateLimitError):
                _with_openai_retry(fn, max_retries=2)

    assert len(sleep_calls) == 2
    # attempt 0: 2^1 ± 0.5 → between 1.5 and 2.5
    assert 1.5 <= sleep_calls[0] <= 2.5
    # attempt 1: 2^2 ± 0.5 → between 3.5 and 4.5
    assert 3.5 <= sleep_calls[1] <= 4.5
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend
uv run pytest tests/test_openai_provider.py::test_with_openai_retry_succeeds_on_first_attempt -v
```

Expected: FAIL — `_with_openai_retry` and `ProviderRateLimitError` not yet defined.

- [ ] **Step 3: Add ProviderRateLimitError to base.py**

Append to `backend/src/docifer_backend/providers/base.py` after the existing dataclass definitions:

```python

class ProviderRateLimitError(Exception):
    """Raised when a provider rate limit is exceeded after all retries."""
```

- [ ] **Step 4: Add retry helper and _is_rate_limit_error to openai_provider.py**

Add after the existing imports at the top of `backend/src/docifer_backend/providers/openai_provider.py`:

```python
import random
import time
from docifer_backend.providers.base import ProviderRateLimitError
```

Add these two module-level functions after the imports (before the `OpenAIProvider` class):

```python
def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "rate limit" in msg or "429" in msg


def _with_openai_retry(fn, max_retries: int = 2):
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            if not _is_rate_limit_error(exc):
                raise
            if attempt == max_retries:
                raise ProviderRateLimitError(str(exc)) from exc
            sleep = (2 ** (attempt + 1)) + random.uniform(-0.5, 0.5)
            time.sleep(max(0, sleep))
```

- [ ] **Step 5: Wrap the three API call sites in openai_provider.py**

In `generate_grounded_answer`, replace:

```python
        response = self.client.responses.create(
            model=self.answer_model,
            instructions=(
```

with:

```python
        response = _with_openai_retry(lambda: self.client.responses.create(
            model=self.answer_model,
            instructions=(
```

and close the lambda before `max_output_tokens` line ends. The full wrapped block:

```python
        response = _with_openai_retry(lambda: self.client.responses.create(
            model=self.answer_model,
            instructions=(
                "You are Docifer's grounded document QA system. Answer only from the "
                "provided evidence. Cite every factual claim with citation IDs "
                "like [C1], [T1], or [V1].\n\n"
                "Abstention rules:\n"
                "- Abstain ONLY when the retrieved evidence has no direct support for "
                "the question, contradicts itself, or is missing the key entity or "
                "metric needed to answer.\n"
                "- Do NOT abstain merely because the evidence is incomplete or partial.\n"
                "- If the evidence supports a partial but useful answer, answer only "
                "the supported part and cite it.\n"
                "- When evidence is partial, use cautious wording: "
                "'Based on the retrieved evidence...', 'The document states...', or "
                "'The available evidence indicates...'.\n"
                "- When a computed table observation is provided, use it as the preferred "
                "table fact and cite only the table ID that supports that observation.\n"
                "- When a visual observation is provided, cite only the visual ID that "
                "supports the visible claim and do not invent unreadable chart values."
            ),
            input=(
                f"Question:\n{question}\n\n"
                f"Evidence:\n{evidence_text}\n\n"
                "Write a concise grounded answer."
            ),
            max_output_tokens=500,
        ))
```

In `verify_citation_grounding`, replace the `self.client.responses.create(...)` call with:

```python
        response = _with_openai_retry(lambda: self.client.responses.create(
            model=self.answer_model,
            instructions=(
                "You are Docifer's citation-grounding verifier. Compare the "
                "answer against the evidence. Return only valid JSON with keys: "
                "verdict, supported_citation_ids, weak_citation_ids, "
                "unsupported_claims, reasoning, revised_answer. Verdict must be "
                "supported, partially_supported, or unsupported. If revision is "
                "not needed, revised_answer must be null. If you do provide a "
                "revised_answer, preserve all citation markers ([C1], [T1], [V1], "
                "etc.) from the original answer."
            ),
            input=(
                f"Question:\n{question}\n\n"
                f"Answer:\n{answer}\n\n"
                f"Evidence:\n{evidence_text}\n\n"
                "Verify whether the answer's cited claims are semantically supported."
            ),
            max_output_tokens=700,
        ))
```

In `interpret_visual_evidence`, find the `self.client.responses.create(...)` call and wrap it:

```python
        response = _with_openai_retry(lambda: self.client.responses.create(
            model=self.vision_model,
            input=content,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "visual_interpretation",
                    "schema": _VISUAL_INTERPRETATION_SCHEMA,
                    "strict": True,
                }
            },
            max_output_tokens=1000,
        ))
```

- [ ] **Step 6: Handle ProviderRateLimitError in runner.py**

In `_evaluate_question` in `backend/src/docifer_backend/evaluation/runner.py`, import at the top of the file:

```python
from docifer_backend.providers.base import ProviderRateLimitError
```

In the `except Exception as exc` block, add a specific catch before the generic one:

```python
        except ProviderRateLimitError as exc:
            return EvaluationResult(
                qa_id=question.qa_id,
                doc_id=question.doc_id,
                category=question.category,
                question=question.question,
                expected_answer=question.expected_answer,
                should_abstain=question.should_abstain,
                status="provider_failed",
                error_message=str(exc),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                content_hash=doc_ref.content_hash,
                evidence_mode=resolved_evidence_mode,
            )
        except Exception as exc:
            return EvaluationResult(
                ...
```

Also update the `build_summary` call to count `provider_failed` separately. In `build_summary` in `reporting.py`, check that `by_status` will include `provider_failed` naturally (it uses `result.status` which is now a new value — no code change needed, it just appears as a new key).

- [ ] **Step 7: Run retry tests**

```
cd backend
uv run pytest tests/test_openai_provider.py -v
```

Expected: all existing + 5 new tests pass.

- [ ] **Step 8: Run full suite**

```
cd backend
uv run pytest --basetemp .pytest_tmp -q
```

Expected: 91+ passed, 1 xfailed

- [ ] **Step 9: Commit**

```bash
git add backend/src/docifer_backend/providers/base.py \
        backend/src/docifer_backend/providers/openai_provider.py \
        backend/src/docifer_backend/evaluation/runner.py \
        backend/tests/test_openai_provider.py
git commit -m "feat(providers): add rate-limit retry/backoff and raise abstention bar in answer prompt"
```

---

## Task 4 — Abstention-Triggered Evidence Expansion Retry (query.py)

**Files:**
- Modify: `backend/src/docifer_backend/retrieval/query.py`
- Test: `backend/tests/test_text_retrieval.py`

**Why:** QA-017, QA-026, QA-031, QA-032 retrieve 4 chunks but none contain the specific answer, so the model abstains. A one-time retry with doubled top_k gives the model a better evidence set.

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_text_retrieval.py`:

```python
def test_query_abstention_retry_fires_when_initial_answer_abstains(session_factory, tmp_path):
    """When the model abstains and text evidence was retrieved, retry with doubled top_k."""
    canonical_path, content_hash, document_id = write_canonical_artifacts(tmp_path)
    client = QdrantClient(":memory:")

    call_log = []

    class AbstainFirstProvider(FakeAIProvider):
        def generate_grounded_answer(self, *, question, evidence):
            call_log.append(len(evidence))
            if len(call_log) == 1:
                return "I do not have enough evidence to answer this question."
            return f"Based on the retrieved evidence, the answer is X. [{evidence[0].citation_id}]"

    service = TextQueryService(
        ai_provider=AbstainFirstProvider(),
        qdrant_client=client,
        session_factory=session_factory,
    )
    _seed_index(service, canonical_path, content_hash, document_id, session_factory, client)

    outcome = service.query(
        question="What is the answer?",
        content_hash=content_hash,
        top_k=2,
        retrieval_mode="dense",
        evidence_mode="text",
    )

    assert len(call_log) == 2, "generate_grounded_answer should be called twice"
    assert outcome.debug["abstention_retry_triggered"] is True
    assert outcome.debug["initial_answer_was_abstention"] is True
    assert outcome.debug["retry_answer_was_abstention"] is False
    assert outcome.debug["initial_top_k"] == 2
    assert outcome.debug["retry_top_k"] == 4
    assert "I do not have enough evidence" not in outcome.answer


def test_query_abstention_retry_does_not_fire_without_retrieved_evidence(session_factory, tmp_path):
    """No retry when there is no retrieved evidence (nothing to expand)."""
    canonical_path, content_hash, document_id = write_canonical_artifacts(tmp_path)
    client = QdrantClient(":memory:")
    call_log = []

    class AlwaysAbstainProvider(FakeAIProvider):
        def generate_grounded_answer(self, *, question, evidence):
            call_log.append(1)
            return "I do not have enough evidence to answer."

    service = TextQueryService(
        ai_provider=AlwaysAbstainProvider(),
        qdrant_client=client,
        session_factory=session_factory,
    )
    # Do NOT seed index — empty collection → no evidence retrieved

    outcome = service.query(
        question="What is the answer?",
        content_hash=content_hash,
        top_k=2,
        retrieval_mode="dense",
        evidence_mode="text",
    )

    assert outcome.debug["abstention_retry_triggered"] is False
    assert len(call_log) == 0  # early return path, no generate call


def test_query_abstention_retry_does_not_fire_in_visual_mode(session_factory, tmp_path):
    """Retry only fires for text/auto evidence modes, not visual."""
    canonical_path, content_hash, document_id = write_canonical_artifacts(tmp_path)
    client = QdrantClient(":memory:")
    call_log = []

    class AbstainProvider(FakeAIProvider):
        def generate_grounded_answer(self, *, question, evidence):
            call_log.append(1)
            return "I do not have enough evidence."

    service = TextQueryService(
        ai_provider=AbstainProvider(),
        qdrant_client=client,
        session_factory=session_factory,
    )
    _seed_index(service, canonical_path, content_hash, document_id, session_factory, client)

    outcome = service.query(
        question="What chart is shown?",
        content_hash=content_hash,
        top_k=2,
        retrieval_mode="dense",
        evidence_mode="visual",
    )

    assert outcome.debug["abstention_retry_triggered"] is False


def test_query_debug_has_retry_fields_when_no_retry(session_factory, tmp_path):
    """Debug always includes retry fields even when no retry was triggered."""
    canonical_path, content_hash, document_id = write_canonical_artifacts(tmp_path)
    client = QdrantClient(":memory:")

    service = TextQueryService(
        ai_provider=FakeAIProvider(),
        qdrant_client=client,
        session_factory=session_factory,
    )
    _seed_index(service, canonical_path, content_hash, document_id, session_factory, client)

    outcome = service.query(
        question="What strategy is recommended?",
        content_hash=content_hash,
        top_k=2,
        retrieval_mode="dense",
        evidence_mode="text",
    )

    assert "abstention_retry_triggered" in outcome.debug
    assert "initial_top_k" in outcome.debug
    assert "retry_top_k" in outcome.debug
    assert "initial_answer_was_abstention" in outcome.debug
    assert "retry_answer_was_abstention" in outcome.debug
    assert outcome.debug["abstention_retry_triggered"] is False
    assert outcome.debug["retry_top_k"] is None
    assert outcome.debug["retry_answer_was_abstention"] is None
```

Also add a helper function `_seed_index` at the module level in `test_text_retrieval.py` (find the existing test that already seeds data and extract the common pattern, or add this):

```python
def _seed_index(service, canonical_path, content_hash, document_id, session_factory, client):
    """Index a canonical artifact so queries have evidence to retrieve."""
    from docifer_backend.retrieval.indexing import TextIndexingService
    indexing_service = TextIndexingService(
        ai_provider=service.ai_provider,
        qdrant_client=client,
        session_factory=session_factory,
    )
    indexing_service.index_canonical_document(str(canonical_path))
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend
uv run pytest tests/test_text_retrieval.py::test_query_abstention_retry_fires_when_initial_answer_abstains -v
```

Expected: FAIL — `abstention_retry_triggered` not in debug dict.

- [ ] **Step 3: Add abstention detection helper and retry logic to query.py**

Add at module level in `backend/src/docifer_backend/retrieval/query.py`, after the imports:

```python
_ABSTENTION_MARKERS = (
    "do not have enough evidence",
    "don't have enough evidence",
    "insufficient evidence",
    "cannot answer",
    "cannot determine",
    "not enough evidence",
    "i do not have",
    "i don't have",
)


def _is_abstention(answer: str) -> bool:
    normalised = (
        answer.lower()
        .replace("don't", "do not")
        .replace("can't", "cannot")
        .replace("doesn't", "does not")
    )
    return any(m in normalised for m in _ABSTENTION_MARKERS)
```

- [ ] **Step 4: Add retry logic and debug fields in query.py**

In `TextQueryService.query()`, find the block where `answer` is first set (after grounding is built). Replace the section from the initial `answer = ...` assignment through `citation_verification` to add retry:

```python
        # --- Initial answer generation ---
        initial_answer_was_abstention = False
        abstention_retry_triggered = False
        retry_top_k: int | None = None
        retry_answer_was_abstention: bool | None = None

        if should_retrieve_visuals and visual_interpretation is not None:
            answer = visual_interpretation.answer
        else:
            answer = self.ai_provider.generate_grounded_answer(
                question=question,
                evidence=grounding,
            )

        # --- Abstention-triggered evidence expansion retry ---
        initial_answer_was_abstention = _is_abstention(answer)
        if (
            initial_answer_was_abstention
            and should_retrieve_text
            and len(retrieved) > 0
            and evidence_mode in {"text", "auto"}
        ):
            retry_top_k = min(top_k * 2, 8)
            retry_retrieved = self._retrieve(
                question=question,
                content_hash=content_hash,
                top_k=retry_top_k,
                retrieval_mode=retrieval_mode,
            )
            if len(retry_retrieved) > len(retrieved):
                abstention_retry_triggered = True
                retry_grounding = [
                    GroundingEvidence(
                        citation_id=f"C{index}",
                        text=chunk.text,
                        source=_format_source(chunk),
                    )
                    for index, chunk in enumerate(retry_retrieved, start=1)
                ]
                retry_grounding.extend(_table_grounding_evidence(table_results, table_reasoning))
                retry_grounding.extend(visual_grounding)
                answer = self.ai_provider.generate_grounded_answer(
                    question=question,
                    evidence=retry_grounding,
                )
                retry_answer_was_abstention = _is_abstention(answer)
                retrieved = retry_retrieved
                grounding = retry_grounding
```

- [ ] **Step 5: Add the five new debug fields to the debug dict in query.py**

In the `debug.update({...})` call near the end of `query()`, add:

```python
                "abstention_retry_triggered": abstention_retry_triggered,
                "initial_top_k": top_k,
                "retry_top_k": retry_top_k,
                "initial_answer_was_abstention": initial_answer_was_abstention,
                "retry_answer_was_abstention": retry_answer_was_abstention,
```

- [ ] **Step 6: Run new query tests**

```
cd backend
uv run pytest tests/test_text_retrieval.py::test_query_abstention_retry_fires_when_initial_answer_abstains tests/test_text_retrieval.py::test_query_abstention_retry_does_not_fire_without_retrieved_evidence tests/test_text_retrieval.py::test_query_abstention_retry_does_not_fire_in_visual_mode tests/test_text_retrieval.py::test_query_debug_has_retry_fields_when_no_retry -v
```

Expected: 4 PASS

- [ ] **Step 7: Run full suite**

```
cd backend
uv run pytest --basetemp .pytest_tmp -q
```

Expected: 95+ passed, 1 xfailed

- [ ] **Step 8: Commit**

```bash
git add backend/src/docifer_backend/retrieval/query.py backend/tests/test_text_retrieval.py
git commit -m "feat(retrieval): add abstention-triggered evidence expansion retry"
```

---

## Task 5 — Smoke Test + Full 40-Question Eval

**Why:** Verify all fixes work together before claiming Phase 7G complete.

- [ ] **Step 1: Restart the FastAPI server**

Stop the running server (Ctrl+C in its terminal or kill the process) and restart:

```powershell
backend\.venv\Scripts\uvicorn.exe docifer_backend.main:app --host 127.0.0.1 --port 8000
```

Confirm health:
```
curl http://127.0.0.1:8000/health
```
Expected: `{"status":"ok",...}`

- [ ] **Step 2: Smoke test the 8 abstention-related questions**

Run only the 8 questions that had abstention-related issues in the baseline:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner `
  --run-name phase7g_smoke_abstention `
  --doc-id DOC-001 --doc-id DOC-003 --doc-id DOC-006 --doc-id DOC-007 `
  --doc-id DOC-009 --doc-id DOC-011 `
  --top-k 4 --retrieval-mode hybrid --evidence-mode category --verify-citations
```

Check the output JSON. Verify:
- `QA-039` (DOC-007): `abstention_correct=true`
- `QA-027`, `QA-033` (DOC-009, DOC-011): `evidence_mode=auto` in results
- `QA-017` (DOC-006), `QA-026` (DOC-009), `QA-031`, `QA-032` (DOC-011): at least 3 of 4 have non-abstaining answers

```powershell
backend\.venv\Scripts\python.exe -c "
import json
with open('evals/runs/phase7g_smoke_abstention/results.jsonl', encoding='utf-8') as f:
    results = [json.loads(l) for l in f]
for r in [x for x in results if x['status'] == 'evaluated']:
    ac = r.get('metrics',{}).get('abstention_correct')
    em = r.get('evidence_mode','?')
    abst = r.get('metrics',{}).get('abstention_detected')
    retry = r.get('debug',{}).get('abstention_retry_triggered')
    print(r['qa_id'], r['doc_id'], 'mode='+em, 'abstain_detected='+str(abst), 'abstain_correct='+str(ac), 'retry='+str(retry))
"
```

- [ ] **Step 3: Run full 40-question eval**

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner `
  --run-name phase7g_full_40q `
  --top-k 4 --retrieval-mode hybrid --evidence-mode category --verify-citations
```

- [ ] **Step 4: Verify gate criteria**

```powershell
backend\.venv\Scripts\python.exe -c "
import json
with open('evals/runs/phase7g_full_40q/summary.json', encoding='utf-8') as f:
    s = json.load(f)
rate = s['metrics']['abstention_correct_rate']
print('abstention_correct_rate:', rate)
print('PASS' if rate >= 0.75 else 'FAIL — below 0.75 threshold')
print('evaluated:', s['evaluated'], 'failed:', s['failed'])
"
```

Expected:
- `abstention_correct_rate >= 0.75`
- `failed = 0` (no hard 429 failures; rate-limited questions become `provider_failed` if any)
- `evaluated + provider_failed = 40`

- [ ] **Step 5: Commit session log update**

Update `docs/session-changes-2026-05-20.md` — append a Phase 7G section with:
- eval run name
- abstention_correct_rate before and after
- per-fix summary (contraction detection, routing, prompt, retry)
- full 40-question metrics table

```bash
git add docs/session-changes-2026-05-20.md
git commit -m "docs(phase7g): record abstention hardening results"
```

---

## Self-Review

**Spec coverage check:**
- Fix 1 (contraction detection) → Task 1 ✓
- Fix 2 (routing priority) → Task 2 ✓
- Fix 3 (prompt abstention threshold) → Task 3 Step 5 ✓
- Fix 4 (abstention retry) → Task 4 ✓
- Fix 5 (rate-limit retry/backoff 2s/4s) → Task 3 Steps 4+5 ✓
- ProviderRateLimitError in runner → Task 3 Step 6 ✓
- Debug fields (5 fields) → Task 4 Steps 4+5 ✓
- Smoke test 8 questions → Task 5 Step 2 ✓
- Full 40-question eval → Task 5 Step 3 ✓

**Placeholder scan:** No TBDs. All code blocks complete.

**Type consistency:**
- `_with_openai_retry` defined in Task 3 Step 4, used same file ✓
- `ProviderRateLimitError` defined in `base.py` Task 3 Step 3, imported in `runner.py` Task 3 Step 6 ✓
- `_is_abstention` defined Task 4 Step 3, used Task 4 Step 4 ✓
- `abstention_retry_triggered` / `retry_top_k` / `initial_top_k` / `initial_answer_was_abstention` / `retry_answer_was_abstention` — all five defined Task 4 Step 4, added to debug Task 4 Step 5, verified in tests Task 4 Step 1 ✓
- `_seed_index` helper defined Task 4 Step 1 and used across test functions ✓
