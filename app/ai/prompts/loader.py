"""Safe YAML loading for the curated prompt catalog."""

from __future__ import annotations

import re
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from app.ai.prompts.models import PromptBundle, PromptFragment

_SAFE_PATH = re.compile(r"^[a-z0-9_-]+(?:/[a-z0-9_-]+)*$")
_CATEGORIES = frozenset(
    {"identities", "modes", "personalities", "profiles", "rules", "styles", "tasks"}
)


class PromptCatalog:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @classmethod
    def default(cls) -> PromptCatalog:
        return cls(Path(__file__).resolve().parent / "catalog")

    @staticmethod
    def _validate_path(value: str) -> None:
        if not _SAFE_PATH.fullmatch(value):
            raise ValueError(f"invalid prompt path: {value}")

    @staticmethod
    def _read_yaml(path: Path) -> object:
        if not path.is_file():
            raise FileNotFoundError(path)
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def load_fragment(self, category: str, name: str) -> PromptFragment:
        self._validate_path(category)
        self._validate_path(name)
        if category not in _CATEGORIES:
            raise ValueError(f"unsupported prompt category: {category}")
        raw = self._read_yaml(self.root / category / f"{name}.yaml")
        return PromptFragment.model_validate(raw)

    def load_bundle(self, name: str) -> PromptBundle:
        self._validate_path(name)
        raw = self._read_yaml(self.root / "bundles" / f"{name}.yaml")
        return PromptBundle.model_validate(raw)
