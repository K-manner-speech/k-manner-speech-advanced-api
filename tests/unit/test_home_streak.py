"""홈의 연속 학습 계산 규칙을 지킨다."""

from __future__ import annotations

from datetime import date, timedelta
from typing import cast
from uuid import uuid4

from app.repositories.home import HomeRepository
from app.services.home import SqlHomeService, count_streak

TODAY = date(2026, 9, 8)


def days_ago(*offsets: int) -> list[date]:
    return [TODAY - timedelta(days=offset) for offset in offsets]


def test_counts_consecutive_days_ending_today() -> None:
    assert count_streak(days_ago(0, 1, 2), TODAY) == 3


def test_yesterday_streak_survives_until_the_day_ends() -> None:
    """오늘 아직 안 눌렀다고 어제까지의 기록을 0 으로 만들지 않는다."""
    assert count_streak(days_ago(1, 2, 3), TODAY) == 3


def test_a_missed_day_breaks_the_streak() -> None:
    # 어제를 빠뜨렸으므로 그제까지의 기록은 이어지지 않는다.
    assert count_streak(days_ago(0, 2, 3), TODAY) == 1
    assert count_streak(days_ago(2, 3), TODAY) == 0


def test_no_attendance_is_zero() -> None:
    assert count_streak([], TODAY) == 0


def test_duplicate_or_unordered_dates_do_not_inflate_the_streak() -> None:
    assert count_streak(days_ago(1, 0, 1, 2), TODAY) == 3


class FakeRepository:
    """출석 일수만 흉내 낸다. 추천은 이 테스트의 관심이 아니다."""

    def __init__(self, attended: list[date]) -> None:
        self.attended = attended
        self.requested_days = 0

    def today(self) -> date:
        return TODAY

    def attendance_dates(self, user_id: object, days: int) -> list[date]:
        self.requested_days = days
        return self.attended

    def recommend_scenario(self, user_id: object) -> None:
        return None


def test_streak_is_not_capped_by_the_seven_day_goal() -> None:
    """30일을 이어 온 사람에게 7일이라고 말하지 않는다."""
    repository = FakeRepository(days_ago(*range(30)))
    summary = SqlHomeService(cast(HomeRepository, repository)).summary(uuid4())

    assert summary.streak.streak_days == 30
    # 진행 바는 7칸이므로 그 창을 넘겨 세지 않는다.
    assert summary.streak.recent_days == 7
    assert repository.requested_days > 7


def test_recent_days_counts_only_the_last_seven_days() -> None:
    repository = FakeRepository(days_ago(0, 1, 8, 20))
    summary = SqlHomeService(cast(HomeRepository, repository)).summary(uuid4())

    assert summary.streak.recent_days == 2
    assert summary.streak.streak_days == 2
