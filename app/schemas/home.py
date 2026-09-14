from datetime import date
from uuid import UUID

from pydantic import Field

from app.schemas.base import ContractModel

# 진행 바가 7칸이고 "7일 목표" 로 표시된다.
STREAK_GOAL_DAYS = 7

# 연속 일수는 목표 창보다 길 수 있다. 1년을 넘겨 이어 온 사람은 그 자체로
# 드물고, 한 행이 하루이므로 이 창을 읽는 값은 저렴하다.
STREAK_WINDOW_DAYS = 366


class LearningStreak(ContractModel):
    """홈 상단의 연속 학습 상태.

    `streak_days` 는 오늘까지 이어진 연속 출석 일수다. 오늘 아직 출석하지
    않았어도 어제까지 이어졌다면 그 값을 유지한다. 하루가 다 가기 전에는
    기록이 끊긴 것으로 보지 않는다.
    `goal_days` 중 `recent_days` 는 최근 7일 안에서 출석한 날 수이며, 하루를
    빠뜨렸다고 0 으로 되돌리지 않는다.
    """

    attended_today: bool
    streak_days: int = Field(ge=0)
    recent_days: int = Field(ge=0, le=STREAK_GOAL_DAYS)
    goal_days: int = Field(ge=1)
    today: date


class RecommendedPractice(ContractModel):
    """오늘의 추천 대화. 하루 동안 같은 것을 보여 준다."""

    scenario_id: UUID
    title: str
    goal: str | None
    difficulty: str | None
    estimated_minutes: int | None
    persona_id: UUID | None
    persona_name: str | None
    persona_avatar_key: str | None = None
    relationship_label: str | None
    opening_message: str | None
    completed_before: bool


class HomeSummary(ContractModel):
    streak: LearningStreak
    recommendation: RecommendedPractice | None
