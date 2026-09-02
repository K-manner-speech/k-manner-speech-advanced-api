# Runtime YAML prompt catalog

This catalog contains curated persona and conversation fragments imported from
`kt-cloud-tech-up-gen-ai/k-manner-speech-api/app/prompts`.

- `bundles/base_chat.yaml` selects common rules and style.
- `bundles/personas/*.yaml` selects identity, personality, and profile fragments.
- `modes/interview.yaml` is intentionally excluded. Interview progression and completion are
  controlled by `app/ai/prompts/policies/conversation.py`.
- `scenarios/` is intentionally excluded. Supabase scenario rows are the runtime source of truth.
- Session-result evaluation is split by practice type:
  `tasks/session_result_free_chat.yaml`, `tasks/session_result_scenario.yaml`, and
  `tasks/session_result_interview.yaml`. Do not merge their scoring domains into one prompt.
- A persona selects a bundle through `public.personas.prompt_bundle_key`; persona names are never
  converted into file paths.
