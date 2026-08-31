"""가장 최근 대화방의 피드백이 맥락을 반영했는지 확인한다.

사용법:
    uv run python scripts/feedback_check.py            # 가장 최근 방
    uv run python scripts/feedback_check.py <room_id>  # 특정 방

브라우저에서 대화를 끝낸 뒤 실행해 턴별 피드백과 종합 결과를 함께 본다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.core.dependencies import get_engine  # noqa: E402


def main() -> None:
    room_id = sys.argv[1] if len(sys.argv) > 1 else None
    with get_engine().connect() as connection:
        if room_id is None:
            room_id = str(
                connection.execute(
                    text("select id from public.practice_rooms order by started_at desc limit 1")
                ).scalar_one()
            )
        room = connection.execute(
            text(
                """
                select r.title, r.practice_type, r.goal_snapshot, r.status,
                       p.name as persona_name, ps.role_key
                from public.practice_rooms r
                left join public.personas p on p.id = r.persona_id
                left join public.persona_scenarios ps
                  on ps.persona_id = r.persona_id and ps.scenario_id = r.scenario_id
                where r.id = :room_id
                """
            ),
            {"room_id": room_id},
        ).mappings().one()

        print(f"방  : {room['title']} ({room['practice_type']}, {room['status']})")
        print(f"상대: {room['persona_name']} / 관계 {room['role_key']}")
        print(f"목표: {room['goal_snapshot']}")

        conditions = list(
            connection.execute(
                text(
                    """
                    select sc.condition_key, sc.description
                    from public.scenario_success_conditions sc
                    join public.practice_rooms r on r.scenario_id = sc.scenario_id
                    where r.id = :room_id
                    order by sc.sort_order
                    """
                ),
                {"room_id": room_id},
            )
        )
        if conditions:
            print("성공 조건:")
            for key, description in conditions:
                print(f"  - {key}: {description}")

        print()
        print("=" * 70)
        print("턴별 피드백")
        print("=" * 70)
        for message in connection.execute(
            text(
                """
                select m.sequence_no, m.sender_type, m.content,
                       f.id as feedback_id, f.overall_score, f.summary, f.analysis_status
                from public.room_messages m
                left join public.turn_feedback f on f.message_id = m.id
                where m.room_id = :room_id
                order by m.sequence_no
                """
            ),
            {"room_id": room_id},
        ).mappings():
            who = "나" if message["sender_type"] == "user" else "상대"
            print(f"\n#{message['sequence_no']} [{who}] {message['content'][:64]}")
            if message["feedback_id"] is None:
                continue
            if message["analysis_status"] != "ready":
                print(f"     피드백 {message['analysis_status']}")
                continue
            print(f"     {message['overall_score']}점 · {message['summary']}")
            for score in connection.execute(
                text(
                    """
                    select category, score, max_score, strength_text, suggestion_text
                    from public.feedback_scores where feedback_id = :feedback_id
                    order by category
                    """
                ),
                {"feedback_id": message["feedback_id"]},
            ):
                print(f"       {score[0]:<16} {score[1]}/{score[2]}")
                if score[3]:
                    print(f"          강점 {score[3]}")
                if score[4]:
                    print(f"          개선 {score[4]}")

        print()
        print("=" * 70)
        print("종합 결과")
        print("=" * 70)
        result = connection.execute(
            text(
                """
                select id, result_status, overall_score, summary
                from public.session_results
                where room_id = :room_id order by attempt_no desc limit 1
                """
            ),
            {"room_id": room_id},
        ).mappings().one_or_none()
        if result is None:
            print("  아직 생성되지 않음 (대화를 끝내고 결과 보기까지 진행하세요)")
            return
        print(f"  상태 {result['result_status']} · 총점 {result['overall_score']}")
        print(f"  총평 {result['summary']}")
        for item in connection.execute(
            text(
                """
                select item_type, category, title, original_expression,
                       recommended_expression, explanation, evidence_text
                from public.result_items where result_id = :result_id
                order by sort_order
                """
            ),
            {"result_id": result["id"]},
        ).mappings():
            print(f"\n  [{item['item_type']}] {item['title']}")
            for label, value in (
                ("분류", item["category"]),
                ("사용자 표현", item["original_expression"]),
                ("추천 표현", item["recommended_expression"]),
                ("설명", item["explanation"]),
                ("근거", item["evidence_text"]),
            ):
                if value:
                    print(f"     {label}: {value}")
        for score in connection.execute(
            text(
                """
                select category, score, strength_text, suggestion_text, evidence_text
                from public.interview_evaluation_scores
                where result_id = :result_id order by category
                """
            ),
            {"result_id": result["id"]},
        ):
            print(f"\n  [면접 {score[0]}] {score[1]}점")
            for label, value in (("강점", score[2]), ("개선", score[3]), ("근거", score[4])):
                if value:
                    print(f"     {label}: {value}")


if __name__ == "__main__":
    main()
