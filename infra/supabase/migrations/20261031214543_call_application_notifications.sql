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
    if tg_table_name = 'training_calls' then
      call_id = record_id::uuid;
      perform realtime.send(jsonb_build_object('table',tg_table_name,'id',record_id,'operation',tg_op),'record_changed','operator:applications',true);
    elsif tg_op = 'DELETE' then call_id = old.call_id;
    else call_id = new.call_id; end if;
    topic = 'operator:call:' || call_id::text;
    payload = jsonb_build_object('table',tg_table_name,'id',record_id,'call_id',call_id,'operation',tg_op);
  end if;
  perform realtime.send(payload,'record_changed',topic,true);
  return null;
end;
$$;
