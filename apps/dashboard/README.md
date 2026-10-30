# BandVision web paneli

Next.js 15 (App Router) paneli: canlı izleme (şablonlu çoklu kamera ızgarası), alarmlar, kameradan canlı sayım ve
güvenlik alarmı, videodan sayım, kamera ve kayıt cihazı ayarları, bildirimler, telefondan erişim. Mimari, uç noktalar ve
fazlar: [`docs/13-web-platform.md`](../../docs/13-web-platform.md).

## Menü
Solda yazılı, gruplu menü (sade arayüz; ayrıntı `docs/13-web-platform.md` "Panel kabuğu"). Gruplar açılır-kapanır ve
tarayıcıda hatırlanır; dar ekranda (telefon) menü üstteki "Menü" düğmesinin arkasına katlanır. Gri öğelerin sayfası henüz yok,
tıklanınca "yakında" der. Her sayfanın altında durum şeridi vardır: analiz sunucusu çalışıyor mu, işlemci yükü, ekran kartı.

| Grup | Öğe | Adres | Ne yapar |
|---|---|---|---|
| İzleme | Canlı izleme | `/watch` | Şablon sekmeleri, Şablon editörü (1…8×8 ve N×M, en çok 128 kutu), kamera listesi, tek kamera, video duvarı |
| İzleme | Alarmlar | `/alarms` | Güvenlik alarmı geçmişi (7 gün), süzgeçler, ihlal anının kaydı |
| Analizler | Ürün sayımı | `/live?tur=urun` | Bant üstü ürün sayan canlı oturumlar (canlı sayım sayfasının süzülmüş hâli) |
| Analizler | Kişi sayımı | `/live?tur=kisi` | Giriş/Çıkış sayan canlı oturumlar |
| Analizler | Güvenlik alarmı (poz) | `/live?tur=guvenlik` | Eller yukarı / yerde yatan kişi izleyen kameralar |
| Analizler | Yangın ve duman | — | Yakında |
| Analizler | Kalite kontrol | — | Yakında |
| Analizler | Video ile test | `/videos` | Video yükle, işaretli videoyu oynat, sayım/doğruluk, zamana göre sayım grafiği, CSV, geçmiş |
| Analizler | Raporlar | — | Yakında |
| Donanım | Kameralar ve kayıt cihazları | `/cameras` | Kayıt cihazı (NVR) ve IP kamera ekle; kamerada canlı sayımı başlat |
| Donanım | Cihaz ayarları | — | Yakında |
| Sistem | Bildirimler (Telegram) | `/notifications` | Telegram kurulumu, deneme alarmı, bu tarayıcıdaki dikkat seçenekleri |
| Sistem | Telefondan erişim | `/settings` | Panel şifresi, yerel ağa açma, telefonda açılacak adres ve QR kod |
| Sistem | Lisans | — | Yakında |
| Sistem | Hakkında | `/about` | Panelin ve analiz sunucusunun sürümü ve git kısa özeti |

Süzmesiz `/live` (eski "Canlı sayım" bağlantıları) açılmaya devam eder; `/` ve logo Video ile test sayfasını açar.

Panel analiz sunucusuna (`services/edge`, `bantvision.analyzer`) **kendi sunucu tarafından** bağlanır;
`ANALYZER_TOKEN` tarayıcıya hiç gitmez, kamera şifreleri panele ve telefona gitmez.

## Yerel çalıştırma
**Windows'ta tek tık:** `tools/panel_baslat.bat` (ya da masaüstündeki kısayolu). İlk seferde analiz sunucusu ortamını (`services/edge/.venv`) ve panel paketlerini kurar, sonra ikisini küçültülmüş pencerelerde başlatıp tarayıcıyı açar; çalışıyorlarsa yeniden başlatmaz. Günlükler: `.logs\analyzer.log`, `.logs\panel.log`.

Paneli kısayol **başlatıcıyla** açar: `tools/panel_run.mjs` (`node tools/panel_run.mjs [--port 3000] [--prod]`).
- Telefondan erişim kapalıyken paneli yalnızca bu bilgisayarda (`127.0.0.1`), geliştirme kipinde çalıştırır.
- Açıkken (Telefondan erişim sayfasından, şifreyle) tüm ağ arayüzlerinde **üretim kipinde** çalıştırır: gerekiyorsa önce kendi klasörüne
  (`.next-lan`) derler (ilk açılış 1–2 dk; `.bat` en çok 240 sn bekler ve "Panel derleniyor" yazar). Derleme başarısız
  olursa ya da derlemede giriş denetimi yoksa yerel ağa açmaz, yalnızca bu bilgisayarda başlatır.
