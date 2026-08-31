alter table public.idempotency_records
  drop constraint idempotency_records_action_scope_check;

alter table public.idempotency_records
  add constraint idempotency_records_action_scope_check
  check (
    action_scope = any (
      array[
        'room.create'::text,
        'room.delete'::text,
        'room_message.create'::text,
        'room_voice_message.create'::text,
        'message_response.retry'::text,
        'message_feedback.retry'::text,
        'message_emotion.retry'::text,
        'message_tts.retry'::text,
        'message_repeat.create'::text,
        'room_result.retry'::text,
        'result.delete'::text,
        'interview_setup.create'::text,
        'interview_document.create'::text,
        'interview_document.analyze'::text,
        'interview_document.replace'::text,
        'interview_document.delete'::text,
        'interview_configuration.generate'::text,
        'interview_configuration.regenerate'::text,
        'interview_practice_room.create'::text,
        'onboarding.complete'::text,
        'account.delete'::text
      ]
    )
  );
