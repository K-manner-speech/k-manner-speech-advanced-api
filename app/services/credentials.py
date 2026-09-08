from __future__ import annotations

from typing import Protocol

from app.adapters.account_auth import (
    AccountAuthGateway,
    AuthGatewayUnavailable,
    AuthReconfirmationError,
    EmailAlreadyUsedError,
    WrongPasswordError,
)
from app.core.errors import ApiError
from app.schemas.profile import (
    CredentialChangeResponse,
    EmailChangeRequest,
    PasswordChangeRequest,
)


class CredentialService(Protocol):
    def change_email(
        self, access_token: str, request: EmailChangeRequest
    ) -> CredentialChangeResponse: ...

    def change_password(
        self, access_token: str, request: PasswordChangeRequest
    ) -> CredentialChangeResponse: ...


class SupabaseCredentialService:
    """로그인 정보는 우리 표가 아니라 Supabase Auth 에 있다.

    여기서는 실패를 화면이 그대로 옮겨 적을 수 있는 코드로 옮기는 일만 한다.
    """

    def __init__(self, gateway: AccountAuthGateway) -> None:
        self._gateway = gateway

    def change_email(
        self, access_token: str, request: EmailChangeRequest
    ) -> CredentialChangeResponse:
        try:
            self._gateway.change_email(access_token, request.email)
        except EmailAlreadyUsedError as error:
            raise ApiError(
                409,
                "EMAIL_ALREADY_USED",
                "이미 사용 중인 이메일입니다. 다른 주소를 입력해 주세요.",
            ) from error
        except AuthReconfirmationError as error:
            raise ApiError(
                401, "SESSION_EXPIRED", "다시 로그인한 뒤 시도해 주세요."
            ) from error
        except AuthGatewayUnavailable as error:
            raise ApiError(
                503,
                "AUTH_UNAVAILABLE",
                "인증 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
                retryable=True,
            ) from error
        # 아직 바뀌지 않았다. 새 주소로 간 확인 링크를 눌러야 확정된다.
        return CredentialChangeResponse(pending_email=request.email)

    def change_password(
        self, access_token: str, request: PasswordChangeRequest
    ) -> CredentialChangeResponse:
        try:
            self._gateway.change_password(
                access_token, request.current_password, request.new_password
            )
        except WrongPasswordError as error:
            raise ApiError(
                400, "WRONG_PASSWORD", "현재 비밀번호가 일치하지 않습니다."
            ) from error
        except AuthReconfirmationError as error:
            raise ApiError(
                401, "SESSION_EXPIRED", "다시 로그인한 뒤 시도해 주세요."
            ) from error
        except AuthGatewayUnavailable as error:
            raise ApiError(
                503,
                "AUTH_UNAVAILABLE",
                "인증 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
                retryable=True,
            ) from error
        return CredentialChangeResponse()
