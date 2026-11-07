# Kayıttan izleme (kayıt cihazı arşivi) — plan (2026-11-07)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Görevler `### Task N` başlıklarıyla.

**Goal:** Panelde kayıt cihazı kanalının arşivini oynatmak (takvim, zaman çizelgesi, duraklat/sürdür, hız, sarma), alarmdan o
ana gitmek, TRASSIR'da dışa aktarmak. **Spec:** `docs/superpowers/specs/2026-11-07-kayittan-izleme-design.md` (bağlayıcı).

**Architecture:** Analiz sunucusunda `live/archive.py`: marka bağdaştırıcıları (`ArchiveClient`), `ArchivePlayer` (iş parçacığı,
MJPEG için son kare), `ArchiveManager` (2 oynatıcı sınırı, boşta kapanma, önbellek, dışa aktarma kilidi); API `/api/v1/live/archive/…`
(panel vekili değişmez). Panel: `/archive` sayfası (`src/components/archive/*`), `AlarmViewer`'da düğme. Dosya kaynağı test kancası.

**Tech:** Python 3.11+, FastAPI, OpenCV, httpx (mevcut); Next.js 15, Playwright (mevcut). Yeni bağımlılık yok.

## Global constraints
- Kullanıcıya görünen metin Türkçe; tanımlayıcılar İngilizce. Tip ipuçları zorunlu; `ruff`, `pytest`, `tsc`, unit, e2e yeşil.
- Görüntü ve dışa aktarılan dosya yalnız panel oturumuna gider; diske yazılmaz; Telegram'a hiçbir şey gitmez.
- Şifre/jeton hiçbir yanıtta, günlükte, hata iletisinde görünmez (`redact_credentials`, mevcut günlük süzgeci).
- API zamanları epoch saniye (UTC, float). Hikvision'a UTC (`Z`), Dahua ve TRASSIR'a bu bilgisayarın yerel saati.
- Belgelerde cihaz modeli, IP, dosya yolu, sır adı yok. Hikvision/Dahua uçları "cihazda doğrulanmadı" etiketiyle.
- Paylaşılan Playwright portları (3100, 3101, 3102, 3118, 8091, 8092, 8098) koşmadan önce boş olmalı; hiçbir süreç öldürülmez.
- Commit iletileri Türkçe, sonunda `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Rulings (bağlayıcı)
R1. **Tek kumanda yolu:** duraklat, sürdür, sar ve hız değişimi = okuma durur, yakalama kapanır (TRASSIR'da `archive_command
    stop`), yeni konum/hızla yeniden açılır. Duraklamada son kare ve `at` sabit kalır. Panel geçişte "Sarılıyor…" gösterir.
R2. **Konum:** `at = start + okunan_kare / fps × hız`; `fps = CAP_PROP_FPS` (0 ya da >120 ise 25). Hikvision/Dahua/dosya hızı
    istemci tarafı kare atlama (`hız`. karede bir yayımlanır; `speeds = (1, 2, 4)`); TRASSIR `speeds = (1, 2, 4, 8, 16)` cihazda.
R3. **Sınırlar:** `ARCHIVE_MAX_PLAYERS = 2` (3. istek `429` "En çok 2 kayıt aynı anda izlenebilir."); `ARCHIVE_IDLE_S = 60`
    (akış ya da durum isteği gelmeyen oynatıcı kapanır, reaper 10 sn'de bir); `ARCHIVE_NO_FRAME_S = 20` (kare gelmezse `error`
    "Kayıt cihazından görüntü gelmedi."); dışa aktarma `end − start ≤ 1800` sn, tek görev (`409` "Bir dışa aktarma sürüyor.").
R4. **Açılış kapısı:** oynatıcı `open_gate.resolve_and_open(url_fn, open_capture, open_gate.VIEWER)` kullanır (canlı oturumlar
    önde). Kare 960 px'e küçültülür (`viewer.downscale`), salt okunur (`viewer._readonly`).
R5. **Takvim/çizelge önbelleği:** `(source, channel, year, month)` ve `(source, channel, day)` anahtarıyla 60 sn; hata önbelleğe
    girmez. Aralıklar birleştirilir: örtüşen ya da ≤ 2 sn boşluklu aralıklar tek aralık.
R6. **TRASSIR çizelgesi:** `timeline(channel, day)` = arşiv jetonu al → `archive_command play start=<gün 00:00:00>
    stop=<gün 23:59:59> speed=1 token=` → `archive_status type=timeline` (boşsa 0,5 sn arayla en çok 3 deneme) →
    `archive_command stop`. `day_start` dönen gün istenenle eşleşmezse boş liste + günlük uyarısı. Takvim `type=calendar`
    (yanıttaki `calendar` listesindeki `YYYY-MM-DD` dizgileri). **Ofis NVR'ında doğrulanacak**; biçim farklıysa ayrıştırıcı düzelir.
R7. **Hikvision (doğrulanmadı):** iz kimliği `kanal_no × 100 + (2 alt | 1 ana)`. Oynatma
    `rtsp://host:rtsp_port/Streaming/tracks/<iz>?starttime=YYYYMMDDTHHMMSSZ&endtime=YYYYMMDDTHHMMSSZ` (UTC; kimlik bilgisi
    `with_credentials`). Çizelge `POST /ISAPI/ContentMgmt/search` gövde
    `<CMSearchDescription><searchID>{uuid}</searchID><trackIDList><trackID>{iz}</trackID></trackIDList><timeSpanList><timeSpan>
    <startTime>YYYY-MM-DDTHH:MM:SSZ</startTime><endTime>…</endTime></timeSpan></timeSpanList><maxResults>400</maxResults>
    <searchResultPostion>{n}</searchResultPostion><metadataList><metadataDescriptor>//recordType.meta.std-cgi.com
    </metadataDescriptor></metadataList></CMSearchDescription>`; yanıt `<CMSearchResult>` içinde `<responseStatusStrg>OK|MORE
    |NO MATCHES</responseStatusStrg>` ve `<matchList><searchMatchItem><timeSpan><startTime/><endTime/>`; `MORE` ise
    `searchResultPostion += 400` ile sürer (en çok 10 sayfa). Takvim `POST /ISAPI/ContentMgmt/record/tracks/<iz>/dailyDistribution`
    gövde `<trackDailyParam><year>Y</year><monthOfYear>M</monthOfYear></trackDailyParam>`; yanıt `<dayList><day><dayOfMonth>D
    </dayOfMonth><record>true|false</record>`. XML ad alanı yok sayılır (`_local_name`).
