create table public.training_reports (
  call_id uuid primary key references public.training_calls(id) on delete cascade,
  application_id uuid not null references public.applications(id) on delete cascade,
  revision integer not null check (revision > 0),
  status text not null check (status in ('draft','final')),
  content jsonb not null check (jsonb_typeof(content) = 'object' and octet_length(content::text) <= 131072),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index training_reports_application_created_idx on public.training_reports(application_id, created_at desc);
alter table public.training_reports enable row level security;
revoke all on public.training_reports from public,anon,authenticated;
grant select on public.training_reports to authenticated;
grant all on public.training_reports to service_role;
create policy report_reader on public.training_reports for select to authenticated
  using ((status='final' or app_private.is_operator()) and app_private.can_read_application(application_id));

create function public.record_training_report(p_call_id uuid,p_revision integer,p_status text,p_content jsonb)
returns void language plpgsql security definer set search_path='' as $$
declare c public.training_calls;
begin
  if not app_private.is_operator() then raise exception 'Operator required' using errcode='42501'; end if;
  select * into c from public.training_calls where id=p_call_id;
  if not found or c.provider is distinct from 'clawops' or c.approved_at is null then
    raise exception 'Approved call required' using errcode='55000';
  end if;
  if p_status='final' and c.status not in ('completed','failed','canceled') then
    raise exception 'Call has not ended' using errcode='55000';
  end if;
  insert into public.training_reports(call_id,application_id,revision,status,content)
    values(c.id,c.application_id,p_revision,p_status,p_content)
    on conflict(call_id) do update set revision=excluded.revision,status=excluded.status,content=excluded.content,updated_at=now()
    where training_reports.revision < excluded.revision and (training_reports.status <> 'final' or excluded.status='final');
end;
$$;
revoke all on function public.record_training_report(uuid,integer,text,jsonb) from public,anon;
grant execute on function public.record_training_report(uuid,integer,text,jsonb) to authenticated;

create function app_private.broadcast_training_report()
returns trigger language plpgsql security definer set search_path='' as $$
begin
  perform realtime.send(jsonb_build_object('table','training_reports','id',new.call_id::text,'call_id',new.call_id::text,'operation',tg_op),'record_changed','operator:call:' || new.call_id::text,true);
  if new.status='final' then
    perform realtime.send(jsonb_build_object('table','training_reports','id',new.call_id::text,'operation',tg_op),'record_changed','application:' || new.application_id::text,true);
  end if;
  return null;
end;
$$;
create trigger training_reports_broadcast after insert or update on public.training_reports
  for each row execute function app_private.broadcast_training_report();
