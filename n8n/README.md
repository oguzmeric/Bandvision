# n8n Uyarı Akışları

Kaynak: Supabase (`alert_rules`, `minute_stats`, `line_state`, `devices`). n8n'de Postgres kimlik bilgisi olarak Supabase bağlantı dizesi (salt okunur rol önerilir; `alert_rules.last_fired_at` güncellemesi için yalnızca o tabloya yazma yetkisi).

Her akış: **Schedule (1 dk)** → **Postgres sorgusu** → **IF (satır var mı)** → **Switch (kanal)** → E-posta / Telegram / SMS (Netgsm vb. HTTP) → **Postgres: last_fired_at = now()**. Aynı kural `params.cooldownMin` (varsayılan 15) dolmadan tekrar tetiklenmez.

## 1. Bant durdu (`kind = 'stopped'`)
```sql
select r.id, r.channels, l.name as line, s.since
from alert_rules r
join lines l on l.id = r.line_id
join line_state s on s.line_id = r.line_id
where r.enabled and r.kind = 'stopped'
  and s.running = false
  and s.since < now() - make_interval(mins => coalesce((r.params->>'minutes')::int, 5))
  and (r.last_fired_at is null or r.last_fired_at < now() - make_interval(mins => coalesce((r.params->>'cooldownMin')::int, 15)));
```
Mesaj: "⚠️ {line} {since} saatinden beri duruyor."

## 2. NOK oranı (`kind = 'nok_rate'`)
```sql
select r.id, r.channels, l.name as line, sum(m.nok)::float / nullif(sum(m.ok + m.nok), 0) as rate, sum(m.ok + m.nok) as n
from alert_rules r
join lines l on l.id = r.line_id
join minute_stats m on m.line_id = r.line_id
 and m.minute > now() - make_interval(mins => coalesce((r.params->>'windowMin')::int, 15))
where r.enabled and r.kind = 'nok_rate'
  and (r.last_fired_at is null or r.last_fired_at < now() - make_interval(mins => coalesce((r.params->>'cooldownMin')::int, 15)))
group by r.id, r.channels, l.name, r.params
having sum(m.ok + m.nok) >= coalesce((r.params->>'minSamples')::int, 50)
   and sum(m.nok)::float / nullif(sum(m.ok + m.nok), 0) > (r.params->>'threshold')::float;
```

## 3. Cihaz çevrimdışı (`kind = 'device_offline'`)
`devices.last_seen_at < now() - interval '2 minutes'` (kuralın hattındaki cihazlar). Mesaja son heartbeat (`fps`, `temperatureState`, `queueDepth`) eklenir.

## 4. Günlük rapor (`kind = 'daily_report'`)
Her gün vardiya bitiminde: hat başına toplam, OK/NOK, duruş süresi, en çok görülen NOK nedenleri. HTML e-posta; dashboard bağlantısı.

## Webhook modu (backend'siz kurulum)
Cihaz doğrudan n8n Webhook düğümüne `bantvision.batch.v1` gönderebilir (`02-contracts.md` §3). Bu modda n8n olayları kendi veri tablosunda (n8n Data Tables) tutar; küçük tek hatlı müşteriler için.
