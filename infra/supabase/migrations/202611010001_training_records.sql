create schema if not exists app_private;
revoke all on schema app_private from public, anon, authenticated;
grant usage on schema app_private to authenticated;

create table app_private.operators (
  user_id uuid primary key references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);
revoke all on app_private.operators from public, anon, authenticated;

create function app_private.is_operator()
returns boolean language sql stable security definer set search_path = '' as $$
  select exists(select 1 from app_private.operators where user_id = (select auth.uid()));
$$;
revoke all on function app_private.is_operator() from public, anon;
grant execute on function app_private.is_operator() to authenticated;

create table public.scenarios (
  id text primary key,
  title text not null check (char_length(title) between 1 and 120),
  description text not null default '',
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);
insert into public.scenarios (id, title) values
  ('phone', '휴대폰 고장과 대리결제'),
  ('hospital', '병원 응급상황과 비용 요청'),
  ('message', '익숙한 목소리와 문자 전환'),
  ('app', '휴대폰 도움과 앱 설치'),
  ('travel', '여행 중 분실과 금전 요청');

create table public.applications (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id),
  applicant_name text not null check (char_length(btrim(applicant_name)) between 1 and 80),
  applicant_phone text not null check (applicant_phone ~ '^\+[1-9][0-9]{6,14}$'),
  target_name text not null check (char_length(btrim(target_name)) between 1 and 80),
  target_phone text not null check (target_phone ~ '^\+[1-9][0-9]{6,14}$'),
  preferred_date date not null,
  preferred_time text not null check (preferred_time in ('morning','afternoon','evening','any')),
  scenario_id text references public.scenarios(id),
  status text not null default 'received' check (status in ('received','preparing','ready','dialing','calling','completed','canceled','failed','uncertain')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index applications_owner_created_idx on public.applications(owner_id, created_at desc);
create index applications_status_created_idx on public.applications(status, created_at desc);

create table public.application_consents (
  application_id uuid primary key references public.applications(id) on delete cascade,
  version text not null check (char_length(version) between 1 and 40),
  privacy boolean not null check (privacy),
  identity boolean not null check (identity),
  voice boolean not null check (voice),
  training boolean not null check (training),
  accepted_at timestamptz not null default now()
);

create function app_private.can_read_application(application_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select app_private.is_operator() or exists(
    select 1 from public.applications a
    where a.id = application_id and a.owner_id = (select auth.uid())
  );
$$;
revoke all on function app_private.can_read_application(uuid) from public, anon;
grant execute on function app_private.can_read_application(uuid) to authenticated;

create table public.voice_assets (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  kind text not null check (kind in ('reference','preview')),
  bucket_id text not null check (bucket_id in ('voice-references','training-audio')),
  object_path text not null,
  status text not null default 'pending' check (status in ('pending','ready','failed')),
  duration_ms integer check (duration_ms > 0),
  sample_rate integer check (sample_rate between 8000 and 192000),
  size_bytes integer check (size_bytes > 0),
  content_type text not null default 'audio/wav',
  created_at timestamptz not null default now(),
  unique(bucket_id, object_path),
  unique(id, application_id),
  check ((kind = 'reference' and bucket_id = 'voice-references') or (kind = 'preview' and bucket_id = 'training-audio')),
  check (kind <> 'reference' or duration_ms between 3000 and 60000)
);
create index voice_assets_application_idx on public.voice_assets(application_id, kind, created_at desc);

create table public.training_calls (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  scenario_id text not null references public.scenarios(id),
  scenario_text text not null check (char_length(scenario_text) between 1 and 16000),
  voice_asset_id uuid,
  model text not null default 'qwen',
  provider text,
  provider_call_id text,
  status text not null default 'preparing' check (status in ('preparing','ready','dialing','queued','ringing','in-progress','completed','canceled','failed','uncertain')),
  approved_at timestamptz,
  started_at timestamptz,
  ended_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (voice_asset_id, application_id) references public.voice_assets(id, application_id),
  unique(provider, provider_call_id),
  check (ended_at is null or (started_at is not null and ended_at >= started_at)),
  check (status not in ('dialing','queued','ringing','in-progress') or (voice_asset_id is not null and approved_at is not null))
);
create index training_calls_application_created_idx on public.training_calls(application_id, created_at desc);
create unique index training_calls_one_active_idx on public.training_calls(application_id)
  where status in ('dialing','queued','ringing','in-progress','uncertain');

create table public.conversation_segments (
  id uuid primary key default gen_random_uuid(),
  call_id uuid not null references public.training_calls(id) on delete cascade,
  source_event_id text not null check (char_length(source_event_id) between 1 and 200),
  speaker text not null check (speaker in ('caller','callee')),
  position integer not null check (position >= 0),
  revision integer not null default 1 check (revision >= 1),
  text text not null check (char_length(text) between 1 and 16000),
  is_final boolean not null default false,
  start_ms integer check (start_ms >= 0),
  end_ms integer check (end_ms is null or (start_ms is not null and end_ms >= start_ms)),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(call_id, source_event_id)
);
create index conversation_segments_call_position_idx on public.conversation_segments(call_id, position, id);

create table public.call_events (
  id bigint generated always as identity primary key,
  call_id uuid not null references public.training_calls(id) on delete cascade,
  source_event_id text not null check (char_length(source_event_id) between 1 and 200),
  event_type text not null check (event_type in ('status','speech_started','speech_stopped','playback_started','playback_stopped','interrupted','error')),
  payload jsonb not null default '{}' check (jsonb_typeof(payload) = 'object' and octet_length(payload::text) <= 8192),
  occurred_at timestamptz not null default now(),
  received_at timestamptz not null default now(),
  unique(call_id, source_event_id)
);
create index call_events_call_occurred_idx on public.call_events(call_id, occurred_at, id);

create function app_private.touch_updated_at()
returns trigger language plpgsql set search_path = '' as $$
begin
  new.updated_at = now();
  return new;
end;
$$;
create trigger applications_touch before update on public.applications for each row execute function app_private.touch_updated_at();
create trigger training_calls_touch before update on public.training_calls for each row execute function app_private.touch_updated_at();
create trigger conversation_segments_touch before update on public.conversation_segments for each row execute function app_private.touch_updated_at();

create function app_private.guard_segment_revision()
returns trigger language plpgsql set search_path = '' as $$
begin
  if new.call_id <> old.call_id or new.source_event_id <> old.source_event_id or new.speaker <> old.speaker or new.position <> old.position then
    raise exception 'Segment identity cannot change' using errcode = '23514';
  end if;
  if new.revision <= old.revision or (old.is_final and not new.is_final) then
    raise exception 'Stale or regressive transcript revision' using errcode = '23514';
  end if;
  return new;
end;
$$;
create trigger conversation_segments_revision before update on public.conversation_segments for each row execute function app_private.guard_segment_revision();

alter table public.scenarios enable row level security;
alter table public.applications enable row level security;
alter table public.application_consents enable row level security;
alter table public.voice_assets enable row level security;
alter table public.training_calls enable row level security;
alter table public.conversation_segments enable row level security;
alter table public.call_events enable row level security;
revoke all on public.scenarios, public.applications, public.application_consents, public.voice_assets, public.training_calls, public.conversation_segments, public.call_events from anon, authenticated;
revoke all on sequence public.call_events_id_seq from anon, authenticated;
grant select on public.scenarios to anon, authenticated;
grant select on public.applications, public.application_consents, public.voice_assets, public.training_calls, public.conversation_segments, public.call_events to authenticated;
grant insert, update, delete on public.scenarios, public.voice_assets, public.training_calls, public.conversation_segments, public.call_events to authenticated;
grant update(status, scenario_id) on public.applications to authenticated;
grant usage, select on sequence public.call_events_id_seq to authenticated;
grant all on public.scenarios, public.applications, public.application_consents, public.voice_assets, public.training_calls, public.conversation_segments, public.call_events to service_role;
grant usage, select on sequence public.call_events_id_seq to service_role;

create policy scenario_catalog on public.scenarios for select to anon, authenticated using (enabled);
create policy scenario_operator on public.scenarios for all to authenticated using (app_private.is_operator()) with check (app_private.is_operator());
create policy application_reader on public.applications for select to authenticated using (app_private.can_read_application(id));
create policy application_operator_update on public.applications for update to authenticated using (app_private.is_operator()) with check (app_private.is_operator());
create policy consent_reader on public.application_consents for select to authenticated using (app_private.can_read_application(application_id));
create policy asset_reader on public.voice_assets for select to authenticated using (app_private.can_read_application(application_id));
create policy asset_operator on public.voice_assets for all to authenticated using (app_private.is_operator()) with check (app_private.is_operator());
create policy call_operator on public.training_calls for all to authenticated using (app_private.is_operator()) with check (app_private.is_operator());
create policy segment_operator on public.conversation_segments for all to authenticated using (app_private.is_operator()) with check (app_private.is_operator());
create policy event_operator on public.call_events for all to authenticated using (app_private.is_operator()) with check (app_private.is_operator());

create function public.submit_application(
  p_applicant_name text, p_applicant_phone text,
  p_target_name text, p_target_phone text,
  p_preferred_date date, p_preferred_time text,
  p_scenario_id text, p_consent_version text,
  p_privacy boolean, p_identity boolean, p_voice boolean, p_training boolean
)
returns uuid language plpgsql security definer set search_path = '' as $$
declare application_id uuid;
begin
  if (select auth.uid()) is null then
    raise exception 'Authentication required' using errcode = '42501';
  end if;
  if p_preferred_date < (now() at time zone 'Asia/Seoul')::date then
    raise exception 'Preferred date must be today or later' using errcode = '23514';
  end if;
  if not coalesce(p_privacy and p_identity and p_voice and p_training, false) then
    raise exception 'All required consents are required' using errcode = '23514';
  end if;
  if p_scenario_id is not null and not exists(select 1 from public.scenarios where id = p_scenario_id and enabled) then
    raise exception 'Unknown scenario' using errcode = '23514';
  end if;
  insert into public.applications(owner_id, applicant_name, applicant_phone, target_name, target_phone, preferred_date, preferred_time, scenario_id)
    values((select auth.uid()), btrim(p_applicant_name), p_applicant_phone, btrim(p_target_name), p_target_phone, p_preferred_date, p_preferred_time, p_scenario_id)
    returning id into application_id;
  insert into public.application_consents(application_id, version, privacy, identity, voice, training)
    values(application_id, p_consent_version, p_privacy, p_identity, p_voice, p_training);
  return application_id;
end;
$$;
revoke all on function public.submit_application(text,text,text,text,date,text,text,text,boolean,boolean,boolean,boolean) from public, anon;
grant execute on function public.submit_application(text,text,text,text,date,text,text,text,boolean,boolean,boolean,boolean) to authenticated;

insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types) values
  ('voice-references', 'voice-references', false, 3145728, array['audio/wav','audio/x-wav']),
  ('training-audio', 'training-audio', false, 20971520, array['audio/wav','audio/mpeg','audio/ogg']);
create policy voice_object_read on storage.objects for select to authenticated using (
  bucket_id in ('voice-references','training-audio') and (
    app_private.is_operator() or exists(
      select 1 from public.voice_assets a where a.bucket_id = storage.objects.bucket_id and a.object_path = storage.objects.name and a.status = 'ready' and app_private.can_read_application(a.application_id)
    )
  )
);
create policy voice_reference_upload on storage.objects for insert to authenticated with check (
  bucket_id = 'voice-references' and (storage.foldername(name))[1] = (select auth.uid())::text
  and exists(select 1 from public.applications a join public.application_consents c on c.application_id = a.id
    where a.id::text = (storage.foldername(name))[2] and a.owner_id = (select auth.uid()) and a.status = 'received')
);
create policy voice_operator_upload on storage.objects for insert to authenticated with check (bucket_id in ('voice-references','training-audio') and app_private.is_operator());
create policy voice_operator_delete on storage.objects for delete to authenticated using (bucket_id in ('voice-references','training-audio') and app_private.is_operator());

create policy training_operator_broadcast_read on realtime.messages for select to authenticated using (
  extension = 'broadcast' and app_private.is_operator() and (
    (select realtime.topic()) = 'operator:applications' or exists(
      select 1 from public.training_calls c where (select realtime.topic()) = 'operator:call:' || c.id::text
    )
  )
);

create function app_private.broadcast_training_change()
returns trigger language plpgsql security definer set search_path = '' as $$
declare record_id text; call_id uuid; topic text; payload jsonb;
begin
  if tg_op = 'DELETE' then record_id = old.id::text; else record_id = new.id::text; end if;
  if tg_table_name = 'applications' then
    topic = 'operator:applications';
    payload = jsonb_build_object('table', tg_table_name, 'id', record_id, 'operation', tg_op);
  else
    if tg_table_name = 'training_calls' then
      call_id = record_id::uuid;
    elsif tg_op = 'DELETE' then
      call_id = old.call_id;
    else
      call_id = new.call_id;
    end if;
    topic = 'operator:call:' || call_id::text;
    payload = jsonb_build_object('table', tg_table_name, 'id', record_id, 'call_id', call_id, 'operation', tg_op);
  end if;
  perform realtime.send(payload, 'record_changed', topic, true);
  return null;
end;
$$;
create trigger applications_broadcast after insert or update or delete on public.applications for each row execute function app_private.broadcast_training_change();
create trigger training_calls_broadcast after insert or update or delete on public.training_calls for each row execute function app_private.broadcast_training_change();
create trigger conversation_segments_broadcast after insert or update or delete on public.conversation_segments for each row execute function app_private.broadcast_training_change();
create trigger call_events_broadcast after insert or update or delete on public.call_events for each row execute function app_private.broadcast_training_change();

revoke all on function app_private.touch_updated_at(), app_private.guard_segment_revision(), app_private.broadcast_training_change() from public, anon, authenticated;
