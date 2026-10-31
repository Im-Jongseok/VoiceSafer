alter table app_private.operators enable row level security;
alter table app_private.schema_migrations enable row level security;
alter table public.applications add column request_id uuid not null default gen_random_uuid() unique;
alter table public.applications add column submission_complete boolean not null default true;
alter table public.applications add column is_demo boolean not null default false;

alter function public.submit_application(text,text,text,text,date,text,text,text,boolean,boolean,boolean,boolean) set schema app_private;
create function public.submit_application(
  p_applicant_name text, p_applicant_phone text, p_target_name text, p_target_phone text,
  p_preferred_date date, p_preferred_time text, p_scenario_id text, p_consent_version text,
  p_privacy boolean, p_identity boolean, p_voice boolean, p_training boolean
) returns uuid language sql security invoker set search_path = '' as $$
  select app_private.submit_application(p_applicant_name,p_applicant_phone,p_target_name,p_target_phone,p_preferred_date,p_preferred_time,p_scenario_id,p_consent_version,p_privacy,p_identity,p_voice,p_training);
$$;
revoke all on function public.submit_application(text,text,text,text,date,text,text,text,boolean,boolean,boolean,boolean) from public, anon;
grant execute on function public.submit_application(text,text,text,text,date,text,text,text,boolean,boolean,boolean,boolean) to authenticated;

create function app_private.create_application(
  p_request_id uuid, p_applicant_name text, p_applicant_phone text, p_target_name text, p_target_phone text,
  p_preferred_date date, p_preferred_time text, p_scenario_id text, p_consent_version text,
  p_privacy boolean, p_identity boolean, p_voice boolean, p_training boolean, p_is_demo boolean
) returns uuid language plpgsql security definer set search_path = '' as $$
declare result_id uuid; owner uuid;
begin
  if (select auth.uid()) is null then raise exception 'Authentication required' using errcode = '42501'; end if;
  if p_request_id is null then raise exception 'Request ID is required' using errcode = '23514'; end if;
  perform pg_advisory_xact_lock(hashtextextended((select auth.uid())::text, 0));
  select id,owner_id into result_id,owner from public.applications where request_id = p_request_id;
  if found then
    if owner <> (select auth.uid()) then raise exception 'Invalid request' using errcode = '42501'; end if;
    return result_id;
  end if;
  result_id = app_private.submit_application(p_applicant_name,p_applicant_phone,p_target_name,p_target_phone,p_preferred_date,p_preferred_time,p_scenario_id,p_consent_version,p_privacy,p_identity,p_voice,p_training);
  update public.applications set request_id = p_request_id, submission_complete = false, is_demo = coalesce(p_is_demo,false) where id = result_id;
  return result_id;
end;
$$;
create function public.create_application(
  p_request_id uuid, p_applicant_name text, p_applicant_phone text, p_target_name text, p_target_phone text,
  p_preferred_date date, p_preferred_time text, p_scenario_id text, p_consent_version text,
  p_privacy boolean, p_identity boolean, p_voice boolean, p_training boolean, p_is_demo boolean default false
) returns uuid language sql security invoker set search_path = '' as $$
  select app_private.create_application(p_request_id,p_applicant_name,p_applicant_phone,p_target_name,p_target_phone,p_preferred_date,p_preferred_time,p_scenario_id,p_consent_version,p_privacy,p_identity,p_voice,p_training,p_is_demo);
$$;
revoke all on function app_private.create_application(uuid,text,text,text,text,date,text,text,text,boolean,boolean,boolean,boolean,boolean), public.create_application(uuid,text,text,text,text,date,text,text,text,boolean,boolean,boolean,boolean,boolean) from public, anon;
grant execute on function app_private.create_application(uuid,text,text,text,text,date,text,text,text,boolean,boolean,boolean,boolean,boolean), public.create_application(uuid,text,text,text,text,date,text,text,text,boolean,boolean,boolean,boolean,boolean) to authenticated;