R8. **Dahua (doğrulanmadı):** oynatma `rtsp://host:rtsp_port/cam/playback?channel=<n>&subtype=<0 ana|1 alt>&starttime=
    YYYY_MM_DD_HH_MM_SS&endtime=…` (yerel saat). Çizelge `GET /cgi-bin/mediaFileFind.cgi?action=factory.create` → `result=<id>`;
    `action=findFile&object=<id>&condition.Channel=<n>&condition.StartTime=YYYY-MM-DD HH:MM:SS&condition.EndTime=…
    &condition.Types[0]=dav` → `OK`; `action=findNextFile&object=<id>&count=100` → `found=<k>` ve `items[i].StartTime=`,
    `items[i].EndTime=` satırları; `k == 100` iken sürer (en çok 50 sayfa); sonunda `action=close` ve `action=destroy`.
    Takvim: ayın tamamı tek `findFile` aralığı, günler sonuçlardan. Kanal numarası 1 tabanlı varsayılır (doğrulanacak).
R9. **Dosya kaynağı (yalnız `ANALYZER_ALLOW_FILE_SOURCES=1`):** zaman ekseni dosya saniyesi (`at` ∈ [0, süre]); `calendar(1970, 1)
    = {1}`, başka ay boş; `timeline(0) = [(0, süre)]`; açılışta `cap.set(CAP_PROP_POS_MSEC, start×1000)`; gerçek zamanlı oynatılır
    (`CameraViewer`'daki `is_file` kalıbı); dışa aktarma `501`.
R10. **Dışa aktarma (TRASSIR):** `POST /jit-export-create-task?sid=` JSON `{"resource_guid": <kanal>, "start_ts": µs,
    "end_ts": µs, "is_hardware": 0, "prefer_substream": 0}` → `task_id`; `GET /jit-export-download?sid=&task_id=` akıtılır
    (httpx `stream`, okuma zaman aşımı 600 sn; cihaz "hazır değil" dönerse 1 sn arayla en çok 20 deneme). Dosya adı
    `<kamera adı>-<YYYYMMDD-HHMM>.mp4` (ASCII'ye indirgenmiş; `Content-Disposition` `filename*` ile UTF-8).
R11. **Alarm kaydı:** `AlarmStore.add(..., source_id=None, channel_id=None)`; kayda `sourceId`, `channelId` (yoksa `None`); eski
    kayıtlar varsayılanla dolar. `_session_view`/alarm JSON'ında görünür. Panel `Alarm` tipine isteğe bağlı alanlar.
R12. **Panel sayfası:** İzleme grubunda "Kayıttan izleme" (`/archive`), Canlı izleme'nin altında. Üstte kamera seçici (yalnız
    `kind == "recorder"` kaynakların kanalları; kaynak adı · kanal adı), sağda ay takvimi (kayıtlı günler koyu, bugün çerçeveli,
    ◀ ▶ ay), altta 24 saatlik çizelge (dolu aralıklar `bg-pl-accent/60`, imleç çizgisi, saat etiketleri 0/6/12/18/24; tıklama
    seek; odakta ←/→ 10 sn, Shift+←/→ 1 dk, Boşluk duraklat/sürdür). Oynatıcı: `<img>` MJPEG, üstte durum satırı
    (`aria-live="polite"`): "Bağlanıyor…", "Sarılıyor…", "Duraklatıldı", "Kayıt bitti" (+ "Sonraki kayda git" düğmesi),
    hata iletisi; sağ üstte `HH:MM:SS` ve tarih. Kumanda: ⏮ 1 dk, ◀ 10 sn, Duraklat/Sürdür, 10 sn ▶, 1 dk ⏭, hız `<select>`
    (`speeds`), "Dışa aktar…" (`canExport` değilse pasif + başlık iletisi). Durum yoklama 1 sn; sayfadan çıkışta `DELETE`
    (`fetch keepalive`). Derin bağlantı `?source=&channel=&t=`. "?" ile kısayol listesi (Canlı izleme kalıbı).
R13. **Dışa aktar penceresi:** başlangıç/bitiş `datetime-local` girdileri, varsayılan imleç −1 dk / +1 dk; süre > 30 dk ise
    düğme pasif ve ileti "En çok 30 dakika."; indirme `fetch` → `Blob` → `<a download>`; sürerken düğme pasif "Hazırlanıyor…";
    hata iletileri sunucudan (`detail`).
R14. **Belgeler:** `docs/13-web-platform.md` yeni bölüm "Kayıttan izleme (`/archive`)" (Çoklu izleme bölümünden sonra),
    `docs/08-trassir-integration.md` arşiv SDK uçları + açık soru 5 kapanır, `docs/12-durum.md` satır + donanım doğrulama listesi.

## Review Focus (spec'in ima ettiği, testle sabitlenen durumlar)
1. Kayıt cihazı oynatma sırasında yanıt vermez olursa oynatıcı `error` + Türkçe ileti; iş parçacığı ölmez, "Sürdür" yeniden dener. (Task 2)
2. Kaydı olmayan ana sarınca akış hemen biter: `ended` ≤ 20 sn, sonsuz "Bağlanıyor…" yok. (Task 2, 3)
3. İki sekme aynı kamerayı açarsa 2 sınırı: üçüncü `429`, panel iletisi anlaşılır; kapanan oynatıcı yerini bırakır. (Task 3, 5)
4. Gün sınırı yerel saatte: çizelge `[gün, gün+86400)`; Hikvision'a UTC çevrimi doğru (yerel 00:00 → UTC). (Task 1)
5. Duraklamada TRASSIR jetonu ölür; sürdürme yeni jeton alır (yeniden açılış yolu), eski adres kullanılmaz. (Task 2)

---

### Task 1: Arşiv bağdaştırıcıları ve ayrıştırıcılar (`live/archive.py`)
**Files:** Create `services/edge/bantvision/live/archive.py`; Modify `services/edge/bantvision/live/recorders.py` (`_DeviceHTTP.post`,
`_DeviceHTTP.stream`); Test `services/edge/tests/test_archive.py`.
**Interfaces (produces):**
```python
class ArchiveClient(ABC):
    speeds: tuple[int, ...]
    can_export: bool
    def stream_url(self, channel: RecorderChannel, start: float, end: float | None, substream: bool, speed: int) -> str: ...
    def stop(self, stream_url: str) -> None: ...                 # TRASSIR: archive_command stop; diğerleri: no-op
    def keep_alive(self, stream_url: str) -> None: ...
    def calendar(self, channel: RecorderChannel, year: int, month: int) -> set[int]: ...
    def timeline(self, channel: RecorderChannel, day: float) -> list[tuple[float, float]]: ...
    def export(self, channel: RecorderChannel, start: float, end: float) -> Iterator[bytes]: ...   # can_export değilse RecorderError.unsupported()
class TrassirArchive(ArchiveClient): ...   # TrassirClient'ı sarar (sid, _video_token, _http)
class HikvisionArchive(ArchiveClient): ...
class DahuaArchive(ArchiveClient): ...
class FileArchive(ArchiveClient): ...      # R9
def make_archive(client: RecorderClient, brand: RecorderBrand) -> ArchiveClient
def merge_ranges(ranges: Iterable[tuple[float, float]], gap: float = 2.0) -> list[tuple[float, float]]
def hik_utc(epoch: float) -> str; def hik_iso(epoch: float) -> str; def dahua_time(epoch: float, sep: str) -> str; def trassir_time(epoch: float) -> str
def parse_trassir_calendar(obj) -> set[str]; def parse_trassir_timeline(obj, day: float) -> list[tuple[float, float]]
def parse_hik_search(xml: bytes) -> tuple[list[tuple[float, float]], str]; def parse_hik_daily(xml: bytes) -> set[int]
def parse_dahua_find(text: str) -> list[tuple[float, float]]
```
`RecorderError` yeni tür `unsupported` ("Bu kayıt cihazında dışa aktarma henüz desteklenmiyor.", API 501). `_DeviceHTTP.post(path,
body: bytes, content_type: str, query=None) -> bytes` ve `_DeviceHTTP.stream(url, timeout) -> Iterator[bytes]` (`get_url` ile aynı hata eşlemesi).
**Steps:** biçim/ayrıştırıcı testleri önce (UTC/yerel çevrim, DST günü, R7/R8 örnek yanıtları, `MORE` sayfalama, boş/bozuk yanıt →
`RecorderError.unexpected`), sonra uygulama; `ruff`; commit.

### Task 2: `ArchivePlayer` ve `ArchiveManager`
**Files:** Modify `services/edge/bantvision/live/archive.py`; Test `services/edge/tests/test_archive_player.py`.
**Interfaces (produces):**
```python
@dataclass(frozen=True)
class PlayerView: id: str; source_id: str; channel_id: str | None; name: str; state: str; message: str; at: float; speed: int; speeds: tuple[int, ...]; fps: float; can_export: bool
class ArchivePlayer:
    def __init__(self, player_id, archive: ArchiveClient, channel, url_fn_factory, open_capture, name, start: float, speed: int, substream: bool, clock=time.monotonic) -> None
    def view(self) -> PlayerView; def frame(self) -> tuple[int, np.ndarray | None]; def touch(self) -> None
    def pause(self) -> None; def resume(self) -> None; def seek(self, at: float) -> None; def set_speed(self, speed: int) -> None
    def close(self) -> None; last_used: float
class ArchiveManager:
    MAX_PLAYERS = 2; IDLE_S = 60.0; NO_FRAME_S = 20.0; CACHE_S = 60.0
    def __init__(self, store: LiveStore, recorder_factory, open_capture, clock=time.monotonic) -> None
    def calendar(self, source_id, channel_id, year, month) -> set[int]; def timeline(self, source_id, channel_id, day) -> list[tuple[float, float]]
    def open(self, source_id, channel_id, at, speed, substream) -> PlayerView   # 429 → TooManyPlayers
    def get(self, player_id) -> ArchivePlayer | None; def close(self, player_id) -> bool; def sweep(self) -> int; def stop(self) -> None
    def export(self, source_id, channel_id, start, end) -> tuple[str, Iterator[bytes]]   # (dosya adı, akış); kilit; ExportBusy
```
Yakalama açılışı R4; iş parçacığı kalıbı `viewer.CameraViewer` (sahte yakalama ile test: `tests/test_viewer.py`'deki `FakeCapture`
kalıbını kopyala/uyarla). Testler: `at` hesabı (fps 0 → 25), kare atlama 2×/4×, pause son kare + `at` sabit, resume yeni adres
(`url_fn` tekrar çağrılır, `stop` eski adresle çağrılır), seek yeni start, 20 sn karesiz → error, akış bitince `ended`, 2 sınırı,
boşta 60 sn kapanış, önbellek 60 sn (hata önbelleğe girmez), export kilidi, `RecorderError` → iş parçacığı yaşar.
**Steps:** testler → uygulama → `ruff` → commit.

### Task 3: API, uygulama bağlantısı, alarm kaydı alanları, dosya kaynağı gerçek yığın testi
**Files:** Modify `services/edge/bantvision/live/api.py` (yeni uçlar; tablo spec'te), `services/edge/bantvision/analyzer/app.py`
(`ArchiveManager` kur, lifespan `stop`), `services/edge/bantvision/live/alarms.py` + `api.py` çağrıları (R11); Test
`services/edge/tests/test_archive_api.py` (TestClient; dosya kaynağı: `tests/`'deki mevcut sentetik video kalıbıyla oynatıcı açılır,
`/stream?limit=3` 3 JPEG verir, `seek` sonrası `at` ≈ istenen, `pause` `at` sabit, 3. oynatıcı 429, export 501, takvim/çizelge R9),
`tests/test_alarms.py` (yeni alanlar, eski kayıt varsayılanı).
**Interfaces (consumes):** Task 2. **Produces:** API sözleşmesi (spec tablosu) — alan adları aynen.
Hatalar `_err` ile; `unsupported` → 501; `TooManyPlayers` → 429; `ExportBusy` → 409; `start>=end` ya da `end-start>1800` → 422.
`GET …/stream` `limit` parametresi (canlıdaki gibi, test için). Yanıtlarda şifre/jeton yok (test: adres alanı hiç dönmez).
**Steps:** testler → uygulama → tüm edge testleri → commit.

### Task 4: Sahte NVR arşiv uçları ve tümleşik testler
**Files:** Modify `tools/mock_nvr.py` (TRASSIR: `get_video stream=archive_main|archive_sub` jetonu; `archive_command` play/stop
kaydı; `archive_status type=calendar|timeline` sabit yanıtlar — timeline `day_start` son `play`'in günü; `POST /jit-export-create-task`
→ `{"task_id"}`; `GET /jit-export-download` → küçük sabit bayt dizisi `video/mp4`. Hikvision: `POST /ISAPI/ContentMgmt/search`
(`MORE` → ikinci sayfa `OK`), `POST …/dailyDistribution`. Dahua: `mediaFileFind.cgi` beş eylem, iki sayfalı sonuç), Test
`services/edge/tests/test_recorders.py` (mock_nvr fixture: üç markada `calendar`, `timeline` (birleştirme dahil), TRASSIR `export`
baytları ve `stop`; Hikvision/Dahua `export` → `unsupported`).
**Steps:** testler → sahte uçlar → tümleşik koşu → commit.

### Task 5: Panel sayfası `/archive`
**Files:** Modify `apps/dashboard/src/lib/nav.ts`; Create `apps/dashboard/src/app/(panel)/archive/page.tsx`,
`apps/dashboard/src/components/archive/{ArchiveView,CameraPicker,Calendar,Timeline,Player,ExportDialog}.tsx`,
`apps/dashboard/src/lib/archive.ts` (+ `archive.test.mjs`: gün başı/ay hesapları, `HH:MM:SS`, çizelge yüzde↔epoch, 30 dk sınırı,
dosya adı), `apps/dashboard/src/lib/archiveKeys.mjs` (kısayollar, test); Test `apps/dashboard/e2e/archive-ui.spec.ts` (sahte
analiz yanıtları: kamera listesi, takvim, çizelge, oynatıcı durumları `connecting→playing→paused→ended→error`, 429/501/409 iletileri,
klavye, derin bağlantı, sayfadan çıkışta DELETE, `aria-live`).
**Consumes:** Task 3 API. R12, R13 bağlayıcı. Mevcut kalıplar: `src/components/watch/*` (tour/keys), `CamerasView` (kanal listesi),
`AlarmViewer` (pencere). `tsc`, unit, e2e yeşil. Commit (birden çok olabilir).

### Task 6: Alarmdan kayda, gerçek yığın e2e, belgeler
**Files:** Modify `apps/dashboard/src/components/live/AlarmViewer.tsx` (+ `src/lib/live.ts` Alarm tipi `sourceId?`, `channelId?`),
`apps/dashboard/e2e/safety-ui.spec.ts` (düğme var/yok), Create `apps/dashboard/e2e/archive.spec.ts` (gerçek yığın, dosya kaynağı:
oynatıcı akıtır, çizelge tıklaması `at` değiştirir, duraklat son kareyi tutar, hız 2×), Modify `docs/13-web-platform.md`,
`docs/08-trassir-integration.md`, `docs/12-durum.md` (R14; donanım doğrulama listesi: TRASSIR ofis NVR; Hikvision/Dahua cihaz
bulununca; "doğrulanmadı" etiketleri).
**Steps:** e2e testler → düğme → belgeler → tüm dashboard testleri → commit.
