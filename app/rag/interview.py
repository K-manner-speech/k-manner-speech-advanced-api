from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    index: int
    text: str
    token_estimate: int


def chunk_document(text: str, *, chunk_size: int = 1200, overlap: int = 200) -> list[DocumentChunk]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    normalized = re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n"))
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    if not normalized:
        return []

    chunks: list[DocumentChunk] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        if end < len(normalized):
            boundary = max(
                normalized.rfind("\n", start + 1, end),
                normalized.rfind(" ", start + 1, end),
            )
            if boundary > start + chunk_size // 2:
                end = boundary
        value = normalized[start:end]
        chunks.append(
            DocumentChunk(
                index=len(chunks),
                text=value,
                token_estimate=max(1, (len(value) + 3) // 4),
            )
        )
        if end == len(normalized):
            break
        start = end - overlap
    return chunks
