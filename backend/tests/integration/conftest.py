from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from helpers import (
    ALL_TEST_COLLECTIONS,
    TEXT_COLLECTION,
    TABLE_COLLECTION,
    VISUAL_COLLECTION,
    TEST_EMBED_DIM,
    fake_vector,
    pg_url,
    qdrant_url,
)


# ── Skip guard ─────────────────────────────────────────────────────────────────

def pytest_collection_modifyitems(config, items):
    if os.getenv("RUN_INTEGRATION_TESTS") == "true":
        return
    skip = pytest.mark.skip(
        reason="Set RUN_INTEGRATION_TESTS=true to run integration tests"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


# ── Postgres fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pg_engine():
    url = pg_url()
    assert "test" in url, f"Refusing to use non-test database: {url}"

    import docifer_backend.ingestion.models  # noqa: F401
    import docifer_backend.retrieval.models  # noqa: F401
    import docifer_backend.retrieval.tables.models  # noqa: F401
    import docifer_backend.retrieval.visuals.models  # noqa: F401
    import docifer_backend.audit.models  # noqa: F401
    from docifer_backend.storage.database import Base

    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="module")
def pg_session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)


# ── Qdrant fixtures ────────────────────────────────────────────────────────────

from qdrant_client import QdrantClient

from docifer_backend.providers.base import (
    CitationGroundingVerdict,
    GroundingEvidence,
    VisualEvidenceInput,
    VisualInterpretationResult,
    VisualObservation,
)


@pytest.fixture(scope="module")
def qdrant_client():
    client = QdrantClient(url=qdrant_url())
    for name in ALL_TEST_COLLECTIONS:
        if client.collection_exists(name):
            client.delete_collection(name)
    yield client
    for name in ALL_TEST_COLLECTIONS:
        if client.collection_exists(name):
            client.delete_collection(name)


# ── Fake AI provider ───────────────────────────────────────────────────────────

class FakeIntegrationProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [fake_vector(t) for t in texts]

    def generate_grounded_answer(
        self, *, question: str, evidence: list[GroundingEvidence]
    ) -> str:
        if not evidence:
            return "I do not have enough evidence to answer this question."
        return f"Based on the evidence: {evidence[0].text[:80]} [{evidence[0].citation_id}]."

    def verify_citation_grounding(
        self, *, question: str, answer: str, evidence: list[GroundingEvidence]
    ) -> CitationGroundingVerdict:
        cids = [e.citation_id for e in evidence[:1]]
        return CitationGroundingVerdict(
            verdict="supported",
            supported_citation_ids=cids,
            weak_citation_ids=[],
            unsupported_claims=[],
            reasoning="Integration test fake verifier.",
            revised_answer=None,
        )

    def interpret_visual_evidence(
        self, *, question: str, visual_evidence: list[VisualEvidenceInput]
    ) -> VisualInterpretationResult:
        obs = [
            VisualObservation(
                citation_id=ve.citation_id,
                visual_id=ve.visual_id,
                observation_type="page_render",
                question_answered=True,
                extracted_facts=["Integration test observation."],
                visible_entities=[],
                numeric_values=[],
                confidence=0.9,
                limitations=[],
                abstain_reason="",
                supported=True,
                reasoning="Fake visual reasoning.",
            )
            for ve in visual_evidence
        ]
        return VisualInterpretationResult(
            status="interpreted",
            answer=f"Visual answer for: {question[:40]}",
            observations=obs,
            used_citation_ids=[ve.citation_id for ve in visual_evidence],
            abstain_reason="",
            reasoning="Fake visual reasoning.",
        )


@pytest.fixture(scope="module")
def fake_provider():
    return FakeIntegrationProvider()
