from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.adapters.interview_provider import InterviewProviderError, OpenAIEmbeddingProvider
from app.rag.interview import chunk_document


def test_chunk_document_is_bounded_overlapping_and_deterministic() -> None:
    text = "첫 번째 프로젝트에서는 FastAPI API를 개발했습니다.\n\n" + (
        "PostgreSQL 쿼리를 분석하고 인덱스를 적용했습니다. " * 12
    )

    first = chunk_document(text, chunk_size=120, overlap=20)
    second = chunk_document(text, chunk_size=120, overlap=20)

    assert first == second
    assert [chunk.index for chunk in first] == list(range(len(first)))
    assert all(0 < len(chunk.text) <= 120 for chunk in first)
    assert first[0].text[-20:] == first[1].text[:20]


def test_chunk_document_rejects_invalid_bounds_and_empty_text() -> None:
    assert chunk_document("  \n", chunk_size=100, overlap=10) == []

    with pytest.raises(ValueError, match="overlap"):
        chunk_document("내용", chunk_size=100, overlap=100)


def test_embedding_provider_validates_order_count_and_vectors() -> None:
    vectors = OpenAIEmbeddingProvider.parse_embeddings(
        json.dumps(
            {
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            }
        ),
        expected_count=2,
    )

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]

    with pytest.raises(InterviewProviderError, match="INTERVIEW_EMBEDDING_SCHEMA_INVALID"):
        OpenAIEmbeddingProvider.parse_embeddings('{"data":[]}', expected_count=1)


def test_embedding_provider_defaults_to_deployed_vector_dimension() -> None:
    provider = OpenAIEmbeddingProvider("test-key", "text-embedding-3-large")

    assert provider._dimensions == 3072


def test_question_provider_rejects_source_outside_retrieved_chunks() -> None:
    allowed_chunk_id = uuid4()
    foreign_chunk_id = uuid4()
    payload = json.dumps(
        {
            "questions": [
                {
                    "sequence": 1,
                    "text": "API 성능을 개선한 경험을 설명해 주세요.",
                    "type": "technical",
                    "required": True,
                    "source_refs": [{"chunk_id": str(foreign_chunk_id), "section": "experience"}],
                    "evaluation_focus": ["문제 해결"],
                }
            ]
        }
    )

    from app.adapters.interview_provider import OpenAIInterviewProvider

    with pytest.raises(InterviewProviderError, match="INTERVIEW_PROVIDER_SCHEMA_INVALID"):
        OpenAIInterviewProvider.parse_questions(
            payload,
            question_count=1,
            allowed_chunk_ids={allowed_chunk_id},
        )
