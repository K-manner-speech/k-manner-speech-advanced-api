"""면접 질문 결과 모델의 계약을 지킨다.

executors 가 provider 응답을 validate_count 로 검사한다. 같은 계약을 보던
테스트가 있었지만 실행되지 않는 provider 구현을 거쳐서 확인해, 그 구현이
사라지면 함께 사라질 검사였다. 모델을 직접 겨눈다.
"""

from __future__ import annotations

import pytest

from app.adapters.interview_provider import (
    GeneratedQuestion,
    InterviewQuestionResult,
    QuestionSourceRef,
)


def _question(sequence: int) -> GeneratedQuestion:
    return GeneratedQuestion(
        sequence=sequence,
        text=f"질문 {sequence}",
        type="required",
        required=True,
        source_refs=[QuestionSourceRef(
            evidence_no=1, section="", chunk_id=None, document_id=None, evidence=None)],
        evaluation_focus=["문제 해결"],
    )


def test_validate_count_accepts_the_requested_number_in_order() -> None:
    result = InterviewQuestionResult(questions=[_question(1), _question(2)])

    assert result.validate_count(2) is result


@pytest.mark.parametrize(
    "questions,requested",
    [
        ([], 1),
        ([_question(1)], 2),
        ([_question(1), _question(2)], 1),
        ([_question(2)], 1),
        ([_question(1), _question(3)], 2),
    ],
)
def test_validate_count_rejects_missing_or_out_of_order_questions(
    questions: list[GeneratedQuestion], requested: int
) -> None:
    with pytest.raises(ValueError):
        InterviewQuestionResult(questions=questions).validate_count(requested)


def test_question_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        InterviewQuestionResult.model_validate(
            {"questions": [], "unexpected": True}
        )


def test_setup_request_rejects_an_application_type_outside_the_list() -> None:
    """질문 깊이를 이 값으로 정하므로 아무 문자열이나 받으면 안 된다."""
    from pydantic import ValidationError

    from app.schemas.interviews import InterviewSetupCreateRequest

    InterviewSetupCreateRequest(desired_role="백엔드 개발자", application_type="경력")
    InterviewSetupCreateRequest(desired_role="백엔드 개발자")

    with pytest.raises(ValidationError):
        InterviewSetupCreateRequest(desired_role="백엔드 개발자", application_type="시니어")
