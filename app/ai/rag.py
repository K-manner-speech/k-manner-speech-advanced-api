from __future__ import annotations

from dataclasses import dataclass
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
