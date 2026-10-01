-- BantVision v1 şeması. Sözleşme: docs/02-contracts.md, açıklama: docs/06-backend-dashboard.md
create extension if not exists pgcrypto;

-- ---------- Organizasyon ----------
create table orgs (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);

create table org_members (
  org_id uuid not null references orgs on delete cascade,
  user_id uuid not null references auth.users on delete cascade,
  role text not null default 'viewer' check (role in ('owner', 'admin', 'viewer')),
  primary key (org_id, user_id)
);

create table sites (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  name text not null
);

create table lines (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  site_id uuid references sites on delete set null,
  name text not null,
  ideal_rate_per_min numeric,                 -- OEE performans için
  timezone text not null default 'Europe/Istanbul',
  created_at timestamptz not null default now()
);

create table shifts (                         -- planlı üretim süresi (OEE kullanılabilirlik)
  id uuid primary key default gen_random_uuid(),
  line_id uuid not null references lines on delete cascade,
  name text not null,
  start_time time not null,
  end_time time not null,                     -- start > end ise gece vardiyası
  weekdays int[] not null default '{1,2,3,4,5}' -- ISO: 1=Pzt
);

-- ---------- Cihazlar ----------
create table devices (
  id text primary key default ('dev_' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 10)),
  org_id uuid not null references orgs on delete cascade,
  line_id uuid references lines on delete set null,
  kind text not null check (kind in ('iphone', 'edge')),
  name text,
  model text,
  app_version text,
  key_hash text not null unique,               -- sha256(deviceKey) hex
  last_seen_at timestamptz,
  last_heartbeat jsonb,
  created_at timestamptz not null default now()
);

create table pairing_codes (
  code text primary key check (code ~ '^[0-9A-Z]{8}$'),
  org_id uuid not null references orgs on delete cascade,
  line_id uuid not null references lines on delete cascade,
  expires_at timestamptz not null default now() + interval '30 minutes',
  used_at timestamptz,
  created_by uuid references auth.users
);

create table profiles (
  id uuid primary key,
  org_id uuid not null references orgs on delete cascade,
  name text not null,
  body jsonb not null,                         -- contracts/product-profile.schema.json
  version int not null default 1,
  updated_at timestamptz not null default now()
);

-- ---------- Olaylar ----------
create table events (
  event_id uuid primary key,
  org_id uuid not null references orgs on delete cascade,
  line_id uuid references lines on delete set null,
  device_id text not null references devices on delete cascade,
  camera_id text not null,
  profile_id uuid,
  type text not null check (type in ('count', 'inspection', 'state', 'heartbeat')),
  ts timestamptz not null,
  body jsonb not null,
  received_at timestamptz not null default now()
);
create index events_line_ts on events (line_id, ts desc);
create index events_device_ts on events (device_id, ts desc);
create index events_nok on events (line_id, ts desc)
  where type = 'inspection' and (body -> 'inspection' ->> 'result') = 'nok';

create table minute_stats (
  line_id uuid not null references lines on delete cascade,
  camera_id text not null,
  minute timestamptz not null,
  count int not null default 0,
  ok int not null default 0,
  nok int not null default 0,
  primary key (line_id, camera_id, minute)
);
create index minute_stats_line_minute on minute_stats (line_id, minute desc);

create table line_state (
  line_id uuid primary key references lines on delete cascade,
  running boolean not null,
  since timestamptz not null,
  updated_at timestamptz not null default now()
);

create table alert_rules (                     -- n8n tarafından okunur
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  line_id uuid references lines on delete cascade,
  kind text not null check (kind in ('stopped', 'nok_rate', 'device_offline', 'rate_low', 'daily_report')),
  params jsonb not null default '{}',          -- ör. {"minutes":5} | {"threshold":0.03,"windowMin":15}
  channels jsonb not null default '{}',        -- ör. {"email":["a@b.com"],"telegramChatId":"..."}
  enabled boolean not null default true,
  last_fired_at timestamptz
);

-- ---------- Erişim (RLS) ----------
create or replace function is_org_member(p_org uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from org_members where org_id = p_org and user_id = auth.uid());
$$;

