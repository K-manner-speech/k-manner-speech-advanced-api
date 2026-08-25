# Pre-baseline migration history

These files are the incremental SQL changes that existed before the repository
captured the complete remote `public` schema on 2026-08-25.

They are retained for audit and review only. Supabase CLI does not execute files
outside `supabase/migrations/`, so do not move them back without first reconciling
the local and remote migration histories.

The active chain starts with
`supabase/migrations/20260825033933_current_remote_schema_baseline.sql`.
