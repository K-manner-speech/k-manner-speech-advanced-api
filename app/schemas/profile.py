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


# 주소가 진짜 닿는지는 확인 메일이 판정한다. 여기서는 형태만 거른다.
# 오탈자를 서버까지 보내지 않으려는 것이지 주소를 검증하려는 것이 아니다.
EmailText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$",
    ),
]


class EmailChangeRequest(ContractModel):
    """주소 변경 요청. 확인 메일을 받아야 확정된다."""

    email: EmailText


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
    """무엇이 끝났고 무엇이 남았는지 화면이 그대로 옮겨 적을 수 있게 한다."""

    pending_email: str | None = None


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
