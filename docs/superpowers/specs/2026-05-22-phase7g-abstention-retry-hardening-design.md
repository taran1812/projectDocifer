# Phase 7G Design Spec — Abstention + Retry Hardening

**Date:** 2026-05-22  
**Status:** Approved  
**Baseline eval:** `phase7f_full_40q` — 40/40 evaluated, `abstention_correct_rate = 0.375`  
**Target:** `abstention_correct_rate >= 0.85`

---

## Problem Statement

Three distinct bugs cause `abstention_correct_rate = 0.375` (3/8 correct):

| Bug | Cases | Impact |
|---|---|---|
| False abstentions — model abstains on answerable questions | QA-017, QA-026, QA-031, QA-032 | 4 wrong |
| Contraction detection gap — "don't have" not in ABSTENTION_MARKERS | QA-039 | 1 wrong |
| Mixed Modality routing — visual-check fires before mixed-check | QA-027, QA-033 | off-mode retrieval |

Additionally: rate-limit errors (QA-036 429) are unhandled — one eval failure every large run.

---

## Fix 1 — Contraction Detection (metrics.py)

**Scope:** `backend/src/docifer_backend/evaluation/metrics.py`

Expand `ABSTENTION_MARKERS` to include contraction forms:

```python
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
```

Add contraction normalisation before marker scan in `_detect_abstention`:

```python
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
```

**Expected outcome:** QA-039 correctly scored as `abstention_correct=True`.

---

## Fix 2 — Mixed Modality Routing Priority (runner.py)

**Scope:** `backend/src/docifer_backend/evaluation/runner.py`, `resolve_evidence_mode()`

Current routing checks visual/figure/chart terms before the `"mixed"` branch. If `expected_evidence_type` for a Mixed Modality question contains "visual", it routes to `visual` before reaching `auto`.

New routing priority order (highest to lowest):

1. `"mixed" in category` → `"auto"`
2. `chart/visual/figure/image/graph` terms → `"visual"`
3. `"table" in category or "table" in expected` → `"table"`
4. default → `"text"`

Implementation:

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

**Expected outcome:** QA-027 and QA-033 route to `auto` (text+visual fusion) instead of `visual`-only.

---

## Fix 3 — Answer Prompt Abstention Threshold (openai_provider.py)

**Scope:** `backend/src/docifer_backend/providers/openai_provider.py`, `generate_grounded_answer()` instructions

Current prompt says: "If the evidence is insufficient, say you do not have enough evidence from the indexed document."

This threshold is too low — the model abstains on partial evidence.

New instructions:

```
You are Docifer's grounded document QA system. Answer only from the
provided evidence. Cite every factual claim with citation IDs like
[C1], [T1], or [V1].

Abstention rules:
- Abstain ONLY when the retrieved evidence has no direct support for
  the question, contradicts itself, or is missing the key entity or
  metric needed to answer.
- Do NOT abstain merely because the evidence is incomplete or partial.
- If the evidence supports a partial but useful answer, answer only
  the supported part and cite it.
- When evidence is partial, use cautious wording: "Based on the
  retrieved evidence...", "The document states...", or "The available
  evidence indicates...".
- When a computed table observation is provided, use it as the
  preferred table fact and cite only the table ID that supports it.
- When a visual observation is provided, cite only the visual ID that
  supports the visible claim and do not invent unreadable chart values.
```

**Expected outcome:** False abstentions on QA-017, QA-026, QA-031, QA-032 replaced by partial cited answers.

---

## Fix 4 — Abstention-Triggered Evidence Expansion Retry (query.py)

**Scope:** `backend/src/docifer_backend/retrieval/query.py`, `TextQueryService.query()`

Global top_k stays at 4. When the model abstains AND retrieved evidence existed, perform one retry with doubled evidence (top_k=8) and regenerate.

Retry conditions (ALL must be true):
- `_detect_abstention(answer)` is True
- `len(retrieved) > 0` (evidence was retrieved but model abstained anyway)
- `evidence_mode in {"text", "auto"}` (table/visual have their own evidence paths)
- Not already in a retry (no infinite loops)

Retry path:
1. Re-retrieve with `top_k * 2` (max 8)
2. Rebuild grounding evidence
3. Re-call `generate_grounded_answer`
4. Use retry answer regardless (even if it also abstains — one retry only)

Add the following fields to `debug` dict for observability:

```python
"abstention_retry_triggered": bool,
"initial_top_k": int,          # original top_k value
"retry_top_k": int | None,     # top_k used in retry (None if no retry)
"initial_answer_was_abstention": bool,
"retry_answer_was_abstention": bool | None,  # None if no retry
```

**Do not** add retry for table or visual evidence modes — the false abstentions are text-retrieval problems.

**Expected outcome:** QA-017, QA-026, QA-031, QA-032 get a second chance with deeper evidence before final abstention.

---

## Fix 5 — Rate-Limit Retry / Backoff (openai_provider.py)

**Scope:** `backend/src/docifer_backend/providers/openai_provider.py`

Wrap the three API call sites in exponential backoff:
- `generate_grounded_answer`
- `verify_citation_grounding`
- `interpret_visual_evidence`

Strategy:
- Catch `openai.RateLimitError` (HTTP 429)
- Retry up to **2 times**
- Backoff: `2^attempt` seconds (2s then 4s) with ±0.5s jitter
- After 2 retries: re-raise as `ProviderRateLimitError` (new exception class) so caller can mark `provider_failed`

```python
import time, random

def _with_retry(fn, max_retries=2):
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except openai.RateLimitError:
            if attempt == max_retries:
                raise
            sleep = (2 ** (attempt + 1)) + random.uniform(-0.5, 0.5)  # 2s, then 4s
            time.sleep(max(0, sleep))
```

Evaluation runner catches `ProviderRateLimitError` and marks result `status="provider_failed"` (separate from `"failed"`) so rate-limit cases are visible but not conflated with system errors.

---

## Implementation Order

1. Fix contraction detection (`metrics.py`) — isolated, no dependencies
2. Fix mixed routing priority (`runner.py`) — isolated, no dependencies
3. Update answer prompt (`openai_provider.py`) — no code structure change
4. Add retry/backoff wrappers (`openai_provider.py`) — add around existing calls
5. Add abstention-triggered retrieval retry (`query.py`) — depends on 3
6. Rerun eval on 8 abstention-related questions first (smoke test)
7. Full 40-question eval

---

## Verification Gate

**Pass criteria:**
- `abstention_correct_rate >= 0.75` after prompt fix alone (before retry)
- `abstention_correct_rate >= 0.85` after full fix set
- False abstentions (QA-017, QA-026, QA-031, QA-032): at least 3/4 now produce a partial cited answer
- QA-039: scored as `abstention_correct=True`
- QA-027, QA-033: mode=auto in run output
- No 429 failures in a 40-question eval (rate-limit retry works)
- Full test suite: 86+ passed, 0 new failures

---

## Files Changed

| File | Change |
|---|---|
| `backend/src/docifer_backend/evaluation/metrics.py` | Fix 1: contraction detection |
| `backend/src/docifer_backend/evaluation/runner.py` | Fix 2: routing priority |
| `backend/src/docifer_backend/providers/openai_provider.py` | Fix 3: prompt, Fix 5: retry/backoff |
| `backend/src/docifer_backend/retrieval/query.py` | Fix 4: abstention retry |

No new files. No schema changes. No new dependencies.
