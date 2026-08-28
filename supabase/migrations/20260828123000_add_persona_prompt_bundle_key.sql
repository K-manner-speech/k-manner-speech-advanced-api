alter table public.personas
add column prompt_bundle_key text;

alter table public.personas
add constraint personas_prompt_bundle_key_format
check (
  prompt_bundle_key is null
  or prompt_bundle_key ~ '^[a-z0-9_-]+$'
);

comment on column public.personas.prompt_bundle_key is
'app/ai/prompts/catalog/bundles/personas 아래 YAML bundle의 확장자 없는 파일명';
