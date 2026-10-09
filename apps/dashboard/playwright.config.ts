import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";
import { hashPassword, newSecret } from "./src/lib/accessCore.mjs";

/**
 * Uçtan uca: gerçek analiz sunucusu (Python referans çekirdeği) + derlenmiş panel.
 * PYTHON: bantvision-edge[analyzer] kurulu Python (varsayılan "python").
 */
const PYTHON = process.env.PYTHON ?? "python";
const ANALYZER_PORT = 8091;
const WEB_PORT = 3100;
/** İkinci panel: telefondan erişimin ŞİFRE ÖZETİ kipi (DASHBOARD_PASSWORD yok; e2e/access-hash.spec.ts) */
const HASH_PORT = 3101;
const DATA_DIR = path.join(os.tmpdir(), `bv-e2e-${process.pid}`);
/** Testte panel şifreyle korunur (e2e/auth.spec.ts); gerçek şifre değildir. */
export const PANEL_PASSWORD = "e2e-test-sifresi";
/** Özet kipi sunucusunun giriş şifresi (e2e/access-hash.spec.ts aynısını kullanır); gerçek şifre değildir. */
export const HASH_MODE_PASSWORD = "ozet-kipi-test-sifresi";
const HASH_MODE = hashPassword(HASH_MODE_PASSWORD);
/** Telefondan erişim ayarı (e2e/access.spec.ts) geçici klasöre yazılır; repodaki apps/dashboard/.local/ asla kullanılmaz.
 * Test işçileri de bu dosyayı okuyabilsin diye yolu ortama koyarız (ilk değerlendirme ana süreçte olur). */
const ACCESS_FILE = (process.env.BV_E2E_ACCESS_FILE ??= path.join(DATA_DIR, "panel-access.json"));
/** Başlatıcının durum dosyası (Ayarlar'daki "derleniyor/başarısız" satırı; e2e/access.spec.ts yazar) da geçici klasörde */
const STATE_FILE = (process.env.BV_E2E_STATE_FILE ??= path.join(DATA_DIR, "panel-state.json"));

export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1400, height: 900 } } }],
  webServer: [
    {
      command: `${PYTHON} -m bantvision.analyzer --port ${ANALYZER_PORT}`,
      cwd: path.resolve(__dirname, "../../services/edge"),
      url: `http://127.0.0.1:${ANALYZER_PORT}/healthz`,
      // Canlı sayım testi yerel video dosyasını kamera gibi açar (yalnızca test bayrağıyla mümkün)
      env: { ANALYZER_DATA_DIR: DATA_DIR, PYTHONIOENCODING: "utf-8", ANALYZER_ALLOW_FILE_SOURCES: "1" },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx next start -p ${WEB_PORT} -H 127.0.0.1`,
      url: `http://127.0.0.1:${WEB_PORT}/videos`,
      env: { ANALYZER_URL: `http://127.0.0.1:${ANALYZER_PORT}`, NEXT_TELEMETRY_DISABLED: "1",
             DASHBOARD_PASSWORD: PANEL_PASSWORD,
             // Telefondan erişim ayarı repoya (apps/dashboard/.local/) değil geçici klasöre yazılır
             PANEL_ACCESS_FILE: ACCESS_FILE, PANEL_STATE_FILE: STATE_FILE },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      // Şifre özeti kipi: DASHBOARD_PASSWORD boş; başlatıcının verdiği özet + oturum sırrı ortamda (yalnızca 127.0.0.1)
      command: `npx next start -p ${HASH_PORT} -H 127.0.0.1`,
      url: `http://127.0.0.1:${HASH_PORT}/login`,
      env: { ANALYZER_URL: `http://127.0.0.1:${ANALYZER_PORT}`, NEXT_TELEMETRY_DISABLED: "1",
             DASHBOARD_PASSWORD: "", PANEL_PASSWORD_HASH: HASH_MODE.hash, PANEL_PASSWORD_SALT: HASH_MODE.salt,
             PANEL_SESSION_SECRET: newSecret(), PANEL_ACCESS_FILE: path.join(DATA_DIR, "panel-access-hash.json"),
             PANEL_STATE_FILE: path.join(DATA_DIR, "panel-state-hash.json") },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
