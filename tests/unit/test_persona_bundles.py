"""카탈로그에 실린 페르소나 번들이 실제로 조립되는지 확인한다."""

import pytest

from app.ai.prompts.composer import PromptComposer
from worker.domain_adapters import INTERVIEWER_PROMPT_BUNDLE

BUNDLES = ["seojun", "minjun", "seoyeon"]


@pytest.mark.parametrize("bundle", BUNDLES)
def test_every_persona_bundle_composes(bundle: str) -> None:
    prompt = PromptComposer.default().compose_conversation(bundle)

    assert prompt.strip()
    # base_chat 은 모든 대화에 깔린다.
    assert "Universal Safety Rules" in prompt
    assert "Speech Level" in prompt


@pytest.mark.parametrize("bundle", BUNDLES)
def test_every_persona_bundle_declares_a_voice(bundle: str) -> None:
    voice = PromptComposer.default().voice_for(bundle)

    assert voice is not None
    assert voice.key
    assert voice.style


def test_speech_level_is_stated_once_for_every_persona() -> None:
    composer = PromptComposer.default()
    for bundle in BUNDLES:
        prompt = composer.compose_conversation(bundle)
        # 규칙 조각은 base_chat 에서 한 번만 들어가야 한다.
        assert prompt.count("# Speech Level") == 1


def test_the_senior_speaks_banmal_and_the_others_do_not() -> None:
    composer = PromptComposer.default()

    assert "반말" in composer.compose_conversation("seojun")
    assert "존댓말" in composer.compose_conversation("minjun")
    assert "존댓말" in composer.compose_conversation("seoyeon")


def test_a_persona_without_a_bundle_still_gets_the_base_prompt() -> None:
    composer = PromptComposer.default()

    prompt = composer.compose_conversation(None)

    assert "Universal Safety Rules" in prompt
    assert composer.voice_for(None) is None


ROLES = ["senior", "supervisor", "colleague", "customer"]


@pytest.mark.parametrize("role", ROLES)
def test_every_role_fragment_composes(role: str) -> None:
    prompt = PromptComposer.default().compose_conversation("minjun", role)

    assert "# Role" in prompt


def test_the_same_persona_gets_a_different_role_per_scenario() -> None:
    composer = PromptComposer.default()

    supervisor = composer.compose_conversation("minjun", "supervisor")
    colleague = composer.compose_conversation("minjun", "colleague")

    # 같은 팀장이지만 시나리오에 따라 상사이기도, 함께 대응하는 담당자이기도 하다.
    assert "직속 상사" in supervisor
    assert "직속 상사" not in colleague
    assert "같은 편에서 일하는 담당자" in colleague
    # 페르소나 정체성은 두 경우 모두 같다.
    assert "김, 이름은 민준" in supervisor
    assert "김, 이름은 민준" in colleague


def test_a_scenario_without_a_role_omits_the_role_fragment() -> None:
    prompt = PromptComposer.default().compose_conversation("minjun", None)

    assert "# Role" not in prompt
    assert "김, 이름은 민준" in prompt


EMOTIONS = ["neutral", "happy", "sad", "angry", "curious", "embarrassment"]


@pytest.mark.parametrize("emotion", EMOTIONS)
def test_every_emotion_has_a_delivery_instruction(emotion: str) -> None:
    instruction = PromptComposer.default().tts_instruction(None, emotion)

    assert instruction.strip()


def test_the_persona_voice_style_leads_the_emotion_instruction() -> None:
    instruction = PromptComposer.default().tts_instruction("seojun", "happy")

    assert instruction.startswith("20대 초반 남자 대학생")
    assert "밝고 따뜻하며" in instruction


def test_a_persona_without_a_bundle_gets_the_emotion_alone() -> None:
    instruction = PromptComposer.default().tts_instruction(None, "angry")

    assert instruction == "불편함이 드러나되 과장하지 않고 단호한 어조로 말하세요."


def test_an_unknown_emotion_falls_back_to_neutral() -> None:
    composer = PromptComposer.default()

    assert composer.tts_instruction(None, "elated") == composer.tts_instruction(None, "neutral")


def test_turn_feedback_defines_each_scoring_category() -> None:
    prompt = PromptComposer.default().task_instruction("turn_feedback")

    # 항목 이름만 나열하면 모델이 context_fit 을 "목표 적합성"으로 읽는다.
    for category in ("honorifics", "courtesy", "context_fit", "naturalness"):
        assert category in prompt
    assert "previous_persona_message 에 대한 응답으로 적절한지" in prompt


def test_turn_feedback_hands_goal_judgement_to_the_session_result() -> None:
    prompt = PromptComposer.default().task_instruction("turn_feedback")

    assert "종합 평가가 판정하며, 개별 발화 채점의 몫이 아닙니다" in prompt


def test_session_result_keeps_the_goal_judgement() -> None:
    prompt = PromptComposer.default().task_instruction("session_result_scenario")

    assert "success_conditions" in prompt
    assert "대화 전체" in prompt


def test_interviewer_borrows_a_real_persona_voice() -> None:
    """면접관에게도 화자 설정이 있어야 한다.

    면접방에는 personas 행이 없어 번들이 비고, 그러면 TTS 가 기본 음성으로
    떨어져 면접관이 매번 다른 사람처럼 들린다. 전용 페르소나가 생기기 전까지
    김민준 팀장의 번들을 빌려 쓴다.
    """
    composer = PromptComposer.default()

    assert INTERVIEWER_PROMPT_BUNDLE in BUNDLES
    voice = composer.voice_for(INTERVIEWER_PROMPT_BUNDLE)
    assert voice is not None
    instruction = composer.tts_instruction(INTERVIEWER_PROMPT_BUNDLE, "neutral")
    # 번들이 없을 때의 지시문에는 화자 설정이 붙지 않는다.
    assert instruction != composer.tts_instruction(None, "neutral")
    assert voice.style in instruction


def test_session_result_summaries_do_not_repeat_detail_cards() -> None:
    composer = PromptComposer.default()
    for task_id in (
        "session_result_free_chat",
        "session_result_scenario",
        "session_result_interview",
    ):
        prompt = composer.task_instruction(task_id)
        assert "3문장 이내, 180자 이내" in prompt
        assert "구체적인 근거와 개선 방법은 항목별 카드에서만 설명" in prompt
