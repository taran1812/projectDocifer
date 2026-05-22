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

The successful Phase 7B validation returns a table citation from the JPMorgan fallback table span on page 340 and a supported citation-grounding verdict.
