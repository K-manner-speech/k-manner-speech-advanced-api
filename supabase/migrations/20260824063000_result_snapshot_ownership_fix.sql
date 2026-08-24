begin;

-- A result is an independent snapshot and must remain addressable after its room is deleted.
alter table public.session_results
  alter column room_id drop not null;

-- Existing rows were backfilled by the preceding migration. Enforce ownership on future rows
-- when the table contains no unresolved legacy ownership.
do $$
begin
  if not exists (select 1 from public.session_results where user_id is null) then
    alter table public.session_results alter column user_id set not null;
  end if;
end $$;

drop policy if exists session_results_own_room on public.session_results;
drop policy if exists session_results_own_user on public.session_results;
create policy session_results_own_user
  on public.session_results
  for all
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- Result items follow the independent result owner, not the possibly deleted room.
drop policy if exists result_items_own_result on public.result_items;
drop policy if exists result_items_own_user_result on public.result_items;
create policy result_items_own_user_result
  on public.result_items
  for all
  to authenticated
  using (
    exists (
      select 1
      from public.session_results r
      where r.id = result_id and r.user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1
      from public.session_results r
      where r.id = result_id and r.user_id = auth.uid()
    )
  );

commit;
