from scripts.rag_question_eval import (
    GeneratedCaseQuestion,
    QuestionQualityDecision,
    quality_metrics,
    render_question_review,
)


def question(case_id: str) -> GeneratedCaseQuestion:
    return GeneratedCaseQuestion(
        case_id=case_id,
        expected_behavior="retrieve_evidence",
        desired_role="백엔드 개발자",
        query="성능 개선 경험",
        question="성능을 어떻게 개선했나요?",
        source_chunk_keys=("resume#0",),
        evidence=("쿼리를 줄였습니다.",),
        supported_claims=("쿼리 개선",),
        unsupported_claims=(),
    )


def test_quality_metrics_require_every_gate_for_overall_pass() -> None:
    decisions = [
        QuestionQualityDecision(
            case_id="pass",
            grounding=True,
            premise_accuracy=True,
            role_relevance=4,
            specificity=4,
            clarity=5,
            answer_leakage=False,
            duplicate_with_case_ids=[],
            reason="통과",
        ),
        QuestionQualityDecision(
            case_id="leak",
            grounding=True,
            premise_accuracy=True,
            role_relevance=5,
            specificity=5,
            clarity=5,
            answer_leakage=True,
            duplicate_with_case_ids=[],
            reason="답 노출",
        ),
    ]

    metrics = quality_metrics([question("pass"), question("leak")], decisions)

    assert metrics["grounding_rate"] == 1
    assert metrics["answer_leakage_rate"] == 0.5
    assert metrics["all_quality_gates_rate"] == 0.5


def test_question_review_shows_question_evidence_and_leakage_reason() -> None:
    item = question("resume-01")
    decision = QuestionQualityDecision(
        case_id="resume-01",
        grounding=True,
        premise_accuracy=True,
        role_relevance=5,
        specificity=5,
        clarity=5,
        answer_leakage=False,
        duplicate_with_case_ids=[],
        reason="이력서에 적힌 개선 경험을 확인하는 질문입니다.",
    )

    review = render_question_review([item], [decision])

    assert "성능을 어떻게 개선했나요?" in review
    assert "> 쿼리를 줄였습니다." in review
    assert "답 노출 판정: 아니요" in review
    assert "이력서에 적힌 개선 경험" in review
