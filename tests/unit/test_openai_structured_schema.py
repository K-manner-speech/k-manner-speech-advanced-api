from __future__ import annotations

from typing import Any

from app.adapters.interview_provider import InterviewAnalysisResult, InterviewQuestionResult
from app.ai.schemas import (
    GeneralFeedback,
    GeneralSessionResultOutput,
    InterviewSessionResultOutput,
    ScenarioGoalProgress,
)
from app.schemas.base import ContractModel

# executors 에서 OpenAI Responses API 로 보내는 결과 모델.
OPENAI_RESULT_TYPES: list[type[ContractModel]] = [
    GeneralFeedback,
    ScenarioGoalProgress,
    InterviewAnalysisResult,
    InterviewQuestionResult,
    GeneralSessionResultOutput,
    InterviewSessionResultOutput,
]


def _objects(schema: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []

    def walk(name: str, node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "object" and "properties" in node:
            found.append((name, node))
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                for property_name, child in value.items():
                    walk(f"{name}.{property_name}", child)
            elif isinstance(value, dict):
                walk(f"{name}.{key}" if key != "$defs" else name, value)
            elif isinstance(value, list):
                for child in value:
                    walk(name, child)

    walk(schema.get("title", "root"), schema)
    return found


def test_openai_schemas_mark_every_property_required() -> None:
    """OpenAI 구조화 출력은 properties 의 모든 키가 required 에 있어야 한다.

    Pydantic 필드에 기본값을 주면 required 에서 빠지고, 요청이 400
    invalid_json_schema 로 거부된다. AI 호출 단계에서야 드러나므로 여기서 막는다.
    nullable 이 필요하면 기본값 없이 `X | None` 으로 선언한다.
    """
    offenders: list[str] = []
    for model in OPENAI_RESULT_TYPES:
        for name, node in _objects(model.model_json_schema()):
            missing = set(node["properties"]) - set(node.get("required", []))
            if missing:
                offenders.append(f"{model.__name__}/{name}: {sorted(missing)}")

    assert not offenders, "required 에서 빠진 속성: " + "; ".join(offenders)
