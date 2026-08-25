from datetime import date
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from app.schemas.base import ContractModel


class LanguageReplaceRequest(ContractModel):
    display_language: Literal["ko", "en"]


NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ProfileReplaceRequest(ContractModel):
    display_name: NonBlankText
    birth_date: date
    gender: NonBlankText
    native_language: NonBlankText

    @field_validator("birth_date")
    @classmethod
    def birth_date_must_not_be_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("birth_date cannot be in the future")
        return value


class ConsentInput(ContractModel):
    consent_type: NonBlankText
    policy_version: NonBlankText
    accepted: Literal[True]


class TermsReplaceRequest(ContractModel):
    consents: list[ConsentInput] = Field(min_length=1)


class ProfileData(ContractModel):
    display_name: str | None
    birth_date: date | None
    gender: str | None
    native_language: str | None


class ConsentStatus(ContractModel):
    consent_type: str
    policy_version: str
    accepted: bool


class OnboardingStatus(ContractModel):
    completed: bool
    missing_requirements: list[str]


class MeResponse(ContractModel):
    profile: ProfileData
    display_language: Literal["ko", "en"]
    consents: list[ConsentStatus]
    onboarding_status: OnboardingStatus


OnboardingMutationResponse = MeResponse
