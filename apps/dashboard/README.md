# BandVision web paneli

Next.js 15 (App Router) paneli: **Video analizi** (video yükle, ilerlemeyi izle, işaretli videoyu oynat, sayım/doğruluk,
zamana göre sayım grafiği, CSV, geçmiş), **Kameralar** ve **Canlı sayım**, **Alarmlar**, **İzleme** (şablonlu çoklu kamera
ızgarası), **Ayarlar** (telefondan erişim). Mimari, uç noktalar ve fazlar: [`docs/13-web-platform.md`](../../docs/13-web-platform.md).

Panel analiz sunucusuna (`services/edge`, `bantvision.analyzer`) **kendi sunucu tarafından** bağlanır;
`ANALYZER_TOKEN` tarayıcıya hiç gitmez, kamera şifreleri panele ve telefona gitmez.

## Yerel çalıştırma
**Windows'ta tek tık:** `tools/panel_baslat.bat` (ya da masaüstündeki kısayolu). İlk seferde analiz sunucusu ortamını (`services/edge/.venv`) ve panel paketlerini kurar, sonra ikisini küçültülmüş pencerelerde başlatıp tarayıcıyı açar; çalışıyorlarsa yeniden başlatmaz. Günlükler: `.logs\analyzer.log`, `.logs\panel.log`.

Paneli kısayol **başlatıcıyla** açar: `tools/panel_run.mjs` (`node tools/panel_run.mjs [--port 3000] [--prod]`).
- Telefondan erişim kapalıyken paneli yalnızca bu bilgisayarda (`127.0.0.1`), geliştirme kipinde çalıştırır.
- Açıkken (Ayarlar'dan şifreyle) tüm ağ arayüzlerinde **üretim kipinde** çalıştırır: gerekiyorsa önce kendi klasörüne
  (`.next-lan`) derler (ilk açılış 1–2 dk; `.bat` en çok 240 sn bekler ve "Panel derleniyor" yazar). Derleme başarısız
  olursa ya da derlemede giriş denetimi yoksa yerel ağa açmaz, yalnızca bu bilgisayarda başlatır.
- Tek kopya çalışır (`.local/panel.lock`); durumunu `.local/panel-state.json`'a yazar; Ayarlar değişince Next'i yeniden başlatır.

**Telefondan erişim** Ayarlar → "Telefondan erişim"den kurulur (panel şifresi, açma/kapama, telefonda açılacak adres ve
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
   telefondan erişim için başlatıcı ve Ayarlar kullanılır. Şifre yoksa panel yalnızca `localhost` / `127.0.0.1` / `[::1]`
   adıyla açılır (başka `Host` → `403`).

| Ortam değişkeni | Varsayılan | Açıklama |
|---|---|---|
| `ANALYZER_URL` | `http://127.0.0.1:8090` | Analiz sunucusu adresi |
| `ANALYZER_TOKEN` | — | Sunucuda token tanımlıysa aynısı (yalnızca sunucu tarafında kullanılır) |
| `DASHBOARD_PASSWORD` | — | Tanımlıysa panelin tüm sayfaları ve API'si tek şifreyle korunur (oturum 7 gün; şifre değişince tüm oturumlar düşer); Ayarlar'daki panel şifresinden önceliklidir. Tanımlı değilse ve telefondan erişim kapalıysa panel şifresizdir ama yalnızca bu bilgisayardan açılır |
| `PANEL_ACCESS_FILE`, `PANEL_STATE_FILE` | `.local/access.json`, `.local/panel-state.json` | Erişim ayarı ve başlatıcı durum dosyası (testler geçici klasöre yönlendirir) |

## Denetimler
```bash
npm run lint
npm run typecheck
npm run test:unit  # saf yardımcılar: şifre özeti, panel planı, giriş kısıtı, Host denetimi, kilit, derleme işareti
npm run build
npm run test:e2e   # gerçek analiz sunucusu + derlenmiş panel; PYTHON=<analyzer kurulu python>
```
Uçtan uca testler uygulamanın test klibini (`apps/ios/BantSayacUITests/ui_test_clip.mp4`) yükler ve
sayımın Python referansıyla aynı olduğunu, işaretli videonun tarayıcıda oynayıp sarılabildiğini, CSV'yi ve silmeyi doğrular;
canlı sayım, güvenlik alarmı, İzleme ve erişim kipleri de sınanır (hiçbiri gerçek kameraya bağlanmaz).
