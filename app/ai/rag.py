from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    index: int
    text: str
    section: str


@dataclass(frozen=True, slots=True)
class EvidenceChunk:
    id: UUID
    user_id: UUID
    document_id: UUID
    document_version: int
    text: str
    section: str
    similarity: float


def chunk_document(
    text: str,
    maximum_tokens: int,
    overlap_tokens: int,
    section: str,
) -> list[DocumentChunk]:
    if maximum_tokens <= 0:
        raise ValueError("maximum_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= maximum_tokens:
        raise ValueError("overlap_tokens must be smaller than maximum_tokens")
    words = text.split()
    if not words:
        return []
    step = maximum_tokens - overlap_tokens
    chunks: list[DocumentChunk] = []
    for start in range(0, len(words), step):
        chunk_words = words[start : start + maximum_tokens]
        if not chunk_words:
            break
        chunks.append(
            DocumentChunk(index=len(chunks), text=" ".join(chunk_words), section=section)
        )
        if start + maximum_tokens >= len(words):
            break
    return chunks


# 질문 근거로 쓸 수 있는 섹션. 요약·기술 나열은 "무엇을 했는가"가 없어 질문을 만들 수 없다.
EVIDENCE_SECTIONS: tuple[str, ...] = ("experience", "risks")


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sqrt(sum(a * a for a in left))
    right_norm = sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def assign_sections(
    chunk_embeddings: list[list[float]],
    section_embeddings: list[tuple[str, list[float]]],
    *,
    fallback: str,
) -> list[str]:
    """각 청크에 의미 섹션 라벨을 붙인다.

    문서 분석이 이미 뽑아 둔 섹션 문장과 청크를 견주어, 가장 가까운 섹션의
    이름을 라벨로 삼는다. 이력서마다 다른 제목·순서에 기대지 않고, 새 임베딩
    호출도 필요 없다. 섹션 문장이 하나도 없으면 라벨을 지어내지 않고
    fallback 을 쓴다.
    """
    if not section_embeddings:
        return [fallback] * len(chunk_embeddings)
    labels: list[str] = []
    for chunk_embedding in chunk_embeddings:
        best_name = fallback
        best_score = float("-inf")
        for name, section_embedding in section_embeddings:
            score = _cosine(chunk_embedding, section_embedding)
            if score > best_score:
                best_name, best_score = name, score
        labels.append(best_name)
    return labels


def select_evidence(
    chunks: list[EvidenceChunk],
    *,
    user_id: UUID,
    document_versions: dict[UUID, int],
    threshold: float,
    top_k: int,
) -> list[EvidenceChunk]:
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be in (0, 1]")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    eligible = [
        chunk
        for chunk in chunks
        if chunk.user_id == user_id
        and document_versions.get(chunk.document_id) == chunk.document_version
        and chunk.similarity >= threshold
    ]
    return sorted(eligible, key=lambda item: item.similarity, reverse=True)[:top_k]
