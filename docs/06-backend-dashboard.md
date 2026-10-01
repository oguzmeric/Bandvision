# 06 — Backend ve Dashboard

## 1. Supabase
- Şema: `supabase/migrations/0001_init.sql` (hazır, uygulanıp test edilmeli).
- Ingest: `supabase/functions/ingest/index.ts` (hazır iskelet). `--no-verify-jwt` ile dağıtılır; cihaz doğrulaması `X-Device-Key` ile.
  - `POST /ingest` → olay paketi; `ingest_events()` fonksiyonu tek işlemde idempotent ekleme + `minute_stats` güncellemesi + `line_state` + cihaz `last_seen_at`.
  - `POST /ingest/pair` → eşleme kodu ile cihaz kaydı, anahtar bir kez döner (DB'de yalnızca sha256).
  - `POST /ingest/upload-url` → NOK görseli için imzalı yükleme URL'si (`nok-images` deposu, yol `<orgId>/<lineId>/<gün>/...`).
- Toplamlar **yalnızca `minute_stats`**'tan okunur; `events` ham kayıt ve denetim içindir.
- Saklama: `events` 90 gün (pg_cron ile günlük silme), `minute_stats` süresiz, NOK görselleri 30 gün (depolama yaşam döngüsü ya da cron).
- Gerekirse büyük hacimde `events` aylık bölümlenir (F3 yük testine göre karar).

### Ölçek notu
`ingest_events` her pakette bir kez çalışır; 500 olaylık paket tek SQL turu. F3.1 kabul kriteri (10.000 olay/dk) yük testiyle doğrulanmalı (`k6` ya da Python betiği, 20 sahte cihaz).

## 2. OEE tanımları
Vardiya (`shifts`) içindeki planlı süre `P`, `line_state`'ten çalışma süresi `R`, `minute_stats`'tan sayım `N`, OK `O`, NOK `K`, hattın ideal hızı `I` (adet/dk):
- Kullanılabilirlik `A = R / P`
- Performans `Pf = N / (I · R_dk)` (I tanımlı değilse gösterilmez)
- Kalite `Q = O / (O + K)` (QC kapalıysa 1 kabul edilmez, "—" gösterilir)
- `OEE = A · Pf · Q`
`line_state` geçmişi için `events` içindeki `state` olayları kullanılır (vardiya penceresinde çalışıyor/durdu aralıkları).

## 3. Dashboard (`apps/dashboard`, Next.js 15 App Router, Supabase Auth)
Görsel dil ZNA kimliği; mevcut VMS Analitik (znaanaliz.com) bileşenleri ve giriş akışı (e-postaya tek kullanımlık kod) yeniden kullanılabilir.

| Sayfa | İçerik |
|---|---|
| `/` Hatlar | Kart başına: canlı sayaç (bugün), son 15 dk hız, çalışıyor/durdu rozeti, NOK oranı, cihaz sağlığı noktası. Realtime: `minute_stats`, `line_state` |
| `/lines/[id]` | Dakikalık sayım grafiği (seçilebilir aralık), vardiya kırılımı, OEE kartları, duruş zaman çizelgesi, OK/NOK oranı, boy sınıfı dağılımı |
| `/lines/[id]/nok` | NOK galerisi: görsel, nedenler, metrikler, zaman; nedene göre filtre; imzalı URL ile görüntüleme |
| `/devices` | Cihazlar: tür, hat, son görülme, fps, sıcaklık durumu, kuyruk derinliği, sürüm. "Eşleme QR'ı üret" (hat seçerek) |
| `/profiles` | Profil listesi ve JSON düzenleyici (şema doğrulamalı); cihazlara gönderim F6'da |
| `/alerts` | `alert_rules` düzenleme |
| `/reports` | Günlük/haftalık özet, CSV/Excel dışa aktarma |

Sorgu ilkeleri: sunucu bileşenlerinde RLS'li kullanıcı oturumu; grafikler için dakikalık veriyi aralığa göre 5 dk/saatlik toplayan SQL görünümleri (`time_bucket` yerine `date_trunc` + `generate_series`).
