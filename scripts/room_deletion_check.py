"""대화방 삭제가 관련 데이터를 전부 정리하는지 확인한다.

사용법:
    uv run python scripts/room_deletion_check.py            # 현재 상태 요약
    uv run python scripts/room_deletion_check.py <room_id>  # 특정 방 기준 상세

방을 지우기 전에 한 번, 지운 뒤에 한 번 실행해 숫자를 비교한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.core.dependencies import get_engine  # noqa: E402

TOTALS = {
    "practice_rooms": "select count(*) from public.practice_rooms",
    "room_messages": "select count(*) from public.room_messages",
    "message_audio": "select count(*) from public.message_audio",
    "room_contexts": "select count(*) from public.room_contexts",
    "session_results": "select count(*) from public.session_results",
    "result_items": "select count(*) from public.result_items",
    "storage.objects": (
        "select count(*) from storage.objects where bucket_id = 'message-audio'"
    ),
}

ORPHANS = {
    "방이 없는 연습 결과": "select count(*) from public.session_results where room_id is null",
    "DB 레코드 없는 음성 파일": """
        select count(*) from storage.objects o
        where o.bucket_id = 'message-audio'
          and not exists (
            select 1 from public.message_audio a where a.storage_path = o.name
          )
    """,
    "파일 없는 음성 레코드": """
        select count(*) from public.message_audio a
        where not exists (
          select 1 from storage.objects o
          where o.bucket_id = 'message-audio' and o.name = a.storage_path
        )
    """,
}

PER_ROOM = {
    "메시지": "select count(*) from public.room_messages where room_id = :room_id",
    "음성 레코드": """
        select count(*) from public.message_audio a
        join public.room_messages m on m.id = a.message_id
        where m.room_id = :room_id
    """,
    "대화 요약": "select count(*) from public.room_contexts where room_id = :room_id",
    "연습 결과": "select count(*) from public.session_results where room_id = :room_id",
    "결과 항목": """
        select count(*) from public.result_items i
        join public.session_results s on s.id = i.result_id
        where s.room_id = :room_id
    """,
    "면접 답변": "select count(*) from public.interview_answers where room_id = :room_id",
    "성공 조건 진행": (
        "select count(*) from public.room_success_condition_progress where room_id = :room_id"
    ),
}


def main() -> None:
    room_id = sys.argv[1] if len(sys.argv) > 1 else None
    with get_engine().connect() as connection:
        if room_id:
            owner = connection.execute(
                text("select user_id from public.practice_rooms where id = :room_id"),
                {"room_id": room_id},
            ).scalar_one_or_none()
            print(f"=== 방 {room_id} ===")
            print(f"  방 자체: {'있음' if owner else '없음 (삭제됨)'}")
            for label, query in PER_ROOM.items():
                count = connection.execute(text(query), {"room_id": room_id}).scalar_one()
                print(f"  {label:<16} {count}건")
            if owner:
                files = connection.execute(
                    text(
                        """
                        select count(*) from storage.objects
                        where bucket_id = 'message-audio' and name like :prefix
                        """
                    ),
                    {"prefix": f"{owner}/{room_id}/%"},
                ).scalar_one()
                print(f"  {'음성 파일':<16} {files}개")
            print()

        print("=== 전체 건수 ===")
        for label, query in TOTALS.items():
            print(f"  {label:<18} {connection.execute(text(query)).scalar_one()}")

        print()
        print("=== 고아 데이터 (모두 0이어야 정상) ===")
        for label, query in ORPHANS.items():
            count = connection.execute(text(query)).scalar_one()
            print(f"  {'OK  ' if count == 0 else 'FAIL'} {label:<26} {count}")


if __name__ == "__main__":
    main()
