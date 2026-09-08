from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# 하루 경계는 사용자가 체감하는 날짜여야 한다. profiles 에 시간대가 없어
# 지금은 고정한다. 클라이언트가 보낸 날짜는 조작할 수 있어 쓰지 않는다.
LOCAL_TIMEZONE = "Asia/Seoul"


class HomeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def today(self) -> Any:
        return self._session.execute(
            text("select (now() at time zone :zone)::date"), {"zone": LOCAL_TIMEZONE}
        ).scalar_one()

    def mark_attendance(self, user_id: UUID) -> None:
        """오늘 출석을 기록한다. 여러 번 눌러도 하루에 한 행이다."""
        self._session.execute(
            text(
                """
                insert into public.daily_attendances (user_id, attended_on)
                values (:user_id, (now() at time zone :zone)::date)
                on conflict (user_id, attended_on) do nothing
                """
            ),
            {"user_id": user_id, "zone": LOCAL_TIMEZONE},
        )

    def attendance_dates(self, user_id: UUID, days: int) -> list[Any]:
        """최근 며칠간 출석한 날짜를 최신순으로 돌려준다.

        연속 일수는 7일 창보다 길어질 수 있으므로 호출하는 쪽이 창을 정한다.
        """
        rows = self._session.execute(
            text(
                """
                select attended_on
                from public.daily_attendances
                where user_id = :user_id
                  and attended_on > (now() at time zone :zone)::date - :days
                order by attended_on desc
                """
            ),
            {"user_id": user_id, "zone": LOCAL_TIMEZONE, "days": days},
        ).scalars()
        return list(rows)

    def recommend_scenario(self, user_id: UUID) -> dict[str, Any] | None:
        """아직 끝내지 않은 시나리오를 먼저 권한다.

        같은 날에는 새로고침해도 같은 것이 나와야 하므로 사용자와 날짜로
        정렬 순서를 고정한다. 모두 해본 사용자에게는 빈 카드 대신 그중 하나를
        다시 권한다.
        """
        row = (
            self._session.execute(
                text(
                    """
                    with completed as (
                        select distinct scenario_id
                        from public.practice_rooms
                        where user_id = :user_id and status = 'completed'
                          and scenario_id is not null
                    )
                    select s.id as scenario_id, s.title, s.goal, s.difficulty,
                           s.estimated_minutes, s.opening_message,
                           p.id as persona_id, p.name as persona_name,
                           ps.relationship_label,
                           (c.scenario_id is not null) as completed_before
                    from public.scenarios s
                    left join completed c on c.scenario_id = s.id
                    left join lateral (
                        select persona_id, relationship_label
                        from public.persona_scenarios
                        where scenario_id = s.id
                        order by persona_id
                        limit 1
                    ) ps on true
                    left join public.personas p on p.id = ps.persona_id
                    where s.is_active and s.practice_type = 'scenario'
                    order by (c.scenario_id is not null),
                             md5(:user_id || (now() at time zone :zone)::date::text
                                 || s.id::text)
                    limit 1
                    """
                ),
                {"user_id": str(user_id), "zone": LOCAL_TIMEZONE},
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None
