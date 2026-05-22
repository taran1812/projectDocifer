from docifer_backend.config.settings import get_settings
from docifer_backend.config.paths import resolve_project_path
import json
import base64
import random
import time
from pathlib import Path

from docifer_backend.providers.base import (
    CitationGroundingVerdict,
    GroundingEvidence,
    ProviderRateLimitError,
    VisualEvidenceInput,
    VisualInterpretationResult,
    VisualObservation,
)


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


class OpenAIProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        embedding_model: str | None = None,
        answer_model: str | None = None,
        vision_model: str | None = None,
    ) -> None:
        settings = get_settings()
        resolved_api_key = api_key or settings.openai_api_key
        if not resolved_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the OpenAI provider.")

        from openai import OpenAI

        self.client = OpenAI(api_key=resolved_api_key)
        self.embedding_model = embedding_model or settings.openai_embedding_model
        self.answer_model = answer_model or settings.openai_answer_model
        self.vision_model = vision_model or settings.openai_vision_model
        self.embedding_batch_size = settings.openai_embedding_batch_size

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.embedding_batch_size):
            batch = texts[start:start + self.embedding_batch_size]
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=batch,
            )
            embeddings.extend(item.embedding for item in response.data)
        return embeddings

    def generate_grounded_answer(
        self,
        *,
        question: str,
        evidence: list[GroundingEvidence],
    ) -> str:
        evidence_text = _format_evidence_sections(evidence)
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
                "- If the question asks for a specific entity, metric, number, date, "
                "name, or comparison and the evidence does not contain that exact "
                "target, say you do not have enough evidence to answer. Do not "
                "substitute loosely related context.\n"
                "- If the question is about personal, private, or sensitive information "
                "that would not appear in a corporate or government document, say you "
                "do not have enough evidence to answer.\n"
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

        output_text = getattr(response, "output_text", None)
        if output_text:
            return output_text.strip()
        return str(response).strip()

    def verify_citation_grounding(
        self,
        *,
        question: str,
        answer: str,
        evidence: list[GroundingEvidence],
    ) -> CitationGroundingVerdict:
        evidence_text = _format_evidence_sections(evidence)
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

        output_text = (getattr(response, "output_text", None) or "").strip()
        try:
            payload = json.loads(_strip_json_fence(output_text))
        except json.JSONDecodeError:
            return CitationGroundingVerdict(
                verdict="partially_supported",
                supported_citation_ids=[],
                weak_citation_ids=[],
                unsupported_claims=[],
                reasoning=f"Verifier returned non-JSON output: {output_text[:500]}",
                revised_answer=None,
            )

        return CitationGroundingVerdict(
            verdict=str(payload.get("verdict") or "partially_supported"),
            supported_citation_ids=list(payload.get("supported_citation_ids") or []),
            weak_citation_ids=list(payload.get("weak_citation_ids") or []),
            unsupported_claims=list(payload.get("unsupported_claims") or []),
            reasoning=str(payload.get("reasoning") or ""),
            revised_answer=payload.get("revised_answer"),
        )

    def interpret_visual_evidence(
        self,
        *,
        question: str,
        visual_evidence: list[VisualEvidenceInput],
    ) -> VisualInterpretationResult:
        if not visual_evidence:
            return VisualInterpretationResult(
                status="abstained",
                answer="I do not have visual evidence to answer this question.",
                observations=[],
                used_citation_ids=[],
                abstain_reason="No visual evidence was provided.",
                reasoning="Visual interpretation requires at least one retrieved visual candidate.",
            )

        content: list[dict] = [
            {
                "type": "input_text",
                "text": _visual_interpretation_prompt(question, visual_evidence),
            }
        ]
        for item in visual_evidence:
            data_url = _image_data_url(item.artifact_path)
            if data_url:
                content.append({"type": "input_image", "image_url": data_url})

        if len(content) == 1:
            return _visual_abstention_result(
                "No readable visual artifacts were available on disk.",
                visual_evidence,
            )

        response = _with_openai_retry(lambda: self.client.responses.create(
            model=self.vision_model,
            instructions=(
                "You are Docifer's narrow visual evidence interpreter. Read only "
                "the provided visual candidates and metadata. Return structured "
                "JSON that matches the supplied schema. Do not infer values that "
                "are not legible. If the relevant chart, labels, or numbers are "
                "unclear, abstain safely."
            ),
            input=[{"role": "user", "content": content}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "docifer_visual_interpretation",
                    "strict": True,
                    "schema": _VISUAL_INTERPRETATION_SCHEMA,
                }
            },
            max_output_tokens=1000,
        ))

        output_text = (getattr(response, "output_text", None) or "").strip()
        try:
            payload = json.loads(_strip_json_fence(output_text))
        except json.JSONDecodeError:
            return _visual_abstention_result(
                f"Vision provider returned non-JSON output: {output_text[:500]}",
                visual_evidence,
            )
        return _parse_visual_interpretation_payload(payload, visual_evidence)


