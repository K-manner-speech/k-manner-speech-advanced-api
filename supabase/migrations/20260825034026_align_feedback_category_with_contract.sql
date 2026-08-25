-- ERD/API/UI contract key: 예의와 배려 = courtesy.
update public.feedback_scores
set category = 'courtesy'
where category = 'consideration';

alter table public.feedback_scores
  drop constraint feedback_scores_category_check,
  drop constraint feedback_scores_score_contract,
  add constraint feedback_scores_category_check check (
    category in ('honorifics', 'courtesy', 'context_fit', 'naturalness')
  ),
  add constraint feedback_scores_score_contract check (
    category in ('honorifics', 'courtesy', 'context_fit', 'naturalness')
    and score between 0 and 25
    and score = trunc(score)
    and max_score = 25
  );

create or replace function public.recalculate_turn_feedback_overall_score()
returns trigger
language plpgsql
set search_path = public
as $function$
declare
  target_feedback_id uuid;
  category_count integer;
  total_score numeric;
begin
  target_feedback_id := coalesce(new.feedback_id, old.feedback_id);

  select count(distinct category), sum(score)
    into category_count, total_score
  from public.feedback_scores
  where feedback_id = target_feedback_id
    and category in ('honorifics', 'courtesy', 'context_fit', 'naturalness');

  update public.turn_feedback
  set overall_score = case when category_count = 4 then total_score else null end,
      updated_at = now()
  where id = target_feedback_id;

  return coalesce(new, old);
end;
$function$;
