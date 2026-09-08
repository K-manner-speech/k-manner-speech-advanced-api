from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app.adapters.account_auth import SupabaseAccountAuthGateway
from app.adapters.storage import SupabaseStorageSigner
from app.core.auth import (
    AuthenticatedUser,
    get_account_deletion_user,
    get_authenticated_user,
)
from app.core.config import AppSettings
from app.core.dependencies import get_session, get_settings
from app.repositories.account import AccountDeletionRepository
from app.repositories.users import UserRepository
from app.schemas.profile import (
    CredentialChangeResponse,
    EmailChangeRequest,
    LanguageReplaceRequest,
    MeResponse,
    PasswordChangeRequest,
    ProfileReplaceRequest,
    TermsReplaceRequest,
)
from app.services.account import AccountDeletionService, SqlAccountDeletionService
from app.services.credentials import CredentialService, SupabaseCredentialService
from app.services.idempotency import IdempotencyRepository
from app.services.users import SqlUserService, UserService

router = APIRouter(tags=["user"])


def get_user_service(session: Annotated[Session, Depends(get_session)]) -> UserService:
    return SqlUserService(UserRepository(session))


def get_account_deletion_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> AccountDeletionService:
    service_role_key = settings.supabase_service_role_key.get_secret_value()
    return SqlAccountDeletionService(
        AccountDeletionRepository(session),
        SupabaseStorageSigner(settings.supabase_url, service_role_key),
        SupabaseAccountAuthGateway(settings.supabase_url, service_role_key),
        IdempotencyRepository(session),
        settings.idempotency_lease_seconds,
        settings.idempotency_retention_seconds,
    )


def get_credential_service(
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> CredentialService:
    return SupabaseCredentialService(
        SupabaseAccountAuthGateway(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
    )


@router.get("/me", operation_id="me.get", response_model=MeResponse)
def get_me(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> MeResponse:
    return service.get_me(user.id)


@router.put("/me/profile", operation_id="me_profile.replace", response_model=MeResponse)
def replace_profile(
    request: ProfileReplaceRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> MeResponse:
    return service.replace_profile(user.id, request)


@router.put("/me/language", operation_id="me_language.replace", response_model=MeResponse)
def replace_language(
    request: LanguageReplaceRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> MeResponse:
    return service.replace_language(user.id, request)


@router.put("/me/terms", operation_id="me_terms.replace", response_model=MeResponse)
def replace_terms(
    request: TermsReplaceRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> MeResponse:
    return service.replace_terms(user.id, request)


@router.post(
    "/me/onboarding/complete",
    operation_id="onboarding.complete",
    response_model=MeResponse,
)
def complete_onboarding(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[UserService, Depends(get_user_service)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> MeResponse:
    del idempotency_key
    return service.complete_onboarding(user.id)


@router.delete("/me", operation_id="account.delete", status_code=204)
def delete_account(
    user: Annotated[AuthenticatedUser, Depends(get_account_deletion_user)],
    service: Annotated[
        AccountDeletionService, Depends(get_account_deletion_service)
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> Response:
    service.delete_account(user.id, user.access_token, idempotency_key)
    return Response(status_code=204)


@router.put(
    "/me/email",
    operation_id="me_email.change",
    response_model=CredentialChangeResponse,
)
def change_email(
    request: EmailChangeRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[CredentialService, Depends(get_credential_service)],
) -> CredentialChangeResponse:
    """주소 변경을 요청한다.

    응답이 200 이어도 아직 바뀌지 않았다. 새 주소로 간 확인 링크를 눌러야
    확정된다. 확인 없이 바꾸면 오타 하나로 계정에 다시 들어올 수 없다.
    """
    return service.change_email(user.access_token, request)


@router.put(
    "/me/password",
    operation_id="me_password.change",
    response_model=CredentialChangeResponse,
)
def change_password(
    request: PasswordChangeRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[CredentialService, Depends(get_credential_service)],
) -> CredentialChangeResponse:
    """현재 비밀번호를 확인한 뒤 바꾼다. 세션만으로는 바꾸지 않는다."""
    return service.change_password(user.access_token, request)
