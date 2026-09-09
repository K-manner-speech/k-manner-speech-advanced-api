from datetime import date
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

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


class PasswordChangeRequest(ContractModel):
    """비밀번호 변경. 세션만으로는 바꿀 수 없고 현재 비밀번호를 확인한다."""

    current_password: Annotated[str, StringConstraints(min_length=1)]
    new_password: Annotated[str, StringConstraints(min_length=8, max_length=72)]

    @model_validator(mode="after")
    def new_password_must_differ(self) -> "PasswordChangeRequest":
        if self.current_password == self.new_password:
            raise ValueError("new_password must differ from current_password")
        return self


class CredentialChangeResponse(ContractModel):
    """바꾸기가 끝났음을 알린다. 지금은 비밀번호 변경만 이 응답을 쓴다."""

    changed: bool = True


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
