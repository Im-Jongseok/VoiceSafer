-- The demo has one ClawOps phone line. Reserve it before claiming its media socket.
create unique index training_calls_one_active_clawops_line_idx
on public.training_calls(provider)
where provider='clawops' and status in ('dialing','queued','ringing','in-progress','uncertain');
