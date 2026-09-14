from fastapi import FastAPI
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware

from app.core.auth import (
    JwksTokenVerifier,
    SessionValidator,
    TokenVerifier,
    UnconfiguredSessionValidator,
    UnconfiguredTokenVerifier,
    get_session_validator,
    get_token_verifier,
)
from app.core.config import AppSettings
from app.core.dependencies import ApplicationReadinessChecker
from app.core.errors import install_error_handlers
from app.core.readiness import ReadinessChecker
from app.routers import (
    catalog,
    conversation,
    feedback,
    health,
    home,
    interviews,
    media,
    results,
    users,
)


def create_app(
    readiness_checker: ReadinessChecker | None = None,
    token_verifier: TokenVerifier | None = None,
    session_validator: SessionValidator | None = None,
    settings: AppSettings | None = None,
) -> FastAPI:
    application = FastAPI(title="K-Manner Speech API", version="0.1.0")
    if settings is not None:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
            allow_credentials=False,
        )
    install_error_handlers(application)
    application.include_router(health.router, prefix="/api/v1")
    application.include_router(users.router, prefix="/api/v1")
    application.include_router(catalog.router, prefix="/api/v1")
    application.include_router(home.router, prefix="/api/v1")
    application.include_router(conversation.router, prefix="/api/v1")
    application.include_router(feedback.router, prefix="/api/v1")
    application.include_router(media.router, prefix="/api/v1")
    application.include_router(results.router, prefix="/api/v1")
    application.include_router(interviews.router, prefix="/api/v1")
    application.dependency_overrides[health.get_readiness_checker] = lambda: (
        readiness_checker or ApplicationReadinessChecker()
    )
    configured_verifier: TokenVerifier
    if token_verifier is not None:
        configured_verifier = token_verifier
    elif settings is not None:
        configured_verifier = JwksTokenVerifier(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json",
            settings.supabase_jwt_issuer,
            settings.supabase_jwt_audience,
            settings.jwt_leeway_seconds,
        )
    else:
        configured_verifier = UnconfiguredTokenVerifier()
    application.dependency_overrides[get_token_verifier] = lambda: configured_verifier
    if session_validator is not None:
        application.dependency_overrides[get_session_validator] = lambda: session_validator
    elif settings is None:
        unconfigured_session_validator = UnconfiguredSessionValidator()
        application.dependency_overrides[get_session_validator] = (
            lambda: unconfigured_session_validator
        )
    return application


_startup_settings: AppSettings | None
try:
    _startup_settings = AppSettings()
except ValidationError:
    _startup_settings = None

app = create_app(settings=_startup_settings)