def _strip_json_fence(text: str) -> str:
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def _format_evidence_sections(evidence: list[GroundingEvidence]) -> str:
    text_items = [item for item in evidence if item.citation_id.upper().startswith("C")]
    table_items = [item for item in evidence if item.citation_id.upper().startswith("T")]
    visual_items = [item for item in evidence if item.citation_id.upper().startswith("V")]
    other_items = [
        item
        for item in evidence
        if not item.citation_id.upper().startswith(("C", "T", "V"))
    ]
    sections: list[str] = []
    if text_items:
        sections.append("Text evidence:\n" + "\n\n".join(_format_evidence_item(item) for item in text_items))
    if table_items:
        sections.append("Table evidence:\n" + "\n\n".join(_format_evidence_item(item) for item in table_items))
    if visual_items:
        sections.append("Visual evidence:\n" + "\n\n".join(_format_evidence_item(item) for item in visual_items))
    if other_items:
        sections.append("Other evidence:\n" + "\n\n".join(_format_evidence_item(item) for item in other_items))
    return "\n\n".join(sections)


def _format_evidence_item(item: GroundingEvidence) -> str:
    return f"[{item.citation_id}] Source: {item.source}\n{item.text}"


def _visual_interpretation_prompt(question: str, visual_evidence: list[VisualEvidenceInput]) -> str:
    metadata = "\n\n".join(
        f"[{item.citation_id}] Visual ID: {item.visual_id}\n"
        f"Source: {item.source}\n"
        f"Metadata:\n{item.metadata_text}"
        for item in visual_evidence
    )
    return (
        f"Question:\n{question}\n\n"
        "Retrieved visual candidates:\n"
        f"{metadata}\n\n"
        "Task:\n"
        "- Interpret only the provided visual candidates.\n"
        "- Prefer direct chart labels, visible legends, and readable values.\n"
        "- Use citation IDs like [V1] in the answer.\n"
        "- If the answer depends on unreadable labels, tiny numbers, cropped content, "
        "or a missing visual, set status to abstained and explain why.\n"
        "- Keep extracted_facts short and concrete.\n"
    )


def _image_data_url(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = resolve_project_path(path_value)
    if not path.exists() or not path.is_file():
        return None
    suffix = Path(path).suffix.lower()
    mime_type = "image/png" if suffix == ".png" else "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _visual_abstention_result(
    reason: str,
    visual_evidence: list[VisualEvidenceInput],
) -> VisualInterpretationResult:
    first = visual_evidence[0] if visual_evidence else None
    citation_id = first.citation_id if first else ""
    visual_id = first.visual_id if first else ""
    answer = (
        f"I cannot determine this from the retrieved visual evidence because {reason}"
        + (f" [{citation_id}]" if citation_id else "")
    )
    observations = [
        VisualObservation(
            citation_id=citation_id,
            visual_id=visual_id,
            observation_type="abstention",
            question_answered=False,
            extracted_facts=[],
            visible_entities=[],
            numeric_values=[],
            confidence=0.0,
            limitations=[reason],
            abstain_reason=reason,
            supported=False,
            reasoning=reason,
        )
    ] if first else []
    return VisualInterpretationResult(
        status="abstained",
        answer=answer,
        observations=observations,
        used_citation_ids=[citation_id] if citation_id else [],
        abstain_reason=reason,
        reasoning=reason,
    )


