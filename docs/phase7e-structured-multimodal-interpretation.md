# Phase 7E - Structured Multimodal Interpretation

Phase 7E adds a narrow, schema-driven visual interpretation layer on top of Phase 7D visual retrieval. It does not turn Docifer into arbitrary image QA. It only interprets retrieved visual evidence candidates and returns cited, structured observations.

## Scope

Implemented capabilities:

- Structured visual interpretation dataclasses:
  - `VisualEvidenceInput`
  - `VisualObservation`
  - `VisualInterpretationResult`
- OpenAI vision-provider support through the Responses API.
- JSON-schema constrained visual interpretation output.
- `/query` support for `evidence_mode="visual"`.
- Auto-mode visual intent detection for chart, figure, graph, plot, image, and related terms.
- Visual citations using `[V1]`, `[V2]`, etc.
- Visual evidence and unused visual evidence in query responses.
- Safe abstention when retrieved visuals are missing, unreadable, unclear, or insufficient.
- Evaluation routing for chart/visual golden questions through visual mode.

Out of scope:

- General-purpose image reasoning.
- Unconstrained chart analytics.
- Multi-step spreadsheet-style computation from images.
- ColQwen integration.
- Frontend rendering of visual artifacts.

## Configuration

Phase 7E adds:

```text
OPENAI_VISION_MODEL=gpt-4o-mini
```

The model is configurable and can be replaced with another vision-capable OpenAI model.

## Query Usage

Visual-only question:

```json
{
  "question": "Which chart shows the main findings?",
  "content_hash": "<content-hash>",
  "evidence_mode": "visual",
  "visual_top_k": 3,
  "verify_citations": true
}
```

Auto mode also detects visual intent:

```json
{
  "question": "What does Figure 2 show?",
  "content_hash": "<content-hash>",
  "evidence_mode": "auto",
  "visual_top_k": 3
}
```

## Response Fields

`/query` now includes:

- `visual_citations`
- `visual_evidence`
- `visual_observations`
- `unused_visual_evidence`

Visual citations use this shape:

```text
[V1] -> visual_id, artifact_path, source PDF, canonical artifact, page range, visual type, retrieval scores
```

Visual observations include:

- `observation_type`
- `question_answered`
- `extracted_facts`
- `visible_entities`
- `numeric_values`
- `confidence`
- `limitations`
- `abstain_reason`
- `supported`
- `reasoning`

## Safe Abstention

The vision provider must abstain when:

- the chart or figure is not visible,
- labels are too small or blurry,
- relevant numbers are unreadable,
- the retrieved visual candidate does not answer the question,
- answering would require guessing.

Example abstention:

```text
I cannot determine this from the retrieved visual evidence because the labels are unreadable. [V1]
```

## Evaluation

The evaluation runner now accepts:

```text
--evidence-mode category|text|table|visual|auto
```

The default `category` mode routes:

- chart/visual/figure/image/graph questions to `visual`,
- table questions to `table`,
- mixed questions to `auto`,
- text questions to `text`.

Example chart/visual run:

```powershell
uv run --project backend python -m docifer_backend.evaluation.runner --run-name phase7e_visual_questions --evidence-mode visual --retrieval-mode hybrid --verify-citations
```

## Validation

Automated validation:

```text
Visual + eval focused tests: 28 passed
Full backend suite: 86 passed, 1 xfailed
Compile check: passed
```

The OpenAI vision provider path is covered by no-network tests that verify:

- base64 image payload creation,
- Responses API `input_image` content shape,
- JSON-schema output request shape,
- structured result parsing,
- safe abstention when no artifact is available.

Live OpenAI vision calls were not run during this implementation pass.
