alter table public.applications add column target_relationship text
  check (target_relationship is null or (target_relationship = btrim(target_relationship) and char_length(target_relationship) between 1 and 80));

-- Keep the existing creation transaction and idempotency checks; accept the new field atomically.
drop function public.create_application(uuid,text,text,text,text,date,text,text,text,boolean,boolean,boolean,boolean,boolean);
create function public.create_application(
  p_request_id uuid, p_applicant_name text, p_applicant_phone text, p_target_name text, p_target_phone text,
  p_preferred_date date, p_preferred_time text, p_scenario_id text, p_consent_version text,
  p_privacy boolean, p_identity boolean, p_voice boolean, p_training boolean,
  p_is_demo boolean default false, p_target_relationship text default null
) returns uuid language plpgsql security definer set search_path = '' as $$
declare result_id uuid;
begin
  if p_target_relationship is not null and char_length(btrim(p_target_relationship)) not between 1 and 80 then
    raise exception 'Invalid relationship' using errcode = '23514';
  end if;
  result_id = app_private.create_application(p_request_id,p_applicant_name,p_applicant_phone,p_target_name,p_target_phone,p_preferred_date,p_preferred_time,p_scenario_id,p_consent_version,p_privacy,p_identity,p_voice,p_training,p_is_demo);
  if p_target_relationship is not null then
    update public.applications set target_relationship = btrim(p_target_relationship)
      where id = result_id and owner_id = (select auth.uid()) and not submission_complete and status = 'received';
  end if;
  return result_id;
end;
$$;
revoke all on function public.create_application(uuid,text,text,text,text,date,text,text,text,boolean,boolean,boolean,boolean,boolean,text) from public, anon;
grant execute on function public.create_application(uuid,text,text,text,text,date,text,text,text,boolean,boolean,boolean,boolean,boolean,text) to authenticated;
