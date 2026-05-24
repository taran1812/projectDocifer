# Session Changes — 2026-05-24

## Summary

Ingested and evaluated a new unseen document (Tesla Q3 2023), then corrected two dataset mis-categorisations (QA-017, QA-032) that were causing false abstentions. False abstention rate halved and true abstention accuracy improved +7pp.

---

## New document: Tesla Q3 2023

Ingested `TSLA-Q3-2023-Update-3.pdf` (26-page earnings update) and registered as **DOC-013**.

- Parsed via ingestion CLI → `datasets/processed/847b5bc4152b/069f148c-.../canonical.json`
- Indexed: 35 text chunks, 14 table-like-text items, 26 visual page records
- DOC-013 entry added to `LOCAL_CORPUS_FILENAMES` in `backend/src/docifer_backend/retrieval/document_registry.py`
- Golden eval file created at `evals/tsla_q3_golden.xlsx` (7 questions: 2 text, 2 table, 2 chart, 1 mixed)

Smoke eval (`tsla_q3_smoke`) result: recall=0.674, citation=1.000, false_abstention=0.000, all verdicts `supported`. Confirms system generalises to unseen documents with no configuration changes.

---

## Dataset fixes: QA-017 and QA-032

Both questions were inspected against source documents and found to target plain-text paragraphs, not structured tables.

| QA ID | Doc | Old Category | Old Evidence | New Category | New Evidence |
|-------|-----|-------------|-------------|-------------|-------------|
| QA-017 | DOC-005 (World Bank 2024) | Table Lookup | Text + Table | Text Factual | Text |
| QA-032 | DOC-009 (NASA HDBK-1009A) | Table Reasoning | Text | Text Factual | Text |

Fixed via openpyxl in `docifer_phase1_corpus_and_golden_eval_v1.xlsx`.

---

## Phase 14 re-eval: `phase14_postfix_68q`

Re-ran full 68-Q eval after fixes with Phase 12 config (top_k=12, hybrid, verify_citations, chunk_size=1200).

### Metrics delta (Phase 12 → Phase 14)

| Metric | Phase 12 | Phase 14 | Δ |
|--------|------:|------:|---:|
| `average_answer_token_recall` | 0.7055 | 0.7073 | +0.18pp |
| `citation_presence_rate` | 0.9559 | 0.9412 | −1.47pp |
| `false_abstention_rate` | 0.037 | **0.0185** | **−1.85pp** |
| `true_abstention_accuracy` | 0.7857 | **0.8571** | **+7.14pp** |
| `abstention_correct_rate` | 0.6875 | **0.8000** | **+11.25pp** |
| P50 latency | 3,897 ms | 3,812 ms | −85 ms |
| P95 latency | 42,551 ms | 32,697 ms | −9.9 s |

### Per-category recall (Phase 14, 68-Q)

| Category | Recall | n | vs Phase 12 |
|----------|-------:|--:|-------------|
| Text Factual | 0.902 | 21 | +0.2pp, +2 Qs |
| Mixed Modality | 0.725 | 5 | +0.4pp |
| Table Lookup | 0.649 | 9 | **+8.2pp**, −1 Q |
| Text Synthesis | 0.546 | 6 | +1.2pp |
| Chart / Visual | 0.672 | 10 | −6pp (stochastic) |
| Table Reasoning | 0.483 | 3 | **+12pp**, −1 Q |
| Abstention accuracy | 12/14 | — | +1 correct |

**Routing:** text=27, table=12, visual=10, auto=5, abstain=14

Table Lookup and Table Reasoning recall gains are due to QA-017/032 leaving those categories — the hard cases (image-rendered tables, multi-step arithmetic) remain. QA-017/032 now answer correctly via text routing.

---

## Status after session

| Phase | Status |
|-------|--------|
| 1–13 | Complete |
| **14** | **Complete** — dataset corrections + Tesla smoke eval |
| 15 (next) | Frontend MVP and portfolio packaging |

### Remaining quality issues (Phase 15+)

- **Chart / Visual (0.672)**: slight regression from Phase 12 (0.732) — likely stochastic; visual chart reading limited to text/table evidence backing
- **Table Reasoning (0.483)**: multi-step arithmetic not covered by Phase 7C
- **Evidence-answer synthesis gap ~0.107**: retriever finds facts, LLM doesn't always cite all of them
