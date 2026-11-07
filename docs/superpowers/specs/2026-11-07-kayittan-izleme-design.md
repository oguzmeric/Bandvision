# Kayıttan izleme (kayıt cihazı arşivi) — tasarım (2026-11-07)

## Amaç ve neden
Müşterilerin kayıt cihazları (TRASSIR, Hikvision, Dahua) kaydı zaten tutuyor; BantVision'da bir alarm ya da sayım olayı
görülünce "o anda ne oldu?" sorusu için başka bir program açmak gerekiyor. Bu paket, panelde seçilen kameranın **kayıt
cihazındaki arşivini** oynatır: tarih/saat seçimi, takvim ve zaman çizelgesi (kayıt olan aralıklar), duraklat/sürdür, hız,
ileri-geri sarma ve TRASSIR'da dışa aktarma. Alarm kaydından tek tıkla o ana gidilir. Kullanıcının yol haritası
(2026-11-06): in-flight işler → **kayıttan izleme** → olay algılama paketi → exe → lisans.

Kullanıcı soruları atlayıp doğrudan başlamamı istediği için (2026-11-04 "soruları atla, direkt başla"; 2026-11-07 "devam")
aşağıdaki kararlar bana ait; yanlışsa ucuz düzeltilir. Donanım: ofiste yalnız TRASSIR var (ağda değilken doğrulama ertelenir);
Hikvision/Dahua cihazı olup olmadığı sorulacak.

## Hedefler
1. Panelde **Kayıttan izleme** sayfası (`/archive`, İzleme grubu): kayıt cihazı kanalı seç → takvim (kayıt olan günler) →
   24 saatlik zaman çizelgesi (kayıt olan aralıklar dolu) → oynatıcı (MJPEG, canlıdaki gibi `<img>`) → kumanda: duraklat/sürdür,
   hız (TRASSIR 1–16×; Hikvision/Dahua 1/2/4×), ±10 sn, ±1 dk, saat göstergesi, çizelgeye tıklayınca o ana atlama.
