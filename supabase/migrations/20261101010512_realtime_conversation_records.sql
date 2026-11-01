-- Retries and delayed intermediate results cannot overwrite a final utterance.
create function app_private.record_training_segment(p_call_id uuid,p_source_event_id text,p_speaker text,p_position integer,p_revision integer,p_text text,p_is_final boolean,p_start_ms integer,p_end_ms integer)
returns uuid language plpgsql security definer set search_path='' as $$
declare result uuid;
begin
  if not app_private.is_operator() then raise exception 'Operator required' using errcode='42501'; end if;
  if not exists(select 1 from public.training_calls where id=p_call_id and provider='clawops' and approved_at is not null) then raise exception 'Approved call required' using errcode='55000'; end if;
  insert into public.conversation_segments(call_id,source_event_id,speaker,position,revision,text,is_final,start_ms,end_ms)
    values(p_call_id,p_source_event_id,p_speaker,p_position,p_revision,p_text,p_is_final,p_start_ms,p_end_ms)
    on conflict(call_id,source_event_id) do update set revision=excluded.revision,text=excluded.text,is_final=excluded.is_final,end_ms=excluded.end_ms
    where conversation_segments.revision < excluded.revision
      and (not conversation_segments.is_final or excluded.is_final)
      and conversation_segments.speaker=excluded.speaker and conversation_segments.position=excluded.position
    returning id into result;
  if result is null then select id into result from public.conversation_segments where call_id=p_call_id and source_event_id=p_source_event_id; end if;
  return result;
end;
$$;
create function public.record_training_segment(p_call_id uuid,p_source_event_id text,p_speaker text,p_position integer,p_revision integer,p_text text,p_is_final boolean,p_start_ms integer,p_end_ms integer)
returns uuid language sql security invoker set search_path='' as $$ select app_private.record_training_segment(p_call_id,p_source_event_id,p_speaker,p_position,p_revision,p_text,p_is_final,p_start_ms,p_end_ms); $$;
revoke all on function app_private.record_training_segment(uuid,text,text,integer,integer,text,boolean,integer,integer),public.record_training_segment(uuid,text,text,integer,integer,text,boolean,integer,integer) from public,anon;
grant execute on function app_private.record_training_segment(uuid,text,text,integer,integer,text,boolean,integer,integer),public.record_training_segment(uuid,text,text,integer,integer,text,boolean,integer,integer) to authenticated;