do $$
declare t text;
begin
  foreach t in array array['orgs','sites','lines','devices','pairing_codes','profiles','events','alert_rules'] loop
    execute format('alter table %I enable row level security', t);
  end loop;
end $$;
alter table org_members enable row level security;
alter table shifts enable row level security;
alter table minute_stats enable row level security;
alter table line_state enable row level security;

create policy orgs_read on orgs for select using (is_org_member(id));
create policy members_read on org_members for select using (is_org_member(org_id));
create policy sites_rw on sites for all using (is_org_member(org_id)) with check (is_org_member(org_id));
create policy lines_rw on lines for all using (is_org_member(org_id)) with check (is_org_member(org_id));
create policy shifts_rw on shifts for all
  using (exists (select 1 from lines l where l.id = line_id and is_org_member(l.org_id)))
  with check (exists (select 1 from lines l where l.id = line_id and is_org_member(l.org_id)));
create policy devices_read on devices for select using (is_org_member(org_id));
create policy devices_update on devices for update using (is_org_member(org_id)) with check (is_org_member(org_id));
create policy pairing_rw on pairing_codes for all using (is_org_member(org_id)) with check (is_org_member(org_id));
create policy profiles_rw on profiles for all using (is_org_member(org_id)) with check (is_org_member(org_id));
create policy events_read on events for select using (is_org_member(org_id));
create policy alerts_rw on alert_rules for all using (is_org_member(org_id)) with check (is_org_member(org_id));
create policy minute_read on minute_stats for select
  using (exists (select 1 from lines l where l.id = line_id and is_org_member(l.org_id)));
create policy state_read on line_state for select
  using (exists (select 1 from lines l where l.id = line_id and is_org_member(l.org_id)));
-- Not: events / minute_stats / line_state yazımı yalnızca aşağıdaki security definer fonksiyonlarla (service role).

-- ---------- Eşleme ----------
create or replace function pair_device(p_code text, p_kind text, p_model text, p_app_version text,
                                       p_name text, p_key_hash text)
returns table (device_id text, org_id uuid, line_id uuid)
language plpgsql security definer set search_path = public as $$
declare v pairing_codes;
begin
  select * into v from pairing_codes
   where code = p_code and used_at is null and expires_at > now()
   for update;
  if not found then
    raise exception 'invalid_or_expired_code' using errcode = 'P0001';
  end if;
  update pairing_codes set used_at = now() where code = p_code;
  return query
    insert into devices (org_id, line_id, kind, model, app_version, name, key_hash)
    values (v.org_id, v.line_id, p_kind, p_model, p_app_version, p_name, p_key_hash)
    returning devices.id, devices.org_id, devices.line_id;
end $$;

-- ---------- Ingest (idempotent + dakikalık özet) ----------
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
           coalesce(sum((body -> 'count' ->> 'delta')::int) filter (where type = 'count'), 0) as c,
           count(*) filter (where type = 'inspection' and body -> 'inspection' ->> 'result' = 'ok') as ok,
           count(*) filter (where type = 'inspection' and body -> 'inspection' ->> 'result' = 'nok') as nok
      from ins
     where type in ('count', 'inspection') and line_id is not null
     group by 1, 2, 3
  ), up as (
    insert into minute_stats as m (line_id, camera_id, minute, count, ok, nok)
    select line_id, camera_id, minute, c, ok, nok from agg
    on conflict (line_id, camera_id, minute) do update
      set count = m.count + excluded.count, ok = m.ok + excluded.ok, nok = m.nok + excluded.nok
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
revoke all on function pair_device(text, text, text, text, text, text) from public, anon, authenticated;

-- ---------- Realtime ----------
alter publication supabase_realtime add table minute_stats, line_state;

-- ---------- Depolama ----------
insert into storage.buckets (id, name, public) values ('nok-images', 'nok-images', false)
on conflict (id) do nothing;
create policy nok_images_read on storage.objects for select
  using (bucket_id = 'nok-images' and is_org_member(((storage.foldername(name))[1])::uuid));