2. **Markalar:** TRASSIR (SDK, ofis NVR'ında doğrulanır), Hikvision (ISAPI + oynatma RTSP'si), Dahua (CGI + oynatma RTSP'si).
   Hikvision ve Dahua adres/biçimleri resmî belge ulaşılamadığı için ikincil kaynaktan; **cihazda doğrulanana dek "doğrulanmadı"**
   etiketiyle belgelenir, arayüz cihazın reddini Türkçe gösterir.
3. **Alarmdan kayda:** alarm kaydı kaynak ve kanal kimliğini taşır; alarm penceresinde "Kayıt cihazında izle" düğmesi
   `/archive?source=&channel=&t=<alarm anı − 10 sn>` açar (kamera bir kayıt cihazı kanalıysa).
4. **Dışa aktarma (TRASSIR):** seçilen aralık (≤ 30 dk) kayıt cihazının `jit-export` görevine verilir, hazır olan .mp4 panel
   üzerinden tarayıcıya iner. Hikvision/Dahua'da düğme pasif ("Bu kayıt cihazında dışa aktarma henüz desteklenmiyor.").
5. **Test kancası:** dosya kaynağı (`ANALYZER_ALLOW_FILE_SOURCES=1`, yalnız test) arşiv gibi davranır: `t` = dosya içindeki
   saniye; takvim/çizelge dosyanın süresi. Böylece gerçek yığın e2e testleri cihazsız çalışır.

## Hedef dışı (v1)
- Uniview ve genel ONVIF Profile G: Uniview'ın oynatma adresi belgede yok; ONVIF Replay `RTSP Range` başlığı ister, OpenCV'nin
  RTSP istemcisi bunu veremiyor (ayrı RTSP istemcisi gerekir). İleride.
- Hikvision/Dahua'da dışa aktarma (ISAPI `download`, Dahua `loadfile`): cihazda doğrulanmadan yazılmaz.
- Arşiv üzerinde analiz (sayım/poz): "Video ile test" zaten var; arşivden otomatik video çekip analiz etmek ileride.
- iPhone: PC paketi.
- Kayıt cihazındaki sesi oynatmak.

## Kısıtlar
- Görüntü cihazdan çıkmaz: arşiv kareleri yalnız panel oturumuna MJPEG olarak gider; dışa aktarılan dosya yalnız tarayıcıya
  iner, hiçbir yere gönderilmez; disk'te tutulmaz (akıtılır). Telegram'a hiçbir şey gitmez.
- Kayıt cihazı şifresi `secrets.json`'da kalır; API yanıtlarında, günlükte ve adreslerde (günlük süzgeci) görünmez.
- Zaman: API'de her yerde **epoch saniye (UTC)**. Bağdaştırıcı cihaz biçimine çevirir: Hikvision UTC (`…Z`), Dahua ve TRASSIR
  cihazın yerel saati = **bu bilgisayarın saat dilimi varsayımı** (belgelenir; cihaz başka dilimdeyse kayma olur — ileride kaynak
  ayarı).
- Kaynak koruması: aynı anda en çok **2** arşiv oynatıcı (`ARCHIVE_MAX_PLAYERS`); üçüncü istek 429 "En çok 2 kayıt aynı anda
  izlenebilir." 60 sn izleyicisiz (akış ya da durum isteği yok) oynatıcı kapanır. RTSP açılışları mevcut `open_gate`
  kapısından `VIEWER` önceliğiyle geçer (canlı oturumlar önde).
- Canlı izleme etkilenmez: arşiv oynatıcı ayrı iş parçacığı ve ayrı sınıf; `ViewHub` değişmez.

## Nasıl çalışır
### Analiz sunucusu (`services/edge/bantvision/live/archive.py`, API `live/api.py`)
- **`ArchiveClient` bağdaştırıcısı** (marka başına, `recorders.py`'deki istemciyi sarar):
  - `stream_url(channel, start_epoch, end_epoch | None, substream, speed) -> str` — şifresiz RTSP (TRASSIR: `get_video
    stream=archive_main|archive_sub` jetonu + `archive_command play start/stop/speed`; Hikvision
    `/Streaming/tracks/<kanal>0<1|2>?starttime=…Z&endtime=…Z`; Dahua `/cam/playback?channel=&subtype=&starttime=&endtime=`).
  - `calendar(channel, year, month) -> set[int]` kayıt olan günler (TRASSIR `archive_status type=calendar`; Hikvision
    `record/tracks/<id>/dailyDistribution`; Dahua ay aralığında `mediaFileFind` sonuçlarından).
  - `timeline(channel, day_start_epoch) -> list[tuple[float, float]]` o günün kayıt aralıkları (TRASSIR `type=timeline`;
    Hikvision `ContentMgmt/search`; Dahua `mediaFileFind`). Bitişik/örtüşen aralıklar birleştirilir.
  - `export(channel, start, end) -> Iterator[bytes]` yalnız TRASSIR (`jit-export-create-task` → `jit-export-download`);
    diğerleri `RecorderError("unsupported")` → 501.
  - `supports_speed: tuple[int, ...]` (TRASSIR `(1,2,4,8,16)`; diğerleri `(1,2,4)` istemci tarafı kare atlama).
  - `keep_alive(url)` TRASSIR jetonu için (canlıdaki gibi `?ping`).
  - Hikvision/Dahua için `_DeviceHTTP.post(path, body, content_type)` eklenir (ISAPI arama XML gövdesiyle).
- **`ArchivePlayer`**: kendi iş parçacığı; `open_gate.resolve_and_open(..., VIEWER)` ile açar, kareleri okur, en çok 960 px'e
  küçültür, son kareyi tutar (`seq`, durum: `connecting|playing|paused|ended|error`, `message`, `at` epoch sn, `fps`).
  - **Konum:** `at = start + okunan_kare / kare_hızı × hız` (kare hızı `CAP_PROP_FPS`, 0 ise 25). TRASSIR durum sorgusu
    kullanılmaz (biçimi doğrulanmadı).
  - **Hız:** TRASSIR'da komutun `speed`'i (cihaz atlar); Hikvision/Dahua'da her `hız`. kare gösterilir (çözme sürer, yalnız
    çıktı seyrelir; bu yüzden 4× üstü yok).
  - **Duraklat / sürdür / sar / hız değiştir = tek yol:** okuma durur, yakalama kapanır (TRASSIR'da `archive_command stop`),
    yeni konumdan yeniden açılır. Duraklamada son kare kalır ve `at` sabit. Yeniden açılış 1–3 sn sürer; panel "Sarılıyor…"
    gösterir. (Tek kod yolu: üç markada da aynı davranış, jeton tazelenir.)
  - **Akış bitti** (`end` ya da kayıt boşluğu): `ended`, son kare kalır; panel "Bu aralıkta kayıt bitti" der ve çizelgedeki bir
    sonraki aralığa atlama düğmesi verir.
  - Akış 20 sn kare vermezse `error` "Kayıt cihazından görüntü gelmedi." (yeniden bağlanma yok; kullanıcı sürdürür).
- **`ArchiveManager`**: oynatıcı tablosu (`id → ArchivePlayer`), 2 sınırı, 60 sn boşta temizlik (mevcut reaper kalıbı),
  takvim/çizelge çağrıları (ağa çıkar; sonuç 60 sn önbellek), dışa aktarma kilidi (TRASSIR tek görev).

### API (`/api/v1/live/archive/…`, panel vekili değişmeden geçer)
| Yöntem | Yol | İş |
|---|---|---|
| `GET` | `/archive/calendar?source=&channel=&year=&month=` | `{days: [1, 3, …]}` |
| `GET` | `/archive/timeline?source=&channel=&day=<epoch gün başı>` | `{ranges: [[başlangıç, bitiş], …]}` epoch sn |
| `POST` | `/archive/players` `{sourceId, channelId, at, speed?, substream?}` | `201` oynatıcı görünümü; 3. oynatıcı `429` |
| `GET` | `/archive/players/{id}` | `{id, sourceId, channelId, name, state, message, at, speed, speeds, fps, canExport}` |
| `GET` | `/archive/players/{id}/stream` | MJPEG (canlıdaki `_mjpeg`) |
| `POST` | `/archive/players/{id}/actions` `{action: pause\|resume\|seek\|speed, at?, speed?}` | görünüm |
| `DELETE` | `/archive/players/{id}` | `204` |
| `POST` | `/archive/export` `{sourceId, channelId, start, end}` | `video/mp4` akışı, `Content-Disposition: attachment;
filename="<kamera>-<tarih-saat>.mp4"`; `start<end`, `end−start ≤ 1800`; TRASSIR dışı `501`; süren görev varken `409` |

Hatalar `RecorderError` → mevcut `_err` eşlemesi (Türkçe, 502/401 ayrımı). Kaynak silinmişse `404 "Kaynak bulunamadı."`.

### Panel (`apps/dashboard`)
- `src/lib/nav.ts`: İzleme grubuna "Kayıttan izleme" (`/archive`), Canlı izleme'nin altına.
- `src/app/(panel)/archive/page.tsx` + `src/components/archive/*`: `ArchiveView` (kamera seçici: yalnız kayıt cihazı kanalları,
  kaynak+kanal listesi mevcut `GET /sources`, `/sources/{id}/channels`), `Calendar` (ay gezgini; kayıtlı günler koyu; bugün
  varsayılan), `Timeline` (24 saat; dolu aralıklar; imleç; tıklayınca seek; klavye ←/→ 10 sn, Shift ile 1 dk), `Player`
  (`<img src="/api/live/archive/players/<id>/stream">`, durum/ileti üstte; saat `HH:MM:SS`; kumanda düğmeleri; hız açılır
  kutusu `speeds`'ten), `ExportDialog` (başlangıç/bitiş varsayılan: imleç ±2 dk; süre ≤ 30 dk; indirme `<a download>` ile
  `POST`'un yanıtı blob'a alınmadan — form `POST` yerine `fetch` + `Blob` + `URL.createObjectURL`, ilerleme yok, 30 dk sınırı).
- Durum yoklama 1 sn (`GET /players/{id}`); sayfa kapanınca `DELETE` (`navigator.sendBeacon` yoksa `keepalive: true`).
- Derin bağlantı: `/archive?source=&channel=&t=` sayfa açılışında kamerayı seçer ve `t`'den oynatır.
- Alarm penceresi (`AlarmViewer`): alarm kaydında `sourceId` varsa "Kayıt cihazında izle" düğmesi.
- Erişilebilirlik: canlı izlemedeki kalıp (odak sırası, `aria-live` iletiler, klavye kısayolları listesi "?" ile).

### Alarm kaydı
`alarms.json` kaydına `sourceId` ve `channelId` (isteğe bağlı; eski kayıtlarda yok → düğme yok) eklenir; `AlarmStore.add`
oturumdan alır. Sözleşme (`contracts/`) etkilenmez (canlı API, panel içi).

### Belgeler
- `docs/13-web-platform.md`: yeni bölüm "Kayıttan izleme (`/archive`)" (davranış, API tablosu, marka notları, doğrulanmadı
  etiketleri, zaman dilimi varsayımı, KVKK satırı).
- `docs/08-trassir-integration.md`: arşiv SDK uçları (doğrulanan/doğrulanmayan), açık soru 5 kapanır.
- `docs/12-durum.md`: paket satırı + donanım doğrulama listesi (TRASSIR ofis NVR; Hikvision/Dahua cihaz bulununca).
- Belgelerde cihaz modeli, IP, yol, sır adı yok (mevcut kural).

## Doğrulama
- Birim: adres/zaman biçimleri (üç marka, UTC/yerel), takvim/çizelge ayrıştırıcıları (örnek yanıtlar: TRASSIR SDK belgesindeki
  JSON, ISAPI XML, Dahua `items[n]` metni), aralık birleştirme, `at` hesabı, hız/kare atlama, 2 oynatıcı sınırı, boşta kapanma,
  duraklat/sürdür/sar yeniden açılışı, dışa aktarma sınırları ve 501/409, alarm kaydındaki yeni alanlar.
- Sahte NVR (`tools/mock_nvr.py`, TRASSIR HTTPS + Hikvision/Dahua Digest) arşiv uçlarını da sunar: `get_video stream=archive_*`, `archive_command`,
  `archive_status calendar|timeline`, `jit-export-*`; API testleri TestClient ile.
- E2E (Playwright): arayüz testleri sahte analiz yanıtlarıyla (takvim, çizelge, oynatıcı durumları, 429/501/409 iletileri,
  klavye); gerçek yığın: dosya kaynağıyla oynatıcı akıtır, seek `at`'i değiştirir, duraklat son kareyi tutar.
- Donanım (ağ gelince, salt okunur): TRASSIR'da takvim/çizelge biçimi, `play` sonrası ilk kare süresi, `speed`, `stop`, jeton
  ömrü, `jit-export` akışı; sonuçlar docs/12'ye. Hikvision/Dahua: cihaz bulununca aynı liste.

## Kabul kriterleri
1. Ofis TRASSIR'ında bir kanalın dünkü kaydı panelden oynar; çizelgeye tıklayınca 3 sn içinde o andan sürer; duraklat/sürdür ve
   4× çalışır; 2 dakikalık aralık .mp4 olarak iner.
2. Alarm penceresinden "Kayıt cihazında izle" alarm anından 10 sn önceye açar.
3. Hikvision/Dahua: birim testleri belgeye göre geçer; arayüz cihaz hatasını Türkçe gösterir; belgede "cihazda doğrulanmadı".
4. Canlı izleme ve analiz oturumları arşiv oynarken ölçülebilir biçimde yavaşlamaz (kapı önceliği; 2 oynatıcı sınırı).
5. Tüm edge testleri, dashboard birim + e2e, ruff, tsc, CI yeşil; `docs/13`, `08`, `12` güncel.
