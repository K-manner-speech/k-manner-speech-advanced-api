from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


class CatalogRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_personas(self, limit: int) -> list[dict[str, Any]]:
        rows = self._session.execute(
            text(
                """
                select id, name, role_title, description, avatar_key
                from public.personas
                where is_active = true
                order by sort_order, id
                limit :limit
                """
            ),
            {"limit": limit},
        ).mappings()
        return [dict(row) for row in rows]

    def get_persona(self, persona_id: UUID) -> dict[str, Any] | None:
        row = (
            self._session.execute(
                text(
                    """
                select id, name, role_title, description, avatar_key
                from public.personas
                where id = :persona_id and is_active = true
                """
                ),
                {"persona_id": persona_id},
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    def persona_scenarios(self, persona_id: UUID) -> list[dict[str, Any]]:
        rows = self._session.execute(
            text(
                """
                select ps.scenario_id, ps.relationship_label
                from public.persona_scenarios ps
                join public.scenarios s on s.id = ps.scenario_id and s.is_active = true
                where ps.persona_id = :persona_id
                order by s.sort_order, s.id
                """
            ),
            {"persona_id": persona_id},
        ).mappings()
        return [dict(row) for row in rows]

    def list_scenarios(self, limit: int, persona_id: UUID | None) -> list[dict[str, Any]]:
        rows = self._session.execute(
            text(
                """
                select s.id, s.practice_type, s.title, s.goal, s.location,
                       s.difficulty, s.estimated_minutes
                from public.scenarios s
                where s.is_active = true
                  and (
                    cast(:persona_id as uuid) is null
                    or exists (
                      select 1 from public.persona_scenarios ps
                      where ps.scenario_id = s.id
                        and ps.persona_id = cast(:persona_id as uuid)
                    )
                  )
                order by s.sort_order, s.id
                limit :limit
                """
            ),
            {"persona_id": persona_id, "limit": limit},
        ).mappings()
        return [dict(row) for row in rows]

    def persona_exists(self, persona_id: UUID) -> bool:
        return (
            self._session.execute(
                text("select 1 from public.personas where id = :persona_id and is_active = true"),
                {"persona_id": persona_id},
            ).first()
            is not None
        )

    def get_scenario(self, scenario_id: UUID) -> dict[str, Any] | None:
        row = (
            self._session.execute(
                text(
                    """
                select id, practice_type, title, goal, location, difficulty,
                       estimated_minutes, opening_message, max_turns
                from public.scenarios
                where id = :scenario_id and is_active = true
                """
                ),
                {"scenario_id": scenario_id},
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    def scenario_personas(self, scenario_id: UUID) -> list[dict[str, Any]]:
        rows = self._session.execute(
            text(
                """
                select ps.persona_id, ps.relationship_label
                from public.persona_scenarios ps
                join public.personas p on p.id = ps.persona_id and p.is_active = true
                where ps.scenario_id = :scenario_id
                -- 시나리오가 정한 순서를 먼저 따른다. 화면은 첫 상대를 기본으로 쓴다.
                order by coalesce(ps.sort_order, 100), p.sort_order, p.id
                """
            ),
            {"scenario_id": scenario_id},
        ).mappings()
        return [dict(row) for row in rows]

    def scenario_conditions(self, scenario_id: UUID) -> list[dict[str, Any]]:
        rows = self._session.execute(
            text(
                """
                select condition_key, description, sort_order
                from public.scenario_success_conditions
                where scenario_id = :scenario_id and is_required = true
                order by sort_order, id
                """
            ),
            {"scenario_id": scenario_id},
        ).mappings()
        return [dict(row) for row in rows]
