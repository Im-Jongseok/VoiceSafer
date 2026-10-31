create index applications_owner_phone_created_idx
  on public.applications(owner_id, applicant_phone, created_at desc);

create function app_private.cancel_application(p_application_id uuid)
returns uuid language plpgsql security definer set search_path = '' as $$
declare application public.applications;
begin
  if (select auth.uid()) is null then
    raise exception 'Authentication required' using errcode = '42501';
  end if;
  select * into application from public.applications
    where id = p_application_id and owner_id = (select auth.uid()) for update;
  if not found then
    raise exception 'Application not found' using errcode = '42501';
  end if;
  if application.status = 'canceled' then return application.id; end if;
  if not application.submission_complete or application.status not in ('received','preparing','ready') or exists (
    select 1 from public.training_calls where application_id = application.id
    and status in ('dialing','queued','ringing','in-progress','uncertain')
  ) then
    raise exception 'Application cannot be canceled in its current state' using errcode = '55000';
  end if;
  update public.applications set status = 'canceled' where id = application.id;
  return application.id;
end;
$$;
create function public.cancel_application(p_application_id uuid)
returns uuid language sql security invoker set search_path = '' as $$
  select app_private.cancel_application(p_application_id);
$$;
revoke all on function app_private.cancel_application(uuid), public.cancel_application(uuid) from public, anon;
grant execute on function app_private.cancel_application(uuid), public.cancel_application(uuid) to authenticated;

create function app_private.guard_canceled_application_call()
returns trigger language plpgsql security definer set search_path = '' as $$
declare application_status text;
begin
  select status into application_status from public.applications where id = new.application_id for update;
  if application_status = 'canceled' and new.status <> 'canceled' then
    raise exception 'Cannot start or prepare calls for a canceled application' using errcode = '55000';
  end if;
  return new;
end;
$$;
revoke all on function app_private.guard_canceled_application_call() from public, anon, authenticated;
create trigger training_calls_cancel_guard before insert or update on public.training_calls
for each row execute function app_private.guard_canceled_application_call();
