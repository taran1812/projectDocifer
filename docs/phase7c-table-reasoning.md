# Phase 7C Table Reasoning

Phase 7C adds a lightweight deterministic reasoning layer after table retrieval and before answer generation. Phase 7B retrieves coherent table evidence; Phase 7C extracts a structured observation from that evidence so the model answers from a computed table fact instead of raw table text alone.

## What Changed

- Added table question intent parsing for metric, year, operation, and entity hints.
- Added numeric parsing for values such as `$27,761`, `(425)`, and `32%`.
- Added structured table reasoning over `structured_json` headers and rows.
- Added fallback table-like text reasoning for segment/year/metric matrix spans.
- Added table reasoning debug output under `/query.debug.table_reasoning`.
- When reasoning is supported, answer generation receives the computed observation plus only the selected supporting table evidence.
- The answer prompt now prefers computed table observations and avoids extra table citations unless they are necessary.

## Supported Phase 7C Pattern

The first supported pattern is benchmark-driven financial table QA:

```text
Which segment had the highest 2025 net income?
```

The reasoner extracts:

```json
{
  "metric": "net income",
  "year": 2025,
  "operation": "max",
  "entity_hint": "segment"
}
```

Then it compares segment candidates and selects:

```text
Commercial & Investment Bank = $27,761 million
```

## API Behavior

The public `/query` request shape is unchanged from Phase 7B. Use either table mode:

```json
{
  "question": "Which segment had the highest 2025 net income?",
  "content_hash": "2a3ee9733eafd01e7667c5540fbd797c4cc688d14f00638a877f5623d1316d9d",
  "evidence_mode": "table",
  "table_top_k": 4,
  "verify_citations": true
}
```

or auto mode:

```json
{
  "question": "Which segment had the highest 2025 net income?",
  "content_hash": "2a3ee9733eafd01e7667c5540fbd797c4cc688d14f00638a877f5623d1316d9d",
  "retrieval_mode": "hybrid",
  "evidence_mode": "auto",
  "table_top_k": 4,
  "verify_citations": true
}
```

New debug fields include:

```json
{
  "table_reasoning_used": true,
  "table_reasoning_status": "supported",
  "table_reasoning": {
    "used_citation_ids": ["T3"],
    "selected_observation": {
      "label": "Commercial & Investment Bank",
      "display_value": "$27,761 million"
    }
  }
}
```

## Validation

Full backend test suite:

```text
56 passed, 1 xfailed
```

Real JPMorgan table-mode HTTP validation:

```text
Commercial & Investment Bank had the highest 2025 net income at $27,761 million. [T3]
```

The response returned:

- 1 table citation
- `table_reasoning_status = supported`
- selected observation `Commercial & Investment Bank`
- selected value `$27,761 million`
- verifier verdict `supported`

Auto mode was also validated and returned the same selected observation with a supported verifier verdict.

## Boundary

Phase 7C is not a spreadsheet engine and does not run SQL over arbitrary document tables. It adds a narrow, inspectable observation layer for retrieved table evidence, starting with financial segment/year/metric comparisons.
