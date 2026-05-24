import json

import pytest
from unittest.mock import patch

from docifer_backend.providers.base import ProviderRateLimitError, VisualEvidenceInput
from docifer_backend.providers.openai_provider import OpenAIProvider, _with_openai_retry


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



def test_with_openai_retry_succeeds_on_first_attempt():
    call_count = 0

    def fn():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = _with_openai_retry(fn)
    assert result == "ok"
    assert call_count == 1


def test_with_openai_retry_retries_on_rate_limit_then_succeeds():
    call_count = 0

    class FakeRateLimitError(Exception):
        pass

    def fn():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise FakeRateLimitError("rate limit")
        return "ok"

    with patch("docifer_backend.providers.openai_provider._is_rate_limit_error", return_value=True):
        with patch("time.sleep"):
            result = _with_openai_retry(fn, max_retries=2)

    assert result == "ok"
    assert call_count == 3


def test_with_openai_retry_raises_provider_rate_limit_error_after_max_retries():
    class FakeRateLimitError(Exception):
        pass

    def fn():
        raise FakeRateLimitError("rate limit")

    with patch("docifer_backend.providers.openai_provider._is_rate_limit_error", return_value=True):
        with patch("time.sleep"):
            with pytest.raises(ProviderRateLimitError):
                _with_openai_retry(fn, max_retries=2)


def test_with_openai_retry_does_not_retry_non_rate_limit_errors():
    call_count = 0

    def fn():
        nonlocal call_count
        call_count += 1
        raise ValueError("something else")

    with pytest.raises(ValueError):
        _with_openai_retry(fn)
    assert call_count == 1


def test_with_openai_retry_backoff_timing():
    sleep_calls = []

    class FakeRateLimitError(Exception):
        pass

    def fn():
        raise FakeRateLimitError("rate limit")

    with patch("docifer_backend.providers.openai_provider._is_rate_limit_error", return_value=True):
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            with pytest.raises(ProviderRateLimitError):
                _with_openai_retry(fn, max_retries=2)

    assert len(sleep_calls) == 2
    assert 1.5 <= sleep_calls[0] <= 2.5   # 2^1 ± 0.5
    assert 3.5 <= sleep_calls[1] <= 4.5   # 2^2 ± 0.5


def test_generate_grounded_answer_prompt_contains_completeness_rules():
    from docifer_backend.providers.openai_provider import OpenAIProvider, ANSWER_PROMPT_VERSION
    import unittest.mock as mock

    captured = {}

    def fake_create(**kwargs):
        captured['instructions'] = kwargs.get('instructions', '')
        return mock.MagicMock(output_text="Answer [C1].")

    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.client = mock.MagicMock()
    provider.client.responses.create.side_effect = lambda **kwargs: fake_create(**kwargs)
    provider.answer_model = "test-model"

    from docifer_backend.providers.base import GroundingEvidence
    provider.generate_grounded_answer(
        question="What are the strategies?",
        evidence=[GroundingEvidence(citation_id="C1", text="The 1i, 2i, 3i strategies.", source="doc.pdf")],
    )

    assert "completeness" in captured['instructions'].lower() or "all parts" in captured['instructions'].lower()
    assert ANSWER_PROMPT_VERSION == "phase12_completeness_v1"
