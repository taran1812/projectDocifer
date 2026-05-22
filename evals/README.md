# Docifer Evaluations

Evaluation run outputs are written locally under:

```text
evals/runs/<run-name>/
```

Each run contains:

- `results.jsonl`
- `summary.json`
- `report.md`
- `ragas_input.jsonl`

The `evals/runs/` directory is ignored by git because it contains generated local results and may include model outputs. Commit curated reports under `docs/` when a baseline needs to be preserved.

## Phase 7B table checks

Phase 7B table retrieval is validated through focused backend tests and targeted real queries before adding a broader table-category eval runner. The current gate question is the JPMorgan segment net income case:

```text
Which segment had the highest 2025 net income?
```

Validated configuration:

```json
{
  "evidence_mode": "table",
  "table_top_k": 4,
  "verify_citations": true
}
```

The successful Phase 7B validation returns table citations from the JPMorgan fallback table evidence and a supported citation-grounding verdict.

## Phase 7C table reasoning checks

Phase 7C keeps the same gate question but adds deterministic observation extraction before answer generation.

Expected result:

```text
Commercial & Investment Bank had the highest 2025 net income at $27,761 million.
```

The successful Phase 7C validation returns:

- one table citation,
- `table_reasoning_status = supported`,
- selected observation `Commercial & Investment Bank`,
- selected value `$27,761 million`,
- verifier verdict `supported`.
