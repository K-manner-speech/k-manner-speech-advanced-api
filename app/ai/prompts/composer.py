"""Compose common and persona YAML fragments into one catalog prompt."""

from __future__ import annotations

from app.ai.prompts.loader import PromptCatalog
from app.ai.prompts.models import PromptFragment


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

    def compose_conversation(self, persona_bundle: str | None) -> str:
        fragments = self._load_bundle_fragments("base_chat")
        if persona_bundle:
            fragments.extend(self._load_bundle_fragments(f"personas/{persona_bundle}"))

        unique: dict[str, PromptFragment] = {}
        for fragment in fragments:
            unique.setdefault(fragment.id, fragment)
        enabled = [fragment for fragment in unique.values() if fragment.enabled]
        enabled.sort(key=lambda fragment: fragment.priority, reverse=True)
        return "\n\n".join(fragment.prompt.strip() for fragment in enabled)
