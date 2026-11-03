create table public.conversation_messages (
  id uuid primary key,
  call_id uuid not null references public.training_calls(id) on delete cascade,
  provider_message_id text unique check (provider_message_id ~ '^MG[A-Za-z0-9]{1,64}$'),
  body text not null check (char_length(body) between 1 and 2000),
  recipient text not null check (recipient ~ '^\+?[0-9]{8,15}$'),
  sender text not null check (sender ~ '^\+?[0-9]{8,15}$'),
  status text not null check (status in ('requesting','queued','sent','failed','uncertain')),
  created_at timestamptz not null,
  updated_at timestamptz not null,
  check (updated_at >= created_at)
);
create index conversation_messages_call_created_idx on public.conversation_messages(call_id, created_at, id);
alter table public.conversation_messages enable row level security;
revoke all on public.conversation_messages from public, anon, authenticated;
grant select,insert,update,delete on public.conversation_messages to authenticated;
grant all on public.conversation_messages to service_role;
create policy message_operator on public.conversation_messages for all to authenticated
  using (app_private.is_operator())
  with check (app_private.is_operator() and exists (
    select 1 from public.training_calls c where c.id = call_id and c.provider = 'clawops' and c.approved_at is not null
  ));
create trigger conversation_messages_broadcast after insert or update or delete on public.conversation_messages
  for each row execute function app_private.broadcast_training_change();
