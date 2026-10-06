import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";

/**
 * Uçtan uca: gerçek analiz sunucusu (Python referans çekirdeği) + derlenmiş panel.
 * PYTHON: bantvision-edge[analyzer] kurulu Python (varsayılan "python").
 */
const PYTHON = process.env.PYTHON ?? "python";
const ANALYZER_PORT = 8091;
const WEB_PORT = 3100;
const DATA_DIR = path.join(os.tmpdir(), `bv-e2e-${process.pid}`);
/** Testte panel şifreyle korunur (e2e/auth.spec.ts); gerçek şifre değildir. */
export const PANEL_PASSWORD = "e2e-test-sifresi";

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
             DASHBOARD_PASSWORD: PANEL_PASSWORD },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