- Tek kopya çalışır (`.local/panel.lock`); durumunu `.local/panel-state.json`'a yazar; erişim ayarı değişince Next'i yeniden başlatır.

**Telefondan erişim** menüde Sistem → "Telefondan erişim" sayfasından kurulur (panel şifresi, açma/kapama, telefonda açılacak adres ve
QR kod); şifre yalnızca özet olarak `apps/dashboard/.local/access.json`'da (git dışı) tutulur. Ayrıntı:
`docs/13-web-platform.md` "Telefondan erişim".

Elle (geliştirme):
1. Analiz sunucusu (Python 3.11+):
   ```bash
   cd services/edge
   pip install -e ".[analyzer]"
   python -m bantvision.analyzer --port 8090
   ```
2. Panel (Node 20+):
   ```bash
   cd apps/dashboard
   npm install
   npm run dev      # ya da derleyip: npm run build && npm start
   ```
   Tarayıcı: http://localhost:3000. `dev` ve `start` betikleri yalnızca `127.0.0.1`'de dinler (yerel ağdan erişilmez);
   telefondan erişim için başlatıcı ve Telefondan erişim sayfası kullanılır. Şifre yoksa panel yalnızca `localhost` / `127.0.0.1` / `[::1]`
   adıyla açılır (başka `Host` → `403`).

| Ortam değişkeni | Varsayılan | Açıklama |
|---|---|---|
| `ANALYZER_URL` | `http://127.0.0.1:8090` | Analiz sunucusu adresi |
| `ANALYZER_TOKEN` | — | Sunucuda token tanımlıysa aynısı (yalnızca sunucu tarafında kullanılır) |
| `DASHBOARD_PASSWORD` | — | Tanımlıysa panelin tüm sayfaları ve API'si tek şifreyle korunur (oturum 7 gün; şifre değişince tüm oturumlar düşer); Ayarlar'daki panel şifresinden önceliklidir. Tanımlı değilse ve telefondan erişim kapalıysa panel şifresizdir ama yalnızca bu bilgisayardan açılır |
| `PANEL_ACCESS_FILE`, `PANEL_STATE_FILE` | `.local/access.json`, `.local/panel-state.json` | Erişim ayarı ve başlatıcı durum dosyası (testler geçici klasöre yönlendirir) |
| `BV_COMMIT` | — | Hakkında'da gösterilen git kısa özeti; tanımlı değilse `git rev-parse --short HEAD`, o da olmazsa "?" (analiz sunucusu da aynı değişkeni okur) |

Analiz sunucusunun Canlı izleme okuyucu sınırı ortam değişkeni `BV_WATCH_MAX_SUB` ile değişir (aynı anda en çok kaç alt
akış; varsayılan 128); ayrıntı `docs/13-web-platform.md` "Çoklu izleme" → "Okuyucular".

## Denetimler
```bash
npm run lint
npm run typecheck
npm run test:unit  # saf yardımcılar: şifre özeti, panel planı, giriş kısıtı, Host denetimi, kilit, derleme işareti,
                   # N×M düzen ve kutu yoğunluğu, şablon düzenleme, sistem durumu, sade görünüm bekçisi
npm run build
npm run test:e2e   # gerçek analiz sunucusu + derlenmiş panel; PYTHON=<analyzer kurulu python>
```
Uçtan uca testler uygulamanın test klibini (`apps/ios/BantSayacUITests/ui_test_clip.mp4`) yükler ve
sayımın Python referansıyla aynı olduğunu, işaretli videonun tarayıcıda oynayıp sarılabildiğini, CSV'yi ve silmeyi doğrular;
menü ve durum şeridi, canlı sayım, güvenlik alarmı, Canlı izleme (5×5 taslağın ve kaydedilen şablonun birleşik akışı dahil)
ve erişim kipleri de sınanır (hiçbiri gerçek kameraya bağlanmaz).
