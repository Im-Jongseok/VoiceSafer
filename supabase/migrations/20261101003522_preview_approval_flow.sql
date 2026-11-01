alter table public.applications
  add column preview_version uuid,
  add column preview_asset_id uuid,
  add column preview_text text,
  add column preview_model text,
  add column confirmed_preview_version uuid,
  add column preview_confirmed_at timestamptz;

create function app_private.set_training_plan(p_application_id uuid,p_version uuid,p_scenario_id text,p_text text,p_model text)
returns uuid language plpgsql security definer set search_path = '' as $$
declare a public.applications;
begin
  if not app_private.is_operator() then raise exception 'Operator required' using errcode='42501'; end if;
  select * into a from public.applications where id=p_application_id for update;
  if not found or not a.submission_complete or a.status not in ('received','preparing','ready') then raise exception 'Application not available' using errcode='55000'; end if;
  if p_version is null or p_text is null or char_length(btrim(p_text)) not between 1 and 16000 or p_model not in ('qwen','cosyvoice','elevenlabs') or not exists(select 1 from public.scenarios where id=p_scenario_id and enabled) then raise exception 'Invalid plan' using errcode='23514'; end if;
  if a.preview_version=p_version then
    if a.scenario_id is distinct from p_scenario_id or a.preview_text is distinct from p_text or a.preview_model is distinct from p_model then raise exception 'Version cannot be reused' using errcode='23514'; end if;
    return a.id;
  end if;
  update public.applications set scenario_id=p_scenario_id,preview_version=p_version,preview_asset_id=null,preview_text=p_text,preview_model=p_model,confirmed_preview_version=null,preview_confirmed_at=null,status='preparing' where id=a.id;
  return a.id;
end;
$$;
create function public.set_training_plan(p_application_id uuid,p_version uuid,p_scenario_id text,p_text text,p_model text)
returns uuid language sql security invoker set search_path='' as $$ select app_private.set_training_plan(p_application_id,p_version,p_scenario_id,p_text,p_model); $$;
revoke all on function app_private.set_training_plan(uuid,uuid,text,text,text), public.set_training_plan(uuid,uuid,text,text,text) from public,anon;
grant execute on function app_private.set_training_plan(uuid,uuid,text,text,text), public.set_training_plan(uuid,uuid,text,text,text) to authenticated;

create function app_private.publish_training_preview(p_application_id uuid,p_version uuid,p_duration_ms integer,p_sample_rate integer,p_size_bytes integer)
returns uuid language plpgsql security definer set search_path='' as $$
declare a public.applications; asset uuid; object storage.objects; expected_path text;
begin
  if not app_private.is_operator() then raise exception 'Operator required' using errcode='42501'; end if;
  select * into a from public.applications where id=p_application_id for update;
  if not found or a.status not in ('received','preparing','ready') or a.preview_version is distinct from p_version then raise exception 'Plan changed or canceled' using errcode='55000'; end if;
  if a.preview_asset_id is not null then return a.preview_asset_id; end if;
  expected_path=a.id::text || '/' || p_version::text || '.wav';
  select * into object from storage.objects where bucket_id='training-audio' and name=expected_path and owner_id=(select auth.uid())::text;
  if not found or object.metadata->>'mimetype' not in ('audio/wav','audio/x-wav') or p_size_bytes is null or p_size_bytes not between 45 and 20971520 or (object.metadata->>'size')::integer is distinct from p_size_bytes or p_duration_ms is null or p_duration_ms not between 1 and 600000 or p_sample_rate is null or p_sample_rate not between 8000 and 192000 then raise exception 'Uploaded preview not valid' using errcode='23514'; end if;
  insert into public.voice_assets(application_id,kind,bucket_id,object_path,status,duration_ms,sample_rate,size_bytes) values(a.id,'preview','training-audio',expected_path,'ready',p_duration_ms,p_sample_rate,p_size_bytes) returning id into asset;
  update public.applications set preview_asset_id=asset,confirmed_preview_version=null,preview_confirmed_at=null,status='ready' where id=a.id;
  return asset;
end;
$$;
create function public.publish_training_preview(p_application_id uuid,p_version uuid,p_duration_ms integer,p_sample_rate integer,p_size_bytes integer)
returns uuid language sql security invoker set search_path='' as $$ select app_private.publish_training_preview(p_application_id,p_version,p_duration_ms,p_sample_rate,p_size_bytes); $$;
revoke all on function app_private.publish_training_preview(uuid,uuid,integer,integer,integer), public.publish_training_preview(uuid,uuid,integer,integer,integer) from public,anon;
grant execute on function app_private.publish_training_preview(uuid,uuid,integer,integer,integer), public.publish_training_preview(uuid,uuid,integer,integer,integer) to authenticated;

create function app_private.confirm_training_preview(p_application_id uuid,p_version uuid,p_asset_id uuid)
returns uuid language plpgsql security definer set search_path='' as $$
declare a public.applications;
begin
  if (select auth.uid()) is null then raise exception 'Authentication required' using errcode='42501'; end if;
  select * into a from public.applications where id=p_application_id and owner_id=(select auth.uid()) for update;
  if not found then raise exception 'Application not found' using errcode='42501'; end if;
  if a.status <> 'ready' or a.preview_version is distinct from p_version or a.preview_asset_id is null or a.preview_asset_id is distinct from p_asset_id or not exists(select 1 from public.voice_assets where id=p_asset_id and application_id=a.id and kind='preview' and status='ready') then raise exception 'Preview changed or unavailable' using errcode='55000'; end if;
  update public.applications set confirmed_preview_version=p_version,preview_confirmed_at=coalesce(preview_confirmed_at,now()) where id=a.id;
  return a.id;
end;
$$;
create function public.confirm_training_preview(p_application_id uuid,p_version uuid,p_asset_id uuid)
returns uuid language sql security invoker set search_path='' as $$ select app_private.confirm_training_preview(p_application_id,p_version,p_asset_id); $$;
revoke all on function app_private.confirm_training_preview(uuid,uuid,uuid), public.confirm_training_preview(uuid,uuid,uuid) from public,anon;
grant execute on function app_private.confirm_training_preview(uuid,uuid,uuid), public.confirm_training_preview(uuid,uuid,uuid) to authenticated;

create function app_private.invalidate_changed_scenario()
returns trigger language plpgsql set search_path='' as $$
begin
  if new.scenario_id is distinct from old.scenario_id and new.preview_version is not distinct from old.preview_version then
    new.preview_version=null;new.preview_asset_id=null;new.preview_text=null;new.preview_model=null;new.confirmed_preview_version=null;new.preview_confirmed_at=null;
    if new.status in ('ready','preparing') then new.status='received'; end if;
  end if;
  return new;
end;
$$;
revoke all on function app_private.invalidate_changed_scenario() from public,anon,authenticated;
create trigger applications_scenario_preview before update on public.applications for each row execute function app_private.invalidate_changed_scenario();
