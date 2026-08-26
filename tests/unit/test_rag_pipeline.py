from __future__ import annotations

from uuid import uuid4

from app.ai.rag import EvidenceChunk, chunk_document, select_evidence


def test_chunk_document_preserves_source_metadata_and_overlap() -> None:
    chunks = chunk_document(
        "하나 둘 셋 넷 다섯 여섯 일곱 여덟 아홉 열",
        maximum_tokens=5,
        overlap_tokens=2,
        section="resume",
    )

    assert [chunk.text for chunk in chunks] == [
        "하나 둘 셋 넷 다섯",
        "넷 다섯 여섯 일곱 여덟",
        "일곱 여덟 아홉 열",
    ]
    assert [chunk.index for chunk in chunks] == [0, 1, 2]
    assert all(chunk.section == "resume" for chunk in chunks)


def test_select_evidence_applies_threshold_top_five_and_owner_version_filter() -> None:
    owner_id = uuid4()
    document_id = uuid4()
    chunks = [
        EvidenceChunk(
            id=uuid4(),
            user_id=owner_id,
            document_id=document_id,
            document_version=2,
            text=f"근거 {index}",
            section="resume",
            similarity=0.95 - index * 0.02,
        )
        for index in range(7)
    ]
    chunks.extend(
        [
            EvidenceChunk(
                id=uuid4(),
                user_id=uuid4(),
                document_id=document_id,
                document_version=2,
                text="다른 사용자",
                section="resume",
                similarity=1.0,
            ),
            EvidenceChunk(
                id=uuid4(),
                user_id=owner_id,
                document_id=document_id,
                document_version=1,
                text="이전 버전",
                section="resume",
                similarity=1.0,
            ),
        ]
    )

    selected = select_evidence(
        chunks,
        user_id=owner_id,
        document_versions={document_id: 2},
        threshold=0.8,
        top_k=5,
    )

    assert len(selected) == 5
    assert [item.text for item in selected] == [f"근거 {index}" for index in range(5)]


def test_chunk_document_rejects_invalid_overlap() -> None:
    try:
        chunk_document("텍스트", 5, 5, "resume")
    except ValueError as error:
        assert "overlap" in str(error)
    else:
        raise AssertionError("overlap equal to maximum must fail")
