"""홈의 연속 학습 계산 규칙을 지킨다."""

from __future__ import annotations

from datetime import date, timedelta

from app.services.home import count_streak

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
