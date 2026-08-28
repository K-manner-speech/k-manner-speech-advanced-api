from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.ai.prompts.composer import PromptComposer
from app.ai.prompts.loader import PromptCatalog
from app.ai.prompts.policies.conversation import build_conversation_instructions
from worker.domain_adapters import ConversationAdapter


def test_base_and_persona_bundles_compose_once_by_priority() -> None:
    composer = PromptComposer.default()

    prompt = composer.compose_conversation("doyun")

    assert "# Universal Safety Rules" in prompt
    assert "# Hallucination Prevention" in prompt
    assert "당신은 친근한 친구처럼 대화한다" in prompt
    assert "친근하고 편안한 말투" in prompt
    assert "당신의 성은 김, 이름은 도윤" in prompt
    assert prompt.count("# Universal Safety Rules") == 1
    assert prompt.index("# Universal Safety Rules") < prompt.index("# Style")


def test_every_installed_yaml_file_matches_its_catalog_model() -> None:
    catalog = PromptCatalog.default()

    for bundle_path in (catalog.root / "bundles").rglob("*.yaml"):
        bundle_name = bundle_path.relative_to(catalog.root / "bundles").with_suffix("").as_posix()
        catalog.load_bundle(bundle_name)
    for category in (
        "identities",
        "modes",
        "personalities",
        "profiles",
        "rules",
        "styles",
        "tasks",
    ):
        for fragment_path in (catalog.root / category).glob("*.yaml"):
            catalog.load_fragment(category, fragment_path.stem)


def test_catalog_rejects_path_traversal_before_file_access(tmp_path: Path) -> None:
    catalog = PromptCatalog(tmp_path)

    with pytest.raises(ValueError, match="invalid prompt path"):
        catalog.load_fragment("rules", "../../secrets")
    with pytest.raises(ValueError, match="invalid prompt path"):
        catalog.load_bundle("/absolute")


def test_runtime_catalog_excludes_interview_mode_and_scenarios() -> None:
    catalog = PromptCatalog.default()

    assert not (catalog.root / "modes" / "interview.yaml").exists()
    assert not (catalog.root / "scenarios").exists()
    with pytest.raises(FileNotFoundError):
        catalog.load_fragment("modes", "interview")


def test_persona_catalog_enriches_but_does_not_replace_interview_policy() -> None:
    persona_prompt = PromptComposer.default().compose_conversation("doyun")

    instructions = build_conversation_instructions(
        is_interview=True,
        is_closing_response=False,
        catalog_prompt=persona_prompt,
    )

    assert "당신의 성은 김, 이름은 도윤" in instructions
    assert "사용자 말을 들은 페르소나의 입장" in instructions
    assert "추가 질문은 최대 한 번" in instructions
    assert "interview_should_end" in instructions


def test_unknown_persona_bundle_fails_instead_of_guessing() -> None:
    with pytest.raises(ValueError, match="invalid prompt path"):
        PromptComposer.default().compose_conversation("김도윤")


def test_conversation_adapter_passes_explicit_bundle_key_without_name_guessing() -> None:
    source = inspect.getsource(ConversationAdapter.claim)

    assert "p.prompt_bundle_key as persona_prompt_bundle" in source
    assert '"prompt_bundle": row["persona_prompt_bundle"]' in source
    assert 'row["persona_name"].lower()' not in source
