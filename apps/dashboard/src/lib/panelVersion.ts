import "server-only";
import pkg from "../../package.json";
import { commitReader } from "./panelCommit.mjs";

/** Panel sürümü (package.json) */
export const PANEL_VERSION: string = pkg.version;

/**
 * Panelin kısa git özeti: ortamda BV_COMMIT varsa o, yoksa süreç başına bir kez `git rev-parse --short HEAD` (eşzamansız,
 * en çok 2 sn; olay döngüsünü durdurmaz); olmazsa "?". Sonuç önbellekte kalır.
 */
export const getPanelCommit: () => Promise<string> = commitReader();
