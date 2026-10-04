# BandVision web paneli

Next.js 15 (App Router) paneli. Şu an: **Video analizi** — video yükle, ilerlemeyi izle, işaretli videoyu oynat,
sayım/doğruluk, zamana göre sayım grafiği, CSV indir, geçmiş. Mimari ve fazlar: [`docs/13-web-platform.md`](../../docs/13-web-platform.md).

Panel analiz sunucusuna (`services/edge`, `bantvision.analyzer`) **kendi sunucu tarafından** bağlanır;
`ANALYZER_TOKEN` tarayıcıya hiç gitmez.

## Yerel çalıştırma
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
   npm run dev
   ```
   Tarayıcı: http://localhost:3000

| Ortam değişkeni | Varsayılan | Açıklama |
|---|---|---|
| `ANALYZER_URL` | `http://127.0.0.1:8090` | Analiz sunucusu adresi |
| `ANALYZER_TOKEN` | — | Sunucuda token tanımlıysa aynısı (yalnızca sunucu tarafında kullanılır) |
| `DASHBOARD_PASSWORD` | — | Tanımlıysa panelin tüm sayfaları ve API'si tek şifreyle korunur (oturum 7 gün; şifre değişince tüm oturumlar düşer). Tanımlı değilse panel açıktır — **yalnızca yerel demoda**; internete açılan her kurulumda zorunlu |

## Denetimler
```bash
npm run lint
npm run typecheck
npm run build
npm run test:e2e   # gerçek analiz sunucusu + derlenmiş panel; PYTHON=<analyzer kurulu python>
```
Uçtan uca testler uygulamanın test klibini (`apps/ios/BantSayacUITests/ui_test_clip.mp4`) yükler ve
sayımın Python referansıyla aynı olduğunu, işaretli videonun tarayıcıda oynayıp sarılabildiğini, CSV'yi ve silmeyi doğrular.
