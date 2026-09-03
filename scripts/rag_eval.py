"""운영 RAG 검색 방식을 재현해 합성 이력서 골드셋을 평가한다.

운영 DB는 변경하지 않는다. 운영과 같은 청킹/임베딩 설정을 사용하고,
pgvector의 cosine distance 정렬을 메모리 내 cosine similarity로 재현한다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.prompts.composer import PromptComposer  # noqa: E402
from app.ai.providers.openai import OpenAIEmbeddingClient, OpenAIResponsesClient  # noqa: E402
from app.ai.rag import chunk_document  # noqa: E402
from app.core.config import AppSettings  # noqa: E402
from app.schemas.base import ContractModel  # noqa: E402

ExpectedBehavior = Literal[
    "retrieve_evidence", "partial_evidence", "insufficient_evidence"
]


@dataclass(frozen=True, slots=True)
class CorpusChunk:
    document_id: str
    chunk_index: int
    text: str


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    document_id: str
    chunk_index: int
    text: str
    similarity: float
    is_relevant: bool = False


@dataclass(frozen=True, slots=True)
class GoldCase:
    case_id: str
    document_id: str
    desired_role: str
    query: str
    gold_quotes: tuple[str, ...]
    expected_behavior: ExpectedBehavior


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    expected_behavior: ExpectedBehavior
    found_rank: int | None
    retrieved: list[RetrievedChunk]
    relevance_level: str | None = None
    relevance_details: tuple[dict[str, Any], ...] = ()


class EvalRelevanceDecision(ContractModel):
    document_id: str
    chunk_index: int
    support_level: Literal["supported", "partially_supported", "unsupported"]
    supported_claims: list[str]
    unsupported_claims: list[str]
    reason: str


class EvalRelevanceResult(ContractModel):
    decisions: list[EvalRelevanceDecision]


def build_corpus(
    documents: dict[str, str], *, maximum_tokens: int = 500, overlap_tokens: int = 75
) -> list[CorpusChunk]:
    if not documents:
        raise ValueError("corpus must contain at least one document")
    corpus: list[CorpusChunk] = []
    for document_id in sorted(documents):
        chunks = chunk_document(
            documents[document_id],
            maximum_tokens=maximum_tokens,
            overlap_tokens=overlap_tokens,
            section="resume",
        )
        if not chunks:
            raise ValueError(f"empty document: {document_id}")
        corpus.extend(
            CorpusChunk(document_id, chunk.index, chunk.text) for chunk in chunks
        )
    return corpus


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        raise ValueError("embedding dimension mismatch")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("cosine similarity does not accept a zero vector")
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )


def retrieve_top_k(
    query_embedding: list[float],
    chunks: list[CorpusChunk],
    chunk_embeddings: list[list[float]],
    *,
    threshold: float,
    top_k: int,
) -> list[RetrievedChunk]:
    if len(chunks) != len(chunk_embeddings):
        raise ValueError("chunk and embedding counts differ")
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be in (0, 1]")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    candidates = [
        RetrievedChunk(
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            similarity=cosine_similarity(query_embedding, embedding),
        )
        for chunk, embedding in zip(chunks, chunk_embeddings, strict=True)
    ]
    eligible = [item for item in candidates if item.similarity >= threshold]
    eligible.sort(key=lambda item: (-item.similarity, item.document_id, item.chunk_index))
    return eligible[:top_k]


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def contains_gold_quote(text: str, quotes: list[str] | tuple[str, ...]) -> bool:
    normalized_text = _normalize_whitespace(text)
    return any(
        bool(normalized_quote := _normalize_whitespace(quote))
        and normalized_quote in normalized_text
        for quote in quotes
    )


def aggregate_metrics(results: list[CaseResult]) -> dict[str, int | float]:
    positives = [item for item in results if item.expected_behavior == "retrieve_evidence"]
    negatives = [
        item for item in results if item.expected_behavior == "insufficient_evidence"
    ]
    partials = [item for item in results if item.expected_behavior == "partial_evidence"]
    if not positives or not negatives:
        raise ValueError("evaluation requires both positive and negative cases")

    def recall_at(limit: int) -> float:
        return sum(
            item.found_rank is not None and item.found_rank <= limit for item in positives
        ) / len(positives)

    rejected = sum(not item.retrieved for item in negatives) / len(negatives)
    metrics: dict[str, int | float] = {
        "positive_cases": len(positives),
        "negative_cases": len(negatives),
        "hit_at_1": recall_at(1),
        "recall_at_3": recall_at(3),
        "recall_at_5": recall_at(5),
        "mrr": sum(1 / item.found_rank if item.found_rank else 0 for item in positives)
        / len(positives),
        "negative_rejection_accuracy": rejected,
        "negative_false_positive_rate": 1 - rejected,
    }
    if partials:
        metrics.update(
            {
                "partial_cases": len(partials),
                "partial_evidence_recall_at_5": sum(
                    item.found_rank is not None and item.found_rank <= 5
                    for item in partials
                )
                / len(partials),
            }
        )
    judged = [item for item in results if item.relevance_level is not None]
    if judged:
        expected_levels = {
            "retrieve_evidence": "supported",
            "partial_evidence": "partially_supported",
            "insufficient_evidence": "unsupported",
        }
        metrics["relevance_classification_accuracy"] = sum(
            item.relevance_level == expected_levels[item.expected_behavior]
            for item in judged
        ) / len(judged)
    return metrics


def select_balanced_threshold(
    rows: list[dict[str, int | float]],
) -> dict[str, int | float]:
    if not rows:
        raise ValueError("threshold rows must not be empty")
    scored: list[dict[str, int | float]] = []
    for row in rows:
        recall = float(row["recall_at_5"])
        rejection = float(row["negative_rejection_accuracy"])
        harmonic = 0.0 if recall + rejection == 0 else 2 * recall * rejection / (recall + rejection)
        scored.append({**row, "balanced_score": harmonic})
    return max(
        scored,
        key=lambda row: (
            float(row["balanced_score"]),
            float(row["recall_at_5"]),
            float(row["threshold"]),
        ),
    )


def load_dataset(dataset_dir: Path) -> tuple[dict[str, str], list[GoldCase]]:
    manifest_path = dataset_dir / "manifest.json"
    cases_path = dataset_dir / "rag_gold_dataset.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents: dict[str, str] = {}
    for item in manifest:
        document_id = str(item["document_id"])
        if document_id in documents:
            raise ValueError(f"duplicate document_id: {document_id}")
        documents[document_id] = (dataset_dir / item["text"]).read_text(encoding="utf-8")

    cases: list[GoldCase] = []
    seen: set[str] = set()
    for line_number, line in enumerate(cases_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        raw = json.loads(line)
        case_id = str(raw["case_id"])
        if case_id in seen:
            raise ValueError(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        behavior = raw["expected_behavior"]
        if behavior not in {
            "retrieve_evidence",
            "partial_evidence",
            "insufficient_evidence",
        }:
            raise ValueError(f"invalid expected_behavior at line {line_number}")
        document_id = str(raw["document_id"])
        if document_id not in documents:
            raise ValueError(f"unknown document_id at line {line_number}: {document_id}")
        quotes = tuple(str(item["quote"]) for item in raw.get("relevant_evidence", []))
        if behavior in {"retrieve_evidence", "partial_evidence"} and not quotes:
            raise ValueError(f"evidence case lacks quotes at line {line_number}")
        if behavior == "insufficient_evidence" and quotes:
            raise ValueError(f"negative case must not contain evidence at line {line_number}")
        cases.append(
            GoldCase(
                case_id=case_id,
                document_id=document_id,
                desired_role=str(raw["desired_role"]),
                query=str(raw["query"]),
                gold_quotes=quotes,
                expected_behavior=behavior,
            )
        )
    if not cases:
        raise ValueError("dataset must contain at least one case")
    return documents, cases


def stratified_cases(cases: list[GoldCase], limit: int) -> list[GoldCase]:
    if limit <= 0:
        raise ValueError("case limit must be positive")
    selected: list[GoldCase] = []
    for behavior in (
        "retrieve_evidence",
        "partial_evidence",
        "insufficient_evidence",
    ):
        group = [item for item in cases if item.expected_behavior == behavior]
        if len(group) <= limit:
            selected.extend(group)
            continue
        if limit == 1:
            selected.append(group[len(group) // 2])
            continue
        indexes = [
            round(index * (len(group) - 1) / (limit - 1)) for index in range(limit)
        ]
        selected.extend(group[index] for index in indexes)
    return selected


def build_query_text(case: GoldCase) -> str:
    """운영 검색 입력의 JSON 형태를 유지하면서 평가 질문을 evaluation_query에 넣는다."""
    return json.dumps(
        {
            "conditions": {"evaluation_query": case.query},
            "role": case.desired_role,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _embed_batches(
    client: OpenAIEmbeddingClient, texts: list[str], batch_size: int = 50
) -> tuple[list[list[float]], int, float]:
    vectors: list[list[float]] = []
    calls = 0
    started = time.monotonic()
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors.extend(client.embed(batch))
        calls += 1
    if len(vectors) != len(texts):
        raise ValueError("embedding provider returned an unexpected vector count")
    return vectors, calls, time.monotonic() - started


def evaluate(
    *,
    cases: list[GoldCase],
    chunks: list[CorpusChunk],
    chunk_embeddings: list[list[float]],
    query_embeddings: list[list[float]],
    threshold: float,
    top_k: int,
) -> list[CaseResult]:
    if len(cases) != len(query_embeddings):
        raise ValueError("case and query embedding counts differ")
    results: list[CaseResult] = []
    for case, query_embedding in zip(cases, query_embeddings, strict=True):
        scoped_pairs = [
            (chunk, embedding)
            for chunk, embedding in zip(chunks, chunk_embeddings, strict=True)
            if chunk.document_id == case.document_id
        ]
        scoped_chunks = [item[0] for item in scoped_pairs]
        scoped_embeddings = [item[1] for item in scoped_pairs]
        raw_retrieved = retrieve_top_k(
            query_embedding,
            scoped_chunks,
            scoped_embeddings,
            threshold=threshold,
            top_k=top_k,
        )
        retrieved = [
            RetrievedChunk(
                document_id=item.document_id,
                chunk_index=item.chunk_index,
                text=item.text,
                similarity=item.similarity,
                is_relevant=(
                    case.expected_behavior in {"retrieve_evidence", "partial_evidence"}
                    and item.document_id == case.document_id
                    and contains_gold_quote(item.text, case.gold_quotes)
                ),
            )
            for item in raw_retrieved
        ]
        found_rank = next(
            (rank for rank, item in enumerate(retrieved, 1) if item.is_relevant), None
        )
        results.append(
            CaseResult(case.case_id, case.expected_behavior, found_rank, retrieved)
        )
    return results


def apply_relevance_check(
    *,
    cases: list[GoldCase],
    results: list[CaseResult],
    provider: OpenAIResponsesClient,
) -> list[CaseResult]:
    cases_by_id = {case.case_id: case for case in cases}
    instructions = PromptComposer.default().task_instruction(
        "interview_evidence_relevance"
    )
    checked: list[CaseResult] = []
    for result in results:
        if not result.retrieved:
            checked.append(result)
            continue
        case = cases_by_id[result.case_id]
        relevance = provider.generate_structured(
            instructions=instructions,
            input_text=json.dumps(
                {
                    "conditions": {"evaluation_query": case.query},
                    "desired_role": case.desired_role,
                    "top_similarity": result.retrieved[0].similarity,
                    "top1_top2_gap": (
                        result.retrieved[0].similarity - result.retrieved[1].similarity
                        if len(result.retrieved) > 1
                        else None
                    ),
                    "evidence": [
                        {
                            "document_id": item.document_id,
                            "chunk_index": item.chunk_index,
                            "text": item.text,
                            "similarity": item.similarity,
                        }
                        for item in result.retrieved
                    ],
                },
                ensure_ascii=False,
            ),
            schema_name="rag_eval_evidence_relevance",
            result_type=EvalRelevanceResult,
        )
        decisions = {
            (item.document_id, item.chunk_index): item.support_level
            for item in relevance.decisions
        }
        expected = {(item.document_id, item.chunk_index) for item in result.retrieved}
        if set(decisions) != expected or len(decisions) != len(relevance.decisions):
            raise ValueError(f"invalid relevance decisions for {result.case_id}")
        retrieved = [
            item
            for item in result.retrieved
            if decisions[(item.document_id, item.chunk_index)] != "unsupported"
        ]
        found_rank = next(
            (rank for rank, item in enumerate(retrieved, 1) if item.is_relevant), None
        )
        levels = set(decisions.values())
        overall_level = (
            "supported"
            if "supported" in levels
            else "partially_supported"
            if "partially_supported" in levels
            else "unsupported"
        )
        checked.append(
            CaseResult(
                result.case_id,
                result.expected_behavior,
                found_rank,
                retrieved,
                relevance_level=overall_level,
                relevance_details=tuple(
                    {
                        "document_id": item.document_id,
                        "chunk_index": item.chunk_index,
                        "support_level": item.support_level,
                        "supported_claims": item.supported_claims,
                        "unsupported_claims": item.unsupported_claims,
                        "reason": item.reason,
                    }
                    for item in relevance.decisions
                ),
            )
        )
    return checked


def _case_payload(result: CaseResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "expected_behavior": result.expected_behavior,
        "found_rank": result.found_rank,
        "relevance_level": result.relevance_level,
        "relevance_details": list(result.relevance_details),
        "retrieved": [
            {
                "rank": rank,
                "document_id": item.document_id,
                "chunk_index": item.chunk_index,
                "similarity": round(item.similarity, 8),
                "is_relevant": item.is_relevant,
                "text_preview": item.text[:240],
            }
            for rank, item in enumerate(result.retrieved, 1)
        ],
    }


def write_reports(
    output_dir: Path,
    report: dict[str, Any],
    results: list[CaseResult],
    *,
    report_name: str = "baseline_vector_500_75",
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{report_name}.json"
    markdown_path = output_dir / f"{report_name}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    metrics = report["metrics"]
    lines = [
        "# RAG Retrieval Baseline",
        "",
        f"- 모델: `{report['settings']['embedding_model']}` "
        f"({report['settings']['dimensions']}차원)",
        f"- 청킹: {report['settings']['maximum_tokens']}단어 / "
        f"overlap {report['settings']['overlap_tokens']}단어",
        f"- 검색: cosine similarity >= {report['settings']['threshold']}, "
        f"Top-{report['settings']['top_k']}",
        f"- 코퍼스: {report['corpus']['documents']}개 문서, {report['corpus']['chunks']}개 청크",
        f"- 사례: 긍정 {metrics['positive_cases']}개, 부정 {metrics['negative_cases']}개",
        "",
        "## Metrics",
        "",
        "| Metric | Score |",
        "|---|---:|",
    ]
    for key in (
        "hit_at_1",
        "recall_at_3",
        "recall_at_5",
        "mrr",
        "negative_rejection_accuracy",
        "negative_false_positive_rate",
    ):
        lines.append(f"| {key} | {metrics[key]:.4f} |")
    lines.extend(["", "## 실패 사례", ""])
    failures = [
        item
        for item in results
        if (item.expected_behavior == "retrieve_evidence" and item.found_rank is None)
        or (item.expected_behavior == "insufficient_evidence" and item.retrieved)
    ]
    if not failures:
        lines.append("없음")
    else:
        for item in failures:
            top = item.retrieved[0] if item.retrieved else None
            detail = (
                f"top={top.document_id}#{top.chunk_index}, similarity={top.similarity:.4f}"
                if top
                else "검색 결과 없음"
            )
            lines.append(f"- `{item.case_id}`: {detail}")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_threshold_sweep(
    output_dir: Path,
    rows: list[dict[str, int | float]],
    selected: dict[str, int | float],
) -> None:
    payload = {
        "selection_rule": "harmonic_mean(recall_at_5, negative_rejection_accuracy)",
        "selected": selected,
        "thresholds": rows,
    }
    (output_dir / "threshold_sweep.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# RAG Threshold Sweep",
        "",
        "선택 기준: Recall@5와 근거 없음 거절 정확도의 조화평균",
        "",
        "| Threshold | Hit@1 | Recall@3 | Recall@5 | MRR | "
        "Negative rejection | False positive | Balanced |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['threshold']:.2f} | {row['hit_at_1']:.3f} | "
            f"{row['recall_at_3']:.3f} | {row['recall_at_5']:.3f} | "
            f"{row['mrr']:.3f} | {row['negative_rejection_accuracy']:.3f} | "
            f"{row['negative_false_positive_rate']:.3f} | "
            f"{row['balanced_score']:.3f} |"
        )
    lines.extend(
        [
            "",
            f"추천 임계값: **{selected['threshold']:.2f}** "
            f"(Balanced {selected['balanced_score']:.3f})",
        ]
    )
    (output_dir / "threshold_sweep.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--threshold",
        type=float,
        help="설정 파일의 RAG 임계값을 이번 평가에서만 덮어씀",
    )
    parser.add_argument(
        "--limit-per-behavior",
        type=int,
        help="각 라벨에서 문서 전체에 고르게 추출할 최대 사례 수",
    )
    parser.add_argument("--maximum-tokens", type=int, default=500)
    parser.add_argument("--overlap-tokens", type=int, default=75)
    parser.add_argument(
        "--thresholds",
        type=float,
        nargs="+",
        help="한 번의 임베딩으로 비교할 임계값 목록",
    )
    parser.add_argument(
        "--relevance-check",
        action="store_true",
        help="면접 모델의 구조화 relevance 판정을 검색 뒤에 적용",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = AppSettings()
    threshold = (
        args.threshold if args.threshold is not None else settings.rag_similarity_threshold
    )
    documents, cases = load_dataset(args.dataset_dir)
    if args.limit_per_behavior is not None:
        cases = stratified_cases(cases, args.limit_per_behavior)
    chunks = build_corpus(
        documents,
        maximum_tokens=args.maximum_tokens,
        overlap_tokens=args.overlap_tokens,
    )
    client = OpenAIEmbeddingClient(
        settings.openai_api_key.get_secret_value(),
        settings.openai_embedding_model,
        dimensions=settings.openai_embedding_dimensions,
    )
    chunk_vectors, chunk_calls, chunk_seconds = _embed_batches(
        client, [item.text for item in chunks]
    )
    query_vectors, query_calls, query_seconds = _embed_batches(
        client, [build_query_text(case) for case in cases]
    )
    results = evaluate(
        cases=cases,
        chunks=chunks,
        chunk_embeddings=chunk_vectors,
        query_embeddings=query_vectors,
        threshold=threshold,
        top_k=args.top_k,
    )
    if args.relevance_check:
        relevance_provider = OpenAIResponsesClient(
            settings.openai_api_key.get_secret_value(),
            settings.openai_interview_model,
            60,
            max_output_tokens=3000,
        )
        results = apply_relevance_check(
            cases=cases, results=results, provider=relevance_provider
        )
    metrics = aggregate_metrics(results)
    report: dict[str, Any] = {
        "experiment": "rag_vector_with_optional_relevance_check",
        "created_at": datetime.now(UTC).isoformat(),
        "query_mode": "production_json_shape_with_gold_evaluation_query",
        "relevance_check": args.relevance_check,
        "settings": {
            "embedding_model": settings.openai_embedding_model,
            "dimensions": settings.openai_embedding_dimensions,
            "maximum_tokens": args.maximum_tokens,
            "overlap_tokens": args.overlap_tokens,
            "threshold": threshold,
            "top_k": args.top_k,
        },
        "corpus": {"documents": len(documents), "chunks": len(chunks)},
        "embedding": {
            "api_calls": chunk_calls + query_calls,
            "chunk_inputs": len(chunks),
            "query_inputs": len(cases),
            "elapsed_seconds": round(chunk_seconds + query_seconds, 3),
        },
        "metrics": metrics,
        "cases": [_case_payload(item) for item in results],
    }
    report_name = (
        f"improved_vector_{args.maximum_tokens}_{args.overlap_tokens}_relevance"
        if args.relevance_check
        else f"baseline_vector_{args.maximum_tokens}_{args.overlap_tokens}"
    )
    write_reports(args.output_dir, report, results, report_name=report_name)
    if args.thresholds:
        rows: list[dict[str, int | float]] = []
        for threshold in sorted(set(args.thresholds)):
            threshold_results = evaluate(
                cases=cases,
                chunks=chunks,
                chunk_embeddings=chunk_vectors,
                query_embeddings=query_vectors,
                threshold=threshold,
                top_k=args.top_k,
            )
            rows.append({"threshold": threshold, **aggregate_metrics(threshold_results)})
        scored_rows = [
            {
                **row,
                "balanced_score": select_balanced_threshold([row])["balanced_score"],
            }
            for row in rows
        ]
        selected = select_balanced_threshold(scored_rows)
        write_threshold_sweep(args.output_dir, scored_rows, selected)
        print(f"selected threshold: {selected['threshold']:.2f}")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"reports: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
