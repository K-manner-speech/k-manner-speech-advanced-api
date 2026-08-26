from typing import Any
from uuid import uuid4

from app.repositories.interviews import InterviewRepository


class FakeMappings:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def one_or_none(self) -> dict[str, Any]:
        return self._row


class FakeResult:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def mappings(self) -> FakeMappings:
        return FakeMappings(self._row)


class FakeSession:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def execute(self, *_args: Any, **_kwargs: Any) -> FakeResult:
        return FakeResult(self._row)


def test_processing_analysis_returns_empty_sections_instead_of_null() -> None:
    analysis_id = uuid4()
    document_id = uuid4()
    repository = InterviewRepository.__new__(InterviewRepository)
    repository._session = FakeSession(  # type: ignore[assignment]
        {
            "id": analysis_id,
            "document_id": document_id,
            "document_version": 1,
            "status": "processing",
            "extracted_sections": None,
            "citation_evidence": None,
            "error_code": None,
        }
    )

    result = repository.get_analysis(uuid4(), analysis_id)

    assert result is not None
    assert result["extracted_sections"] == {}
    assert "citation_evidence" not in result
    assert "error_code" not in result


def test_processing_configuration_hides_internal_error_code() -> None:
    configuration_id = uuid4()
    repository = InterviewRepository.__new__(InterviewRepository)
    repository._session = FakeSession(  # type: ignore[assignment]
        {
            "id": configuration_id,
            "setup_id": uuid4(),
            "version_no": 1,
            "status": "processing",
            "document_version_snapshot": {},
            "analysis_ids": [uuid4()],
            "question_count": 3,
            "error_code": None,
        }
    )

    result = repository.get_configuration(uuid4(), configuration_id)

    assert result is not None
    assert "error_code" not in result
    assert result["error"] is None
