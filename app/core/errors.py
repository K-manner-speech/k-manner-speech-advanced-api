from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.common import ErrorEnvelope, FieldError


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        fields: dict[str, Any] | None = None,
        field_errors: list[FieldError] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields or {}
        self.field_errors = field_errors or []
        self.retryable = retryable


def install_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        field_errors = [
            FieldError(
                field=".".join(str(part) for part in item["loc"]),
                code=str(item["type"]),
            )
            for item in error.errors()
        ]
        envelope = ErrorEnvelope(
            code="VALIDATION_ERROR",
            message="요청 형식이 올바르지 않습니다.",
            field_errors=field_errors,
            request_id=uuid4(),
            retryable=False,
        )
        return JSONResponse(status_code=422, content=envelope.model_dump(mode="json"))

    @application.exception_handler(ApiError)
    async def handle_api_error(_request: Request, error: ApiError) -> JSONResponse:
        envelope = ErrorEnvelope(
            code=error.code,
            message=error.message,
            fields=error.fields,
            field_errors=error.field_errors,
            request_id=uuid4(),
            retryable=error.retryable,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=envelope.model_dump(mode="json"),
        )
