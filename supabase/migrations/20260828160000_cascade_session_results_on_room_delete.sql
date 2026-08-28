-- 대화방을 삭제하면 그 방에서 나온 연습 결과도 함께 정리되도록 한다.
--
-- 지금까지 session_results.room_id는 ON DELETE SET NULL이라 방이 사라져도 결과가
-- 남았다. 그런데 result_items.original_expression에는 사용자가 실제로 한 문장이
-- 그대로 저장되므로, 대화 기록을 지워도 발화는 다른 테이블에 남는 상태였다.
-- 삭제 확인 문구가 약속하는 "복구할 수 없습니다"와도 어긋난다.
--
-- 남겨진 결과는 방 기준 조회(get_room_result)가 practice_rooms를 조인하기 때문에
-- 원래 대화와의 연결이 끊겨, 무슨 연습이었는지 추적할 수 없는 상태로만 남았다.
--
-- result_items, interview_evaluation_scores, processing_jobs는 이미
-- session_results에 CASCADE로 매달려 있어 함께 정리된다.

alter table public.session_results
drop constraint session_results_room_id_fkey;

alter table public.session_results
add constraint session_results_room_id_fkey
foreign key (room_id) references public.practice_rooms(id) on delete cascade;
