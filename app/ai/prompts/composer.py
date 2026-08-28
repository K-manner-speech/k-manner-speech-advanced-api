"""Compose common and persona YAML fragments into one catalog prompt."""

from __future__ import annotations

from app.ai.prompts.loader import PromptCatalog
from app.ai.prompts.models import PromptFragment, PromptVoice


class PromptComposer:
    def __init__(self, catalog: PromptCatalog) -> None:
        self._catalog = catalog

    @classmethod
    def default(cls) -> PromptComposer:
        return cls(PromptCatalog.default())

    def _load_bundle_fragments(self, name: str) -> list[PromptFragment]:
        bundle = self._catalog.load_bundle(name)
        return [
            self._catalog.load_fragment(reference.category, reference.name)
            for reference in bundle.prompts
        ]

    def compose_conversation(
        self, persona_bundle: str | None, role: str | None = None
    ) -> str:
        """공통 + 페르소나 + 역할 조각을 하나의 프롬프트로 합친다.

        역할은 (페르소나, 시나리오) 조합마다 달라지므로 페르소나 번들이 아니라
        호출 시점에 지정한다. 같은 팀장이 한 시나리오에서는 상사, 다른 시나리오에서는
        함께 대응하는 담당자일 수 있다.
        """
        fragments = self._load_bundle_fragments("base_chat")
        if persona_bundle:
            fragments.extend(self._load_bundle_fragments(f"personas/{persona_bundle}"))
        if role:
            fragments.append(self._catalog.load_fragment("roles", role))

        unique: dict[str, PromptFragment] = {}
        for fragment in fragments:
            unique.setdefault(fragment.id, fragment)
        enabled = [fragment for fragment in unique.values() if fragment.enabled]
        enabled.sort(key=lambda fragment: fragment.priority, reverse=True)
        return "\n\n".join(fragment.prompt.strip() for fragment in enabled)

    def voice_for(self, persona_bundle: str | None) -> PromptVoice | None:
        """페르소나 번들이 지정한 TTS 음성. 번들이 없거나 voice가 없으면 None."""
        if not persona_bundle:
            return None
        return self._catalog.load_bundle(f"personas/{persona_bundle}").voice

    def task_instruction(self, task: str) -> str:
        """대화가 아닌 worker 작업(감정 분석·피드백·결과 등)의 지시문."""
        return self._catalog.load_fragment("tasks", task).prompt.strip()

    def tts_instruction(self, persona_bundle: str | None, emotion: str) -> str:
        """TTS 발화 지시문. 페르소나 화자 설정 뒤에 감정별 어조를 잇는다.

        모르는 감정은 neutral 로 떨어뜨린다. worker 가 넘기는 값은 DB 제약으로
        여섯 가지뿐이지만, 조각 파일이 빠져도 합성이 멈추지 않게 한다.
        """
        try:
            delivery = self._catalog.load_fragment("emotions", emotion).prompt.strip()
        except (FileNotFoundError, ValueError):
            delivery = self._catalog.load_fragment("emotions", "neutral").prompt.strip()
        voice = self.voice_for(persona_bundle)
        if voice and voice.style:
            return f"{voice.style}, {delivery}"
        return delivery
