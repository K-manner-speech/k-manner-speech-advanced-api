update public.consent_policies
set is_active = false
where consent_type in ('terms', 'privacy')
  and policy_version <> 'v1'
  and is_active = true;

insert into public.consent_policies
  (consent_type, policy_version, is_required, is_active)
values
  ('terms', 'v1', true, true),
  ('privacy', 'v1', true, true)
on conflict (consent_type, policy_version)
do update set
  is_required = excluded.is_required,
  is_active = excluded.is_active;
