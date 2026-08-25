from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.profile import ProfileReplaceRequest, TermsReplaceRequest


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_profile(self, authenticated_user_id: UUID) -> dict[str, Any] | None:
        row = (
            self._session.execute(
                text(
                    """
                select display_name, birth_date, gender, native_language,
                       display_language, onboarding_completed
                from public.profiles
                where id = :authenticated_user_id
                """
                ),
                {"authenticated_user_id": authenticated_user_id},
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    def replace_profile(
        self,
        authenticated_user_id: UUID,
        request: ProfileReplaceRequest,
    ) -> None:
        result = self._session.execute(
            text(
                """
                update public.profiles
                set display_name = :display_name,
                    birth_date = :birth_date,
                    gender = :gender,
                    native_language = :native_language,
                    updated_at = now()
                where id = :authenticated_user_id
                returning id
                """
            ),
            {"authenticated_user_id": authenticated_user_id, **request.model_dump()},
        )
        if result.scalar_one_or_none() is None:
            raise LookupError("profile not found")

    def replace_language(self, authenticated_user_id: UUID, language: str) -> None:
        result = self._session.execute(
            text(
                """
                update public.profiles
                set display_language = :language, updated_at = now()
                where id = :authenticated_user_id
                returning id
                """
            ),
            {"authenticated_user_id": authenticated_user_id, "language": language},
        )
        if result.scalar_one_or_none() is None:
            raise LookupError("profile not found")

    def list_active_consents(self, authenticated_user_id: UUID) -> list[dict[str, Any]]:
        rows = self._session.execute(
            text(
                """
                select p.consent_type, p.policy_version, p.is_required,
                       (c.id is not null and c.revoked_at is null) as accepted
                from public.consent_policies p
                left join public.user_consents c
                  on c.user_id = :authenticated_user_id
                 and c.consent_type = p.consent_type
                 and c.policy_version = p.policy_version
                where p.is_active = true
                order by p.consent_type, p.effective_at desc
                """
            ),
            {"authenticated_user_id": authenticated_user_id},
        ).mappings()
        return [dict(row) for row in rows]

    def replace_terms(
        self,
        authenticated_user_id: UUID,
        request: TermsReplaceRequest,
    ) -> None:
        active = {
            (row["consent_type"], row["policy_version"])
            for row in self.list_active_consents(authenticated_user_id)
        }
        requested = {(consent.consent_type, consent.policy_version) for consent in request.consents}
        if not requested.issubset(active):
            raise ValueError("inactive consent policy")

        for consent in request.consents:
            self._session.execute(
                text(
                    """
                    insert into public.user_consents
                        (user_id, consent_type, policy_version, accepted_at, revoked_at)
                    values
                        (:authenticated_user_id, :consent_type, :policy_version, now(), null)
                    on conflict (user_id, consent_type, policy_version)
                    do update set accepted_at = now(), revoked_at = null
                    """
                ),
                {
                    "authenticated_user_id": authenticated_user_id,
                    "consent_type": consent.consent_type,
                    "policy_version": consent.policy_version,
                },
            )

    def mark_onboarding_complete(self, authenticated_user_id: UUID) -> None:
        result = self._session.execute(
            text(
                """
                update public.profiles
                set onboarding_completed = true, updated_at = now()
                where id = :authenticated_user_id
                returning id
                """
            ),
            {"authenticated_user_id": authenticated_user_id},
        )
        if result.scalar_one_or_none() is None:
            raise LookupError("profile not found")

    def commit(self) -> None:
        self._session.commit()
