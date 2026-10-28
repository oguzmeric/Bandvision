import "server-only";
import { execFileSync } from "node:child_process";
import pkg from "../../package.json";

/** Panel sürümü (package.json) */
export const PANEL_VERSION: string = pkg.version;

/** Panelin kısa git özeti: ortamda BV_COMMIT varsa o, yoksa süreç başına bir kez `git rev-parse --short HEAD` ("?" olabilir). */
let panelCommit: string | undefined;
export function getPanelCommit(): string {
  if (panelCommit !== undefined) return panelCommit;
  const env = process.env.BV_COMMIT?.trim();
  if (env) return (panelCommit = env);
  try {
    panelCommit = execFileSync("git", ["rev-parse", "--short", "HEAD"], { timeout: 2000, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim() || "?";
  } catch {
    panelCommit = "?";
  }
  return panelCommit;
}
