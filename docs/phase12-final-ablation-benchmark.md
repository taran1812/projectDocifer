# Phase 12 Final Ablation Benchmark

> Started: 2026-05-23
> Goal: answer_token_recall ≥ 0.72 (min), ≥ 0.78 (stretch)
> Baseline: average_expected_answer_token_recall ≈ 0.66

---

## Task 0 — Routing Verification

All 40 golden questions routed via `resolve_evidence_mode(..., requested="category")`.

**Deviation from plan:** plan assumed all-text dataset. Actual dataset is multi-modal.

| Mode | Count |
|------|------:|
| text | 24 / 40 |
| table | 9 / 40 |
| visual | 5 / 40 |
| auto (mixed modality) | 2 / 40 |

**Abstention questions:** 4 / 40 (N < 10 — abstention metrics indicative only throughout Tasks 2–9; raw counts reported)

**Impact on ablations:** top_k and chunk-size changes only affect text retrieval (24 Qs). Table/visual recall is unaffected by these parameters. All benchmark tables report two recall columns:
- `answer_recall_text` — over 24 text-routed questions only
- `answer_recall_all` — over all 40 questions

---

## Task 2 — top_k Ablation

### Baseline + top_k Sweep

Config: `retrieval_mode=hybrid`, `evidence_mode=category`, `verify_citations=True`

| Run | top_k | Answer Recall (all) | Answer Recall (text only) | Evidence Recall (all) | Gap | Citation % | False Abstention (n/total) | True Abstention (n/total) | P50 ms | P95 ms |
|-----|------:|--------------------:|--------------------------:|---------------------:|----:|----------:|---------------------------:|---------------------------:|-------:|-------:|
| phase12_topk4_baseline | 4 | 0.6520 | 0.7064 | 0.7557 | 0.1038 | 0.9250 | 2/36 | 2/4 | 4491 | 13266 |
| phase12_topk6 | 6 | 0.6567 | 0.7148 | 0.7756 | 0.1189 | 0.9500 | 3/36 | 3/4 | 3718 | 14815 |
| phase12_topk8 | 8 | 0.6166 | 0.6813 | 0.7926 | 0.1760 | 0.9487 | 1/36 | 3/4 | 5833 | 26513 |
| phase12_topk12 | 12 | 0.6732 | 0.7662 | 0.7993 | 0.1261 | 0.9750 | 2/36 | 4/4 | 4078 | 13808 |

Note: Abstention metrics (TA column) indicative only — N=4.

### Decision

**Provisional top_k = 12**

- top_k=8 regresses vs baseline on both text recall (0.6813 vs 0.7064) and P95 (26.5s spike)
- top_k=12 improves text recall by +0.085 over top_k=8 (>> 0.03 plan threshold) → qualifies
- top_k=12 citation rate 0.975 ≥ 0.95 gate; P95 13808ms ≈ baseline (not materially worse)
- top_k=12 best citation rate of all configs

Observation: evidence_answer_gap = 0.1038 at baseline (> 0.08 threshold) → **Task 5 answer completeness prompt is triggered**.

---

## Task 2.5 — No-Verify Latency Ablation

Config: top_k=12, hybrid, evidence_mode=category

| Run | Verify | Answer Recall | Citation % | P50 ms | P95 ms | P50 Δ | P95 Δ |
|-----|--------|-------------:|-----------:|-------:|-------:|------:|------:|
| phase12_topk12 | ✓ | 0.6732 | 0.975 | 4078 | 13808 | — | — |
| phase12_noverify_topk12 | ✗ | 0.6880 | 0.925 | 1707 | 15667 | −2371 | +1859 |

**Verdict:** Verification saves 2.4s at P50 but P95 worsens (+1.9s). Citation rate drops without verification (0.975→0.925). No fast-path mode recommended for Phase 13 — P95 does not benefit and citation quality degrades. Keep `verify_citations=true` as default.

---

## Task 4 — Chunk-Size Ablation

TBD

---

## Task 6 — Answer Prompt Ablation

TBD

---

## Task 8 — Query Decomposition Ablation

TBD

---

## Task 9 — Reranker Broad-Pool Ablation

TBD

---

## Task 10 — Expanded Dataset Benchmark

TBD

---

## Task 11 — Final Benchmark Report

TBD
