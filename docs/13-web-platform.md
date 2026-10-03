# 13 — Web platformu: canlı izleme ve video analizi

Kullanıcı isteği (2026-10-02): telefonda yaptığımız canlı analiz ve galeriden çalıştırdığımız video analizi **web'den** de görülebilmeli ve yapılabilmeli.
`06-backend-dashboard.md` (F3) planının üzerine kurulur; o dokümandaki şema/ingest/OEE geçerlidir.

## Kararlar (kullanıcı, 2026-10-02)
| Konu | Karar |
|---|---|
| Canlı görünüm | **Sayılar + işaretli anlık kare.** Sayaç, grafik, OK/NOK, NOK fotoğrafları ve birkaç saniyede bir güncellenen işaretli anlık kare; anlık kare **hat bazında açılıp kapatılır** (varsayılan kapalı — "görüntü cihazdan çıkmaz" ilkesi). Kesintisiz video akışı yok. |
| Barındırma | Henüz karar yok → önce **yerel geliştirme**; her parça konteyner, bulut ya da kendi sunucuya taşınabilir. |
| Yüklenen video saklama | **7 gün** sonra video ve işaretli video otomatik silinir; analiz özeti kalır. |

## Mimari
```
iPhone / edge ──olaylar (+isteğe bağlı anlık kare)──► Supabase (ingest, Postgres, Storage, Realtime)
                                                              │
Tarayıcı ◄──── Next.js paneli (apps/dashboard) ◄──────────────┘
   │  video yükle                     ▲ iş durumu, sonuç dosyaları
   └────────► Analiz sunucusu (services/edge, bantvision.analyzer, FastAPI) ─ Python referans çekirdeği
```
- **Analiz sunucusu**, telefondaki ve masaüstündeki ile **aynı Python referans çekirdeğini** kullanır (`bantvision.video`): otomatik kalibrasyon, sayım, işaretli video, özet, CSV. Tarayıcı oynatabilsin diye işaretli video **H.264 (yuv420p, faststart)** olarak üretilir.
- İşler tek tek işlenir (CPU yoğun), kuyruk diskte kalıcıdır; sunucu yeniden başlarsa yarım kalan iş "başarısız: sunucu yeniden başladı" olur, kullanıcı yeniden başlatır.
- Saklama: `ANALYZER_RETENTION_DAYS` (varsayılan 7); süresi dolan işin dosyaları silinir, iş kaydı `expired` olarak özetiyle kalır.

## Sözleşmeler
- **Analiz işi:** `contracts/analysis-job.schema.json` (`bantvision.analysis-job.v1`), `02-contracts.md` §7.
- **Anlık kare (canlı):** W3'te `event.schema.json`'a eklenecek; önce sözleşme, sonra uygulamalar.

## Analiz sunucusu API (v1)
| Yöntem | Yol | Açıklama |
|---|---|---|
| `POST` | `/api/v1/jobs` | `multipart/form-data`: `file` (video), `options` (JSON, isteğe bağlı: `preset`, `truth`, `direction`, `roi`, `roiPolygon`, `line`, `countLine`, `bgRange`). `202` + iş |
| `GET` | `/api/v1/jobs` | Son işler (yeniden eskiye) |
| `GET` | `/api/v1/jobs/{id}` | İş: durum, ilerleme, sonuç |
| `GET` | `/api/v1/jobs/{id}/files/{ad}` | `annotated.mp4`, `counts.csv`, `profile.json`, `background.png` |
| `DELETE` | `/api/v1/jobs/{id}` | İşi ve dosyalarını sil (sürüyorsa iptal) |
| `GET` | `/healthz` | Sağlık |

Güvenlik: `ANALYZER_TOKEN` tanımlıysa `Authorization: Bearer <token>` zorunlu (panelin sunucu tarafı çağırır; tarayıcıya verilmez). Yükleme sınırı `ANALYZER_MAX_UPLOAD_MB` (varsayılan 2048), video olmayan dosya reddedilir. CORS: `ANALYZER_CORS_ORIGINS`.

## Fazlar
| Faz | İçerik | Kabul |
|---|---|---|
| **W1** | Analiz sunucusu (FastAPI) + sözleşme + testler; Dockerfile | Test klibi yüklenir → sayım Python referansıyla aynı, işaretli H.264 video, CSV; 7 gün kuralı test edilir |
| **W2** ✅ | `apps/dashboard` (Next.js 15): **Video analizi** sayfası — yükle, ilerleme, işaretli video oynatıcı, sayım/doğruluk, CSV indir, geçmiş. Çalıştırma: `apps/dashboard/README.md` | Tarayıcıda uçtan uca (Playwright, CI `dashboard` işi) |
| **W3** | Canlı: Supabase yerel (Docker), ingest, iPhone olay gönderimi (outbox), hat başına isteğe bağlı anlık kare; panelde **Hatlar** ve hat sayfası (Realtime) | iPhone'dan sayım panelde ≤ 5 sn'de görünür; anlık kare kapalıyken hiç görüntü gitmez |
| **W4** | NOK galerisi, raporlar, barındırma (karar sonrası), giriş/organizasyon | `06` kabul kriterleri |
