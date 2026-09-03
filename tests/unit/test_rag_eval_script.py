from __future__ import annotations

import pytest

from scripts.rag_eval import (
    CaseResult,
    CorpusChunk,
    RetrievedChunk,
    aggregate_metrics,
    build_corpus,
    contains_gold_quote,
    cosine_similarity,
    retrieve_top_k,
    select_balanced_threshold,
)


def test_build_corpus_reuses_production_chunking_and_rejects_empty_document() -> None:
    corpus = build_corpus(
        {"resume-1": "하나 둘 셋 넷 다섯 여섯 일곱 여덟 아홉 열"},
        maximum_tokens=5,
        overlap_tokens=2,
    )

    assert [(chunk.document_id, chunk.chunk_index, chunk.text) for chunk in corpus] == [
        ("resume-1", 0, "하나 둘 셋 넷 다섯"),
        ("resume-1", 1, "넷 다섯 여섯 일곱 여덟"),
        ("resume-1", 2, "일곱 여덟 아홉 열"),
    ]

    with pytest.raises(ValueError, match="empty document"):
        build_corpus({"resume-1": "  \n"})


def test_cosine_search_applies_threshold_order_and_top_k() -> None:
    chunks = [
        CorpusChunk("d1", 0, "첫 청크"),
        CorpusChunk("d2", 0, "둘째 청크"),
        CorpusChunk("d3", 0, "셋째 청크"),
    ]

    retrieved = retrieve_top_k(
        [1.0, 0.0],
        chunks,
        [[1.0, 0.0], [0.8, 0.6], [0.0, 1.0]],
        threshold=0.7,
        top_k=2,
    )

    assert [(item.document_id, item.similarity) for item in retrieved] == [
        ("d1", 1.0),
        ("d2", 0.8),
    ]
    with pytest.raises(ValueError, match="dimension"):
        cosine_similarity([1.0], [1.0, 0.0])
    with pytest.raises(ValueError, match="zero vector"):
        cosine_similarity([0.0, 0.0], [1.0, 0.0])


def test_gold_quote_matching_normalizes_whitespace_only() -> None:
    assert contains_gold_quote(
        "Fetch Join과 조회 전용 DTO를 적용해\n쿼리를 101회에서 3회로 줄였습니다.",
        ["Fetch Join과 조회 전용 DTO를 적용해 쿼리를 101회에서 3회로 줄였습니다."],
    )
    assert not contains_gold_quote("쿼리를 개선했습니다.", ["쿼리를 101회에서 3회로 줄였습니다."])


def test_aggregate_metrics_separates_positive_and_negative_cases() -> None:
    positive_first = CaseResult(
        case_id="p1",
        expected_behavior="retrieve_evidence",
        found_rank=1,
        retrieved=[],
    )
    positive_second = CaseResult(
        case_id="p2",
        expected_behavior="retrieve_evidence",
        found_rank=2,
        retrieved=[],
    )
    positive_miss = CaseResult(
        case_id="p3",
        expected_behavior="retrieve_evidence",
        found_rank=None,
        retrieved=[],
    )
    negative_rejected = CaseResult(
        case_id="n1",
        expected_behavior="insufficient_evidence",
        found_rank=None,
        retrieved=[],
    )
    negative_false_positive = CaseResult(
        case_id="n2",
        expected_behavior="insufficient_evidence",
        found_rank=None,
        retrieved=[RetrievedChunk("d1", 0, "관련 없는 청크", 0.5, False)],
    )

    metrics = aggregate_metrics(
        [positive_first, positive_second, positive_miss, negative_rejected, negative_false_positive]
    )

    assert metrics == {
        "positive_cases": 3,
        "negative_cases": 2,
        "hit_at_1": pytest.approx(1 / 3),
        "recall_at_3": pytest.approx(2 / 3),
        "recall_at_5": pytest.approx(2 / 3),
        "mrr": pytest.approx(0.5),
        "negative_rejection_accuracy": pytest.approx(0.5),
        "negative_false_positive_rate": pytest.approx(0.5),
    }


def test_aggregate_metrics_requires_both_case_types() -> None:
    with pytest.raises(ValueError, match="positive and negative"):
        aggregate_metrics(
            [CaseResult("only-positive", "retrieve_evidence", 1, [])]
        )


def test_aggregate_metrics_reports_partial_evidence_separately() -> None:
    metrics = aggregate_metrics(
        [
            CaseResult("positive", "retrieve_evidence", 1, []),
            CaseResult("negative", "insufficient_evidence", None, []),
            CaseResult("partial-hit", "partial_evidence", 3, []),
            CaseResult("partial-miss", "partial_evidence", None, []),
        ]
    )

    assert metrics["partial_cases"] == 2
    assert metrics["partial_evidence_recall_at_5"] == pytest.approx(0.5)


def test_select_balanced_threshold_uses_harmonic_mean_and_prefers_recall_on_tie() -> None:
    rows = [
        {"threshold": 0.4, "recall_at_5": 1.0, "negative_rejection_accuracy": 0.0},
        {"threshold": 0.5, "recall_at_5": 0.8, "negative_rejection_accuracy": 0.8},
        {"threshold": 0.6, "recall_at_5": 0.5, "negative_rejection_accuracy": 1.0},
    ]

    selected = select_balanced_threshold(rows)

    assert selected["threshold"] == 0.5
    assert selected["balanced_score"] == pytest.approx(0.8)
