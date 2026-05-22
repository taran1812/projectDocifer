import json

from docifer_backend.providers.base import VisualEvidenceInput
from docifer_backend.providers.openai_provider import OpenAIProvider


class FakeResponses:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.last_payload = None

    def create(self, **payload):
        self.last_payload = payload
        return type("FakeResponse", (), {"output_text": self.output_text})()


class FakeClient:
    def __init__(self, output_text: str) -> None:
        self.responses = FakeResponses(output_text)


def test_openai_provider_interpret_visual_evidence_parses_structured_output(tmp_path):
    image_path = tmp_path / "page_0001.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    output = json.dumps({
        "status": "supported",
        "answer": "The figure shows an upward trend. [V1]",
        "used_citation_ids": ["V1"],
        "observations": [
            {
                "citation_id": "V1",
                "visual_id": "abc:page:0001",
                "observation_type": "chart_summary",
                "question_answered": True,
                "extracted_facts": ["The figure shows an upward trend."],
                "visible_entities": ["trend line"],
                "numeric_values": [],
                "confidence": 0.8,
                "limitations": [],
                "abstain_reason": "",
                "supported": True,
                "reasoning": "The trend line is visible.",
            }
        ],
        "abstain_reason": "",
        "reasoning": "The figure is readable.",
    })
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.client = FakeClient(output)
    provider.vision_model = "test-vision-model"

    result = provider.interpret_visual_evidence(
        question="What does the figure show?",
        visual_evidence=[
            VisualEvidenceInput(
                citation_id="V1",
                visual_id="abc:page:0001",
                artifact_path=str(image_path),
                metadata_text="Document: sample.pdf\nPage: 1",
                source="visual:abc:page:0001, sample.pdf, page 1",
            )
        ],
    )

    assert result.status == "supported"
    assert result.used_citation_ids == ["V1"]
    assert result.observations[0].supported is True
    payload = provider.client.responses.last_payload
    assert payload["model"] == "test-vision-model"
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["input"][0]["content"][1]["type"] == "input_image"


def test_openai_provider_interpret_visual_evidence_abstains_without_artifact():
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.client = FakeClient("{}")
    provider.vision_model = "test-vision-model"

    result = provider.interpret_visual_evidence(
        question="What does the figure show?",
        visual_evidence=[
            VisualEvidenceInput(
                citation_id="V1",
                visual_id="missing:page:0001",
                artifact_path="does/not/exist.jpg",
                metadata_text="Document: missing.pdf",
                source="visual:missing:page:0001, missing.pdf, page 1",
            )
        ],
    )

    assert result.status == "abstained"
    assert "No readable visual artifacts" in result.abstain_reason
    assert result.used_citation_ids == ["V1"]
