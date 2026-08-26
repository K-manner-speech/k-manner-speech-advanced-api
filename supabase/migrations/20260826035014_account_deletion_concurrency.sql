create unique index idempotency_account_delete_active_user_idx
  on public.idempotency_records (user_id)
  where action_scope = 'account.delete' and state = 'in_progress';
