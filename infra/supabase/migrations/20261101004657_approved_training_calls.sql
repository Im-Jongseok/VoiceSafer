-- Reserve against the latest applicant approval before the PC sends a phone request.
create function app_private.reserve_training_call(p_application_id uuid, p_version uuid, p_target_phone text)
returns uuid language plpgsql security definer set search_path='' as $$
declare a public.applications; call_id uuid;
begin
  if not app_private.is_operator() then raise exception 'Operator required' using errcode='42501'; end if;
  select * into a from public.applications where id=p_application_id for update;
  if not found or not a.submission_complete or a.status <> 'ready'
    or p_version is null or a.preview_version is distinct from p_version
    or a.confirmed_preview_version is distinct from p_version or a.preview_confirmed_at is null
    or a.target_phone is distinct from p_target_phone
    or a.preview_model is null or a.preview_text is null
    or not exists(select 1 from public.application_consents where application_id=a.id and privacy and identity and voice and training)
    or not exists(select 1 from public.voice_assets where id=a.preview_asset_id and application_id=a.id and kind='preview' and status='ready' and bucket_id='training-audio')
    or exists(select 1 from public.training_calls where application_id=a.id and status in ('dialing','queued','ringing','in-progress','uncertain'))
  then raise exception 'Latest approved preview and available application required' using errcode='55000'; end if;
  insert into public.training_calls(application_id,scenario_id,scenario_text,voice_asset_id,model,provider,status,approved_at)
    values(a.id,a.scenario_id,a.preview_text,a.preview_asset_id,a.preview_model,'clawops','dialing',a.preview_confirmed_at)
    returning id into call_id;
  update public.applications set status='dialing' where id=a.id;
  return call_id;
end;
$$;
create function public.reserve_training_call(p_application_id uuid,p_version uuid,p_target_phone text)
returns uuid language sql security invoker set search_path='' as $$ select app_private.reserve_training_call(p_application_id,p_version,p_target_phone); $$;
revoke all on function app_private.reserve_training_call(uuid,uuid,text),public.reserve_training_call(uuid,uuid,text) from public,anon;
grant execute on function app_private.reserve_training_call(uuid,uuid,text),public.reserve_training_call(uuid,uuid,text) to authenticated;

create function app_private.update_training_call_status(p_call_id uuid,p_provider_call_id text,p_status text)
returns uuid language plpgsql security definer set search_path='' as $$
declare c public.training_calls; application_id uuid; next_status text;
begin
  if not app_private.is_operator() then raise exception 'Operator required' using errcode='42501'; end if;
  select t.application_id into application_id from public.training_calls t where t.id=p_call_id;
  if not found then raise exception 'Call not found' using errcode='55000'; end if;
  -- Same lock order as reserve/cancel; serialize status changes across PCs.
  perform 1 from public.applications where id=application_id for update;
  select * into c from public.training_calls where id=p_call_id for update;
  if c.provider is distinct from 'clawops' or p_status is null
    or p_status not in ('queued','ringing','in-progress','completed','canceled','failed','uncertain')
    or (p_provider_call_id is not null and p_provider_call_id !~ '^CA[A-Za-z0-9]{1,64}$')
    or (c.provider_call_id is not null and c.provider_call_id is distinct from p_provider_call_id)
    or (p_provider_call_id is null and (c.status <> 'dialing' or p_status not in ('failed','uncertain')))
  then raise exception 'Invalid call update' using errcode='23514'; end if;
  -- A delayed poll must never restore a finished call or an earlier ringing state.
  if c.status in ('completed','canceled','failed') then return c.id; end if;
  next_status=p_status;
  if (c.status='in-progress' and p_status in ('queued','ringing')) or (c.status='ringing' and p_status='queued') then next_status=c.status; end if;
  update public.training_calls set provider_call_id=coalesce(c.provider_call_id,p_provider_call_id),status=next_status,
    started_at=case when p_provider_call_id is not null then coalesce(c.started_at,now()) else c.started_at end,
    ended_at=case when next_status in ('completed','canceled','failed') and p_provider_call_id is not null then now() else null end
    where id=c.id;
  update public.applications set status=case
    when next_status in ('queued','ringing','in-progress') then 'calling'
    when next_status='completed' then 'completed'
    when next_status='uncertain' then 'uncertain'
    else 'ready' end where id=application_id;
  return c.id;
end;
$$;
create function public.update_training_call_status(p_call_id uuid,p_provider_call_id text,p_status text)
returns uuid language sql security invoker set search_path='' as $$ select app_private.update_training_call_status(p_call_id,p_provider_call_id,p_status); $$;
revoke all on function app_private.update_training_call_status(uuid,text,text),public.update_training_call_status(uuid,text,text) from public,anon;
grant execute on function app_private.update_training_call_status(uuid,text,text),public.update_training_call_status(uuid,text,text) to authenticated;