create function app_private.finish_application(p_application_id uuid, p_object_path text, p_duration_ms integer, p_size_bytes integer)
returns uuid language plpgsql security definer set search_path = '' as $$
declare application public.applications; object storage.objects; expected_path text;
begin
  if (select auth.uid()) is null then raise exception 'Authentication required' using errcode = '42501'; end if;
  select * into application from public.applications where id = p_application_id and owner_id = (select auth.uid()) for update;
  if not found then raise exception 'Application not found' using errcode = '42501'; end if;
  if application.submission_complete then return application.id; end if;
  if p_object_path is not null then
    expected_path = (select auth.uid())::text || '/' || application.id::text || '/reference.wav';
    if p_object_path <> expected_path or p_duration_ms is null or p_duration_ms not between 3000 and 60000 then
      raise exception 'Invalid reference audio' using errcode = '23514';
    end if;
    select * into object from storage.objects where bucket_id = 'voice-references' and name = expected_path and owner_id = (select auth.uid())::text;
    if not found or coalesce((object.metadata->>'size')::integer,0) <> p_size_bytes or object.metadata->>'mimetype' not in ('audio/wav','audio/x-wav') then
      raise exception 'Uploaded reference audio not found' using errcode = '23514';
    end if;
    insert into public.voice_assets(application_id,kind,bucket_id,object_path,status,duration_ms,sample_rate,size_bytes)
      values(application.id,'reference','voice-references',expected_path,'pending',p_duration_ms,24000,p_size_bytes);
  end if;
  update public.applications set submission_complete = true where id = application.id;
  return application.id;
end;
$$;
create function public.finish_application(p_application_id uuid,p_object_path text default null,p_duration_ms integer default null,p_size_bytes integer default null)
returns uuid language sql security invoker set search_path = '' as $$
  select app_private.finish_application(p_application_id,p_object_path,p_duration_ms,p_size_bytes);
$$;
revoke all on function app_private.finish_application(uuid,text,integer,integer), public.finish_application(uuid,text,integer,integer) from public, anon;
grant execute on function app_private.finish_application(uuid,text,integer,integer), public.finish_application(uuid,text,integer,integer) to authenticated;

create function public.is_operator() returns boolean language sql stable security invoker set search_path = '' as $$
  select app_private.is_operator();
$$;
revoke all on function public.is_operator() from public, anon;
grant execute on function public.is_operator() to authenticated;

alter policy voice_object_read on storage.objects using (
  bucket_id in ('voice-references','training-audio') and (
    app_private.is_operator() or exists(
      select 1 from public.voice_assets a where a.bucket_id = storage.objects.bucket_id and a.object_path = storage.objects.name
      and (a.status = 'ready' or a.kind = 'reference') and app_private.can_read_application(a.application_id)
    )
  )
);
create policy application_owner_broadcast_read on realtime.messages for select to authenticated using (
  extension = 'broadcast' and exists(
    select 1 from public.applications a where a.owner_id = (select auth.uid()) and (select realtime.topic()) = 'application:' || a.id::text
  )
);
create or replace function app_private.broadcast_training_change()
returns trigger language plpgsql security definer set search_path = '' as $$
declare record_id text; call_id uuid; topic text; payload jsonb;
begin
  if tg_op = 'DELETE' then record_id = old.id::text; else record_id = new.id::text; end if;
  if tg_table_name = 'applications' then
    topic = 'operator:applications';
    payload = jsonb_build_object('table',tg_table_name,'id',record_id,'operation',tg_op);
    perform realtime.send(payload,'record_changed','application:' || record_id,true);
  else
    if tg_table_name = 'training_calls' then call_id = record_id::uuid;
    elsif tg_op = 'DELETE' then call_id = old.call_id;
    else call_id = new.call_id; end if;
    topic = 'operator:call:' || call_id::text;
    payload = jsonb_build_object('table',tg_table_name,'id',record_id,'call_id',call_id,'operation',tg_op);
  end if;
  perform realtime.send(payload,'record_changed',topic,true);
  return null;
end;
$$;
