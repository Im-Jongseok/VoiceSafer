create index applications_scenario_idx on public.applications(scenario_id);
create index training_calls_scenario_idx on public.training_calls(scenario_id);
create index training_calls_voice_asset_idx on public.training_calls(voice_asset_id, application_id);

drop policy scenario_operator on public.scenarios;
drop policy scenario_catalog on public.scenarios;
create policy scenario_catalog on public.scenarios for select to anon using (enabled);
create policy scenario_authenticated_reader on public.scenarios for select to authenticated using (enabled or app_private.is_operator());
create policy scenario_operator_insert on public.scenarios for insert to authenticated with check (app_private.is_operator());
create policy scenario_operator_update on public.scenarios for update to authenticated using (app_private.is_operator()) with check (app_private.is_operator());
create policy scenario_operator_delete on public.scenarios for delete to authenticated using (app_private.is_operator());

drop policy asset_operator on public.voice_assets;
create policy asset_operator_insert on public.voice_assets for insert to authenticated with check (app_private.is_operator());
create policy asset_operator_update on public.voice_assets for update to authenticated using (app_private.is_operator()) with check (app_private.is_operator());
create policy asset_operator_delete on public.voice_assets for delete to authenticated using (app_private.is_operator());