def _parse_visual_interpretation_payload(
    payload: dict,
    visual_evidence: list[VisualEvidenceInput],
) -> VisualInterpretationResult:
    known_citations = {item.citation_id for item in visual_evidence}
    observations = [
        _parse_visual_observation(item)
        for item in payload.get("observations") or []
        if isinstance(item, dict)
    ]
    used = [
        str(item)
        for item in payload.get("used_citation_ids") or []
        if str(item) in known_citations
    ]
    if not used:
        used = [
            observation.citation_id
            for observation in observations
            if observation.supported and observation.citation_id in known_citations
        ]
    status = str(payload.get("status") or "abstained")
    if status not in {"supported", "abstained", "unsupported"}:
        status = "abstained"
    answer = str(payload.get("answer") or "").strip()
    abstain_reason = str(payload.get("abstain_reason") or "").strip()
    if status != "supported" and not abstain_reason:
        abstain_reason = "The visual evidence was not clear enough to answer safely."
    if not answer:
        if status == "supported" and used:
            answer = f"The retrieved visual evidence supports the requested observation. [{used[0]}]"
        else:
            answer = (
                f"I cannot determine this from the retrieved visual evidence because {abstain_reason}"
                + (f" [{used[0]}]" if used else "")
            )
    elif status == "supported" and used and not any(f"[{cid}]" in answer for cid in used):
        answer = f"{answer} [{used[0]}]"
    return VisualInterpretationResult(
        status=status,
        answer=answer,
        observations=observations,
        used_citation_ids=list(dict.fromkeys(used)),
        abstain_reason=abstain_reason,
        reasoning=str(payload.get("reasoning") or ""),
    )


def _parse_visual_observation(payload: dict) -> VisualObservation:
    return VisualObservation(
        citation_id=str(payload.get("citation_id") or ""),
        visual_id=str(payload.get("visual_id") or ""),
        observation_type=str(payload.get("observation_type") or "visual_observation"),
        question_answered=bool(payload.get("question_answered")),
        extracted_facts=[str(item) for item in payload.get("extracted_facts") or []],
        visible_entities=[str(item) for item in payload.get("visible_entities") or []],
        numeric_values=[str(item) for item in payload.get("numeric_values") or []],
        confidence=float(payload.get("confidence") or 0.0),
        limitations=[str(item) for item in payload.get("limitations") or []],
        abstain_reason=str(payload.get("abstain_reason") or ""),
        supported=bool(payload.get("supported")),
        reasoning=str(payload.get("reasoning") or ""),
    )


_VISUAL_INTERPRETATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "status",
        "answer",
        "used_citation_ids",
        "observations",
        "abstain_reason",
        "reasoning",
    ],
    "properties": {
        "status": {"type": "string", "enum": ["supported", "abstained", "unsupported"]},
        "answer": {"type": "string"},
        "used_citation_ids": {"type": "array", "items": {"type": "string"}},
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "citation_id",
                    "visual_id",
                    "observation_type",
                    "question_answered",
                    "extracted_facts",
                    "visible_entities",
                    "numeric_values",
                    "confidence",
                    "limitations",
                    "abstain_reason",
                    "supported",
                    "reasoning",
                ],
                "properties": {
                    "citation_id": {"type": "string"},
                    "visual_id": {"type": "string"},
                    "observation_type": {"type": "string"},
                    "question_answered": {"type": "boolean"},
                    "extracted_facts": {"type": "array", "items": {"type": "string"}},
                    "visible_entities": {"type": "array", "items": {"type": "string"}},
                    "numeric_values": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                    "limitations": {"type": "array", "items": {"type": "string"}},
                    "abstain_reason": {"type": "string"},
                    "supported": {"type": "boolean"},
                    "reasoning": {"type": "string"},
                },
            },
        },
        "abstain_reason": {"type": "string"},
        "reasoning": {"type": "string"},
    },
}
