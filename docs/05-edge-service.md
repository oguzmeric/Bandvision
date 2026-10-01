# 05 — Edge Servisi

Konum: `services/edge`. Python 3.11+, FastAPI, OpenCV, numpy. Çekirdek (`bantvision/core`) hazır ve test edilmiş; bu doküman servis katmanını tanımlar.

## 1. Donanım
- **Önerilen:** Intel N100 / N150 mini PC (8–16 GB RAM, 256 GB SSD), Ubuntu 24.04 Server, **kablolu Ethernet**.
- Hedef kapasite: 640×360 alt akışta 25 fps ile kutu başına 4 kamera (F2'de ölçülüp dokümana yazılacak).
- Raspberry Pi 5 tek kamera için yeterli olabilir; ölç ve not et.
- AHD: kamera XVR'a bağlıysa XVR'ın RTSP'si kullanılır. XVR yoksa USB AHD yakalama kartı (UVC uyumlu olanı seç; V4L2 ile `/dev/videoN`).

## 2. Klasör yapısı (hedef)
```
services/edge/
  bantvision/
    core/            # hazır: profile, segmenter, tracker, qc, pipeline
    sim.py           # hazır: sentetik bant
    sources/         # FrameSource: rtsp.py, usb.py, file.py (test/replay)
    worker.py        # kamera başına süreç: kaynak → pipeline → olaylar
    outbox.py        # SQLite kuyruk
    uploader.py      # batch gönderici
    io_bridge.py     # ESP32 UDP istemcisi
    codes.py         # barkod (zxing-cpp) / metin (opsiyonel)
    discovery.py     # ONVIF WS-Discovery, mDNS yayını
    api/             # FastAPI: app.py, routes_*.py, mjpeg.py, overlay.py
    config.py        # YAML + ortam değişkenleri
  tests/
  Dockerfile, docker-compose.yml
```

## 3. Bileşenler

### 3.1 FrameSource
```python
class FrameSource(Protocol):
    def open(self) -> None: ...
    def read(self) -> tuple[np.ndarray, float] | None   # (BGR kare, monotonic zaman damgası)
    def close(self) -> None: ...
    info: SourceInfo  # width, height, nominal_fps, kind
```
- **RTSP:** `cv2.VideoCapture(url, cv2.CAP_FFMPEG)`, `OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp|stimeout;5000000"`. Okuma ayrı iş parçacığında; işleme kuyruğu boyutu 4. Kuyruk doluysa **en eskiyi at** ve `dropped_frames` sayacını artır (heartbeat'te raporla). Zaman damgası okuma anında `time.monotonic()`.
- Bağlantı koparsa üstel bekleme (1→30 sn), `state` olayı `source_lost` / `source_restored`; tekrar bağlanınca izler sıfırlanır, arka plan korunur.
- Donanım çözme: Intel'de `cv2.CAP_PROP_HW_ACCELERATION = cv2.VIDEO_ACCELERATION_ANY` dene; çalışmazsa yazılım.
- **USB:** `cv2.VideoCapture(index, cv2.CAP_V4L2)`, MJPG FOURCC, 720p/25.
- **File:** test ve "kayıttan tekrar oynatma" için (sahada kaydedilen videoyla parametre ayarı).

### 3.2 Worker
- Kamera başına ayrı **süreç** (`multiprocessing`, GIL'den kaçınmak için). Ana süreçle `multiprocessing.Queue` üzerinden: komutlar (profil güncelle, kalibrasyon başlat, sayaç sıfırla) ve sonuçlar (durum özeti 10 Hz, olaylar).
- Her `FrameResult` için: sayım → `count` olayı; QC → `inspection` olayı (+ NOK görseli `data/nok/<tarih>/<cameraId>-<trackId>.jpg`); `state_change` → `state` olayı; I/O çıkışları (`07`).
- Barkod/metin: worker içinde küçük bir `ThreadPoolExecutor(2)`; sonuç 500 ms içinde gelmezse eksik sayılır, `inspection` olayı sonuçla birlikte bir kez gönderilir.
- Profil değişince `Pipeline.set_profile`; `processingWidth` değiştiyse arka plan sıfırlanır.

### 3.3 Outbox ve gönderici
SQLite (WAL), `data/outbox.db`:
```sql
CREATE TABLE outbox (seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE, body TEXT NOT NULL,
                     created_at REAL NOT NULL, sent_at REAL);
CREATE INDEX outbox_unsent ON outbox(sent_at) WHERE sent_at IS NULL;
```
- Gönderici 2 sn'de bir en fazla 500 gönderilmemiş olayı `bantvision.batch.v1` olarak yollar; başarıda `sent_at` doldurur. 7 günden eski gönderilmişler silinir. Disk kotası: 1 GB (aşılırsa en eski gönderilmişler, sonra en eski heartbeat'ler silinir; sayım/inspection olayları asla).
- NOK görselleri: imzalı URL ile yükleme (`02` §3), başarısızsa yeniden denenir.

### 3.4 Yapılandırma
`/etc/bantvision/config.yaml` (Docker'da volume):
```yaml
device:
  name: "Edge-01"
  ingestUrl: "https://<proje>.supabase.co/functions/v1/ingest"
  deviceKeyFile: "/data/device.key"
  idleSeconds: 30
api:
  bind: "0.0.0.0:8080"
  tokenFile: "/data/api.token"      # yerel API için Bearer token
cameras:
  - id: "cam1"
    name: "Hat A çıkış"
    source: { kind: rtsp, url: "rtsp://user:pass@192.168.1.64:554/Streaming/Channels/102" }
    profileFile: "/data/profiles/cam1.json"
    qcSource: { kind: rtsp, url: "rtsp://.../Channels/101" }   # opsiyonel: NOK görseli/barkod için ana akış
```
Not: `qcSource` verilirse QC kırpıntısı ana akıştan, zaman damgasına en yakın kareden alınır (alt ve ana akış ayrı okunur; en fazla 200 ms fark kabul).

## 4. Yerel API
Tümü `Authorization: Bearer <token>` (mDNS ile bulan iOS uygulaması tokenı eşleme sırasında QR'dan alır).

| Yöntem | Yol | Açıklama |
|---|---|---|
| GET | `/health` | sürüm, çalışma süresi |
| GET | `/cameras` | kameralar + anlık durum (fps, total, running, okNok) |
| POST | `/cameras` | kamera ekle (kaynak tanımı) |
| DELETE | `/cameras/{id}` | |
| GET | `/cameras/{id}/snapshot.jpg?overlay=1&w=720` | son kare (overlay'li/overlay'siz) |
| GET | `/cameras/{id}/preview` | MJPEG (`multipart/x-mixed-replace`), overlay'li, ≤ 10 fps |
| WS | `/cameras/{id}/state` | 10 Hz: `{frameSize, blobs[], tracks[], fps, total, ok, nok, calibration}` |
| GET/PUT | `/cameras/{id}/profile` | `contracts/product-profile.schema.json` |
| POST | `/cameras/{id}/calibration/background` | boş bant öğren |
| POST | `/cameras/{id}/calibration/sample?target=8` | örnek ürün öğren |
| POST | `/cameras/{id}/calibration/cancel` | |
| POST | `/cameras/{id}/counter/reset` | |
| POST | `/cameras/{id}/record?seconds=60` | sahadan ham video kaydı (ayar için) |
| GET | `/discovery/onvif` | ağdaki ONVIF kameralar + RTSP profil URI'leri |
| POST | `/io/test?channel=1` | I/O köprüsüne test darbesi |

Overlay çizimi iOS `OverlayView` ile aynı renkler: ROI sarı, çizgi turuncu, leke yeşil, iz noktası beyaz/camgöbeği, iz kimliği onaltılık.

## 5. Keşif
- **ONVIF:** WS-Discovery ile cihazları bul, `GetProfiles` + `GetStreamUri` ile alt/ana akış URI'lerini getir (kullanıcı adı/şifre gerekir).
- **mDNS:** `_bantvision._tcp.local` yayını; TXT: `id`, `name`, `version`, `api=1`.

## 6. Paketleme
- `Dockerfile`: `python:3.11-slim` + `libgl1` gerekmez (headless), `ffmpeg` kütüphaneleri OpenCV wheel'inde. Kullanıcı root değil.
- `docker-compose.yml`: `network_mode: host` (mDNS ve ONVIF çok yayını için), `/data` ve `/etc/bantvision` volume, `restart: unless-stopped`, `/dev/dri` (VAAPI) ve USB yakalama için `/dev/video*` cihazları.
- Güncelleme: imaj etiketi + `docker compose pull && up -d`. (Uzaktan güncelleme F6 sonrası.)

## 7. Testler
- Çekirdek: `tests/test_synthetic.py` (hazır).
- Kaynak: `file` kaynağıyla sentetik videoyu (`sim` → MP4) oynat, uçtan uca olayların outbox'a düştüğünü doğrula.
- RTSP: CI'da `mediamtx` konteyneri ile sentetik videoyu RTSP olarak yayınla, bağlantı kopma/yeniden bağlanma senaryosu.
- Uploader: sahte ingest sunucusu (500 döndür → tekrar dene; 400 → düşür; çift gönderimde idempotent).
