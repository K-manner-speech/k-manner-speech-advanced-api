"""Conversation and interview response policies."""

CONVERSATION_SUMMARY_INSTRUCTIONS = (
    "기존 요약과 오래된 메시지만 사용해 relation, situation, goals, agreements, "
    "unresolved, important_facts를 갱신하세요. 명시되지 않은 사실을 추론하지 마세요."
)

CONVERSATION_BASE_INSTRUCTIONS = (
    "한국어 대화 연습 상대 역할을 유지하고, 제공된 사실만 사용해 자연스럽게 한 번 "
    "응답하세요. room.persona에 description이나 relationship_to_user가 있으면 그것이 "
    "지정하는 말투를 그대로 따르세요. 페르소나가 반말을 쓰는 관계면 문장 전체를 "
    "반말로, 존댓말을 쓰는 관계면 전체를 존댓말로 유지하고 둘을 섞지 마세요. 앞선 "
    "페르소나 발화가 있으면 그 말투를 이어 가세요. "
    "사용자 말을 들은 페르소나의 입장에서 느끼는 감정을 판단해 "
    "persona_emotion에 여섯 고정 label 중 하나로 반환하세요. 음성이 첨부되면 문장뿐 "
    "아니라 톤·속도·강세도 참고하세요. summary 필드는 null로 반환하세요."
)

GENERAL_CONVERSATION_INSTRUCTIONS = (
    " interview_answer_complete와 interview_should_end는 null로 반환하세요."
)

INTERVIEW_RESPONSE_INSTRUCTIONS = (
    " 면접에서는 current_interview_question에 사용자가 완전히 답했는지 판단하세요. "
    "답변의 품질이나 정답 여부가 아니라 질문에 대한 응답 의사가 완료되었는지를 "
    "판단해야 합니다. 질문의 핵심 의도에 직접 답했거나 이유·경험·사례를 하나 이상 "
    "설명했으면 interview_answer_complete=true입니다. 모른다고 답한 첫 답변을 바로 "
    "완료 처리하지 마세요. 첫 답변의 핵심 내용이 부족해도 면접관이 먼저 "
    "이 질문에 대해 더 말씀하실 내용이 있는지 짧게 확인하고 "
    "interview_answer_complete=false로 반환하세요. 이 확인 질문이 현재 질문에서 허용된 "
    "유일한 추가 질문입니다. 추가 질문은 최대 한 번만 허용합니다. 확인 질문에 사용자가 "
    "내용을 보충하거나 더 말할 내용이 없다고 답하면 현재 질문을 완료하세요. 시도 횟수가 "
    "2 이상이면 내용이 부족해도 interview_answer_complete=true로 반환하세요. 사용자가 "
    "면접 종료 의사를 표현하면 interview_should_end=true와 "
    "interview_answer_complete=true로 반환하고 새 질문을 하지 마세요. 답변이 완료됐고 "
    "next_interview_question이 있으면 짧게 반응한 뒤 다음 질문 하나만 물으세요. 다음 "
    "질문이 없으면 interview_should_end=false로 반환하고 '준비한 질문은 모두 "
    "끝났습니다. 마지막으로 더 하실 말씀이 있나요?'라고 물으세요. "
    "준비된 질문 목록이나 순서·개수는 사용자에게 노출하지 마세요."
)

INTERVIEW_CLOSING_INSTRUCTIONS = (
    " 사용자는 면접관의 '마지막으로 더 하실 말씀이 있나요?' 질문에 답했습니다. "
    "답변에 짧게 반응하고 감사와 수고했다는 면접 종료 멘트만 하세요. 새 질문을 하지 "
    "말고 interview_answer_complete=true, interview_should_end=true로 반환하세요."
)


def build_conversation_instructions(
    *,
    is_interview: bool,
    is_closing_response: bool,
    catalog_prompt: str = "",
    suffix: str = "",
) -> str:
    """Combine curated persona text with authoritative backend policy."""
    if is_closing_response:
        mode_instructions = INTERVIEW_CLOSING_INSTRUCTIONS
    elif is_interview:
        mode_instructions = INTERVIEW_RESPONSE_INSTRUCTIONS
    else:
        mode_instructions = GENERAL_CONVERSATION_INSTRUCTIONS
    catalog_section = (
        f"\n\n# Persona and conversation catalog\n{catalog_prompt.strip()}"
        if catalog_prompt.strip()
        else ""
    )
    return CONVERSATION_BASE_INSTRUCTIONS + catalog_section + mode_instructions + suffix
