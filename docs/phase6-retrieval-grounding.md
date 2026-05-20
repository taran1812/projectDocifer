# Phase 6 Retrieval Quality Upgrades and Citation Grounding

Phase 6 upgrades the text RAG baseline with BM25-style lexical retrieval, hybrid ranking, cleaner citation semantics, and citation-grounding verification.

## Implemented Components

- Dense retrieval remains available as the baseline.
- BM25-style lexical retrieval over persisted `text_chunks`.
- Hybrid retrieval combining normalized dense and BM25 scores.
- Retrieval score breakdowns in API responses.
- Separation of retrieved evidence, answer citations, and unused retrieved evidence.
- OpenAI-backed citation-grounding verifier.
- Evaluation runner support for retrieval modes and citation verification.
- Tests for BM25, hybrid retrieval, verifier plumbing, and citation cleanup.

## Retrieval Modes

The `/query` endpoint now accepts:

```json
{
  "retrieval_mode": "dense"
}
```

Allowed values:

- `dense`
- `bm25`
- `hybrid`

`dense` uses the Phase 4 OpenAI embedding + Qdrant path.

`bm25` uses local lexical scoring over Postgres `text_chunks`.

`hybrid` combines dense and BM25 result sets with normalized score fusion.

## Query Schema Additions

Request additions:

```json
{
  "retrieval_mode": "hybrid",
  "verify_citations": true
}
```

Response additions:

- `answer_citations`
- `retrieved_evidence`
- `unused_retrieved_evidence`
- `citation_verification`
- dense / lexical / hybrid score fields
- retrieval mode in evidence items

The existing `citations` and `evidence` fields remain for compatibility. `citations` now means final answer citations, not every retrieved chunk.

## Citation-Grounding Verifier

When `verify_citations` is true, Docifer sends:

- the question,
- the generated answer,
- retrieved evidence with citation IDs,

to the verifier.

The verifier returns:

- `supported`
- `partially_supported`
- `unsupported`
- supported citation IDs,
- weak citation IDs,
- unsupported claims,
- reasoning,
- optional revised answer.

If the verifier returns `unsupported`, Docifer replaces the answer with the verifier revision or an abstention message.

## Example API Request

```json
{
  "question": "Which strategy does the report recommend for upper-middle-income countries?",
  "content_hash": "8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8",
  "top_k": 3,
  "retrieval_mode": "hybrid",
  "verify_citations": true
}
```

Validated answer:

```text
For upper-middle-income countries, the report recommends shifting to a 3i strategy: investment + infusion + innovation. [C2]
```

Validated verifier verdict:

```json
{
  "verdict": "supported",
  "supported_citation_ids": ["C2"],
  "weak_citation_ids": [],
  "unsupported_claims": []
}
```

## Evaluation Comparisons

Runs created for the indexed `DOC-005` slice:

```text
phase6_doc005_dense
phase6_doc005_bm25
phase6_doc005_hybrid_verifier
```

Current results:

| Mode | Evaluated | Citation Presence | Avg Token Recall | P50 Latency ms | P95 Latency ms |
|---|---:|---:|---:|---:|---:|
| dense | 3 | 1.0 | 0.875 | 2095.07 | 3566.15 |
| bm25 | 3 | 1.0 | 0.7917 | 1145.56 | 2434.81 |
| hybrid + verifier | 3 | 1.0 | 0.875 | 3858.13 | 4137.9 |

Interpretation:

- Dense remains strong on this small text slice.
- BM25 is faster and useful for exact lexical matches.
- Hybrid + verifier preserves answer quality and adds citation-grounding verdicts at higher latency.
- The current three-question slice is too small to claim broad quality gains. The value of BM25 and hybrid retrieval should become clearer after more documents are ingested and indexed.

## Reranker Decision

A heavyweight cross-encoder or BGE-style reranker was not installed in this pass.

Reason:

- current indexed coverage is only one small document and three runnable golden questions,
- the extra model dependency and first-run download cost are not justified by this slice,
- BM25 + hybrid retrieval already gives the project a measurable retrieval-quality upgrade without adding a large local model dependency.

This is an explicit Phase 6 v1 decision. A cross-encoder reranker should be reconsidered after more documents are indexed and the eval harness has enough examples to measure the tradeoff.

## Validation

Commands run:

```powershell
backend\.venv\Scripts\pytest.exe backend\tests
```

Result:

```text
12 passed
```

Compile check:

```powershell
backend\.venv\Scripts\python.exe -m compileall -q backend\src backend\tests
```

Readiness:

```json
{
  "status": "ready",
  "checks": {
    "postgres": "ok",
    "qdrant": "ok"
  }
}
```

Real OpenAI-backed validation was run for:

- BM25 retrieval answer generation,
- hybrid retrieval answer generation,
- citation-grounding verification,
- FastAPI `/query` schema,
- dense / BM25 / hybrid-verifier eval comparisons.

## Phase 6 Gate Status

Phase 6 is valid for the currently indexed text baseline.

Satisfied:

- dense baseline remains runnable,
- BM25 retrieval works,
- hybrid retrieval works,
- answer citations are separated from retrieved evidence,
- unused retrieved evidence is exposed,
- citation-grounding verifier works,
- evaluation runner compares retrieval modes,
- cross-encoder reranker decision is documented with rationale.

Remaining future work:

- index more documents to broaden the benchmark,
- revisit cross-encoder reranking with enough eval coverage,
- add deeper citation correctness metrics after verifier outputs accumulate.
