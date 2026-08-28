"""Backend-owned prompts for non-conversation AI worker tasks."""

EMOTION_ANALYSIS_INSTRUCTIONS = (
    "사용자 발화에서 드러난 감정을 여섯 고정 label 중 하나로 분류하고 짧은 근거를 "
    "제시하세요. 추측을 사실처럼 표현하지 마세요."
)

TURN_FEEDBACK_INSTRUCTIONS = (
    "한국어 발화를 높임법, 예의와 배려, 상황 적합성, 자연스러움 네 항목으로 "
    "각각 정수 0~25점 평가하세요. 답변에 실제로 드러난 내용만 근거로 삼으세요."
)

DOCUMENT_ANALYSIS_INSTRUCTIONS = (
    "지원 문서를 면접 준비용으로 구조화하세요. 문서의 사실만 사용하고 인용 근거를 "
    "보존하세요."
)

INTERVIEW_QUESTION_GENERATION_INSTRUCTIONS = (
    "제공된 근거만 사용해 면접 질문을 정확히 {question_count}개 생성하고 각 source ref를 "
    "보존하세요."
)

SESSION_RESULT_INSTRUCTIONS = (
    "대화 결과를 강점과 개선점으로 정리하세요. 면접이면 고정 5개 항목을 각각 "
    "정수 1~20점으로 평가하고 합격·불합격을 판정하지 마세요. 실제 답변만 근거로 "
    "평가하세요."
)
