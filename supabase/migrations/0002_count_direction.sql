-- İki yönlü sayım (countMode detect; kişi/araç/hayvan, docs/03 §4.10).
-- Sayım olayında count.direction = 'out' (çıkış) count'a eklenmez, count_out'a eklenir. direction yoksa ya da
-- 'in' ise eskisi gibi count (giriş / ürün). Eski cihazlar etkilenmez.

alter table minute_stats add column if not exists count_out int not null default 0;

create or replace function ingest_events(p_device_id text, p_events jsonb)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_dev devices;
  v_total int := jsonb_array_length(p_events);
  v_inserted int;
  v_running boolean;
  v_since timestamptz;
  v_hb jsonb;
begin
  select * into v_dev from devices where id = p_device_id;
  if not found then
    raise exception 'unknown_device' using errcode = 'P0001';
  end if;

  with src as (
    select (e ->> 'eventId')::uuid as event_id,
           e ->> 'type' as type,
           (e ->> 'ts')::timestamptz as ts,
           coalesce(e ->> 'cameraId', 'default') as camera_id,
           nullif(e ->> 'profileId', '')::uuid as profile_id,
           e as body
      from jsonb_array_elements(p_events) e
  ), ins as (
    insert into events (event_id, org_id, line_id, device_id, camera_id, profile_id, type, ts, body)
    select event_id, v_dev.org_id, v_dev.line_id, v_dev.id, camera_id, profile_id, type, ts, body from src
    on conflict (event_id) do nothing
    returning line_id, camera_id, type, ts, body
  ), agg as (
    select line_id, camera_id, date_trunc('minute', ts) as minute,
           coalesce(sum((body -> 'count' ->> 'delta')::int)
                      filter (where type = 'count' and coalesce(body -> 'count' ->> 'direction', 'in') <> 'out'), 0) as c,
           coalesce(sum((body -> 'count' ->> 'delta')::int)
                      filter (where type = 'count' and body -> 'count' ->> 'direction' = 'out'), 0) as c_out,
           count(*) filter (where type = 'inspection' and body -> 'inspection' ->> 'result' = 'ok') as ok,
           count(*) filter (where type = 'inspection' and body -> 'inspection' ->> 'result' = 'nok') as nok
      from ins
     where type in ('count', 'inspection') and line_id is not null
     group by 1, 2, 3
  ), up as (
    insert into minute_stats as m (line_id, camera_id, minute, count, count_out, ok, nok)
    select line_id, camera_id, minute, c, c_out, ok, nok from agg
    on conflict (line_id, camera_id, minute) do update
      set count = m.count + excluded.count, count_out = m.count_out + excluded.count_out,
          ok = m.ok + excluded.ok, nok = m.nok + excluded.nok
    returning 1
  )
  select count(*) into v_inserted from ins;

  -- son durum olayı
  select (e -> 'state' ->> 'running')::boolean, (e ->> 'ts')::timestamptz
    into v_running, v_since
    from jsonb_array_elements(p_events) e
   where e ->> 'type' = 'state'
   order by (e ->> 'ts')::timestamptz desc
   limit 1;
  if v_running is not null and v_dev.line_id is not null then
    insert into line_state as s (line_id, running, since, updated_at)
    values (v_dev.line_id, v_running, v_since, now())
    on conflict (line_id) do update
      set running = excluded.running, since = excluded.since, updated_at = now()
      where s.since <= excluded.since;
  end if;

  -- son heartbeat
  select e -> 'heartbeat' into v_hb
    from jsonb_array_elements(p_events) e
   where e ->> 'type' = 'heartbeat'
   order by (e ->> 'ts')::timestamptz desc
   limit 1;
  update devices
     set last_seen_at = now(),
         last_heartbeat = coalesce(v_hb, last_heartbeat),
         app_version = coalesce(v_hb ->> 'appVersion', app_version)
   where id = v_dev.id;

  return jsonb_build_object('accepted', v_inserted, 'duplicates', v_total - v_inserted);
end $$;

revoke all on function ingest_events(text, jsonb) from public, anon, authenticated;
