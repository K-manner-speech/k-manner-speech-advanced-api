from __future__ import annotations

from datetime import date, timedelta
from typing import Protocol
from uuid import UUID

from app.repositories.home import HomeRepository
from app.schemas.home import (
    STREAK_GOAL_DAYS,
    HomeSummary,
    LearningStreak,
    RecommendedPractice,
)


def count_streak(attended: list[date], today: date) -> int:
    """오늘 또는 어제부터 하루도 빠짐없이 이어진 날 수를 센다.

    오늘 아직 출석하지 않았어도 어제까지 이어졌다면 그 기록을 살려 둔다.
    하루가 다 가기 전에 끊긴 것으로 보이면 사용자는 이미 늦었다고 느낀다.
    """
    days = set(attended)
    cursor = today if today in days else today - timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


class HomeService(Protocol):
    def summary(self, user_id: UUID) -> HomeSummary: ...

    def attend(self, user_id: UUID) -> HomeSummary: ...


class SqlHomeService:
    def __init__(self, repository: HomeRepository) -> None:
        self._repository = repository

    def summary(self, user_id: UUID) -> HomeSummary:
        today = self._repository.today()
        attended = self._repository.attendance_dates(user_id, STREAK_GOAL_DAYS)
        recommended = self._repository.recommend_scenario(user_id)
        return HomeSummary(
            streak=LearningStreak(
                attended_today=today in set(attended),
                streak_days=count_streak(attended, today),
                recent_days=len(attended),
                goal_days=STREAK_GOAL_DAYS,
                today=today,
            ),
            recommendation=(
                RecommendedPractice.model_validate(recommended)
                if recommended is not None
                else None
            ),
        )

    def attend(self, user_id: UUID) -> HomeSummary:
        self._repository.mark_attendance(user_id)
        return self.summary(user_id)
