from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.core.errors import ApiError
from app.repositories.users import UserRepository
from app.schemas.profile import (
    ConsentStatus,
    LanguageReplaceRequest,
    MeResponse,
    OnboardingStatus,
    ProfileData,
    ProfileReplaceRequest,
    TermsReplaceRequest,
)


class UserService(Protocol):
    def get_me(self, user_id: UUID) -> MeResponse: ...
    def replace_profile(self, user_id: UUID, request: ProfileReplaceRequest) -> MeResponse: ...
    def replace_language(self, user_id: UUID, request: LanguageReplaceRequest) -> MeResponse: ...
    def replace_terms(self, user_id: UUID, request: TermsReplaceRequest) -> MeResponse: ...
    def complete_onboarding(self, user_id: UUID) -> MeResponse: ...


class SqlUserService:
    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    def get_me(self, user_id: UUID) -> MeResponse:
        profile = self._repository.get_profile(user_id)
        if profile is None:
            raise ApiError(404, "PROFILE_NOT_FOUND", "프로필을 찾을 수 없습니다.")
        consent_rows = self._repository.list_active_consents(user_id)
        missing = self._missing_requirements(profile, consent_rows)
        return MeResponse(
            profile=ProfileData(
                display_name=profile["display_name"],
                birth_date=profile["birth_date"],
                gender=profile["gender"],
                native_language=profile["native_language"],
            ),
            display_language=profile["display_language"],
            consents=[
                ConsentStatus(
                    consent_type=row["consent_type"],
                    policy_version=row["policy_version"],
                    accepted=row["accepted"],
                )
                for row in consent_rows
            ],
            onboarding_status=OnboardingStatus(
                completed=bool(profile["onboarding_completed"]) and not missing,
                missing_requirements=missing,
            ),
        )

    def replace_profile(self, user_id: UUID, request: ProfileReplaceRequest) -> MeResponse:
        try:
            self._repository.replace_profile(user_id, request)
            self._repository.commit()
        except LookupError as error:
            raise ApiError(404, "PROFILE_NOT_FOUND", "프로필을 찾을 수 없습니다.") from error
        return self.get_me(user_id)

    def replace_language(self, user_id: UUID, request: LanguageReplaceRequest) -> MeResponse:
        try:
            self._repository.replace_language(user_id, request.display_language)
            self._repository.commit()
        except LookupError as error:
            raise ApiError(404, "PROFILE_NOT_FOUND", "프로필을 찾을 수 없습니다.") from error
        return self.get_me(user_id)

    def replace_terms(self, user_id: UUID, request: TermsReplaceRequest) -> MeResponse:
        try:
            self._repository.replace_terms(user_id, request)
            self._repository.commit()
        except ValueError as error:
            raise ApiError(
                409,
                "CONSENT_POLICY_MISMATCH",
                "현재 동의 정책과 요청이 일치하지 않습니다.",
            ) from error
        return self.get_me(user_id)

    def complete_onboarding(self, user_id: UUID) -> MeResponse:
        current = self.get_me(user_id)
        missing = current.onboarding_status.missing_requirements
        if missing:
            raise ApiError(
                409,
                "ONBOARDING_REQUIREMENTS_MISSING",
                "온보딩 필수 항목이 완료되지 않았습니다.",
                fields={"missing_requirements": missing},
            )
        self._repository.mark_onboarding_complete(user_id)
        self._repository.commit()
        return self.get_me(user_id)

    @staticmethod
    def _missing_requirements(
        profile: dict[str, object],
        consents: list[dict[str, object]],
    ) -> list[str]:
        missing = [
            name
            for name in ("display_name", "birth_date", "gender", "native_language")
            if not profile.get(name)
        ]
        missing.extend(
            f"consent:{row['consent_type']}"
            for row in consents
            if row["is_required"] and not row["accepted"]
        )
        return missing
