import { execFile } from "node:child_process";

/** `git rev-parse --short HEAD`, beklemeden (süreç kendi başına çalışır, olay döngüsü durmaz); en çok 2 sn */
function gitShortHead() {
  return new Promise((resolve, reject) => {
    execFile("git", ["rev-parse", "--short", "HEAD"], { timeout: 2000, encoding: "utf8" },
      (err, stdout) => (err ? reject(err) : resolve(stdout)));
  });
}

/**
 * Panelin kısa git özetini okuyan işlev: ortamda `BV_COMMIT` varsa o; yoksa süreç başına BİR kez `git rev-parse --short
 * HEAD` (eşzamansız; aynı anda gelen istekler aynı sonucu bekler); git yoksa, hata verirse ya da 2 sn'de bitmezse "?".
 * Sonuç önbellekte kalır. `run` ve `env` testler içindir.
 * @param {{ run?: () => Promise<string>, env?: Record<string, string | undefined> }} [deps]
 * @returns {() => Promise<string>}
 */
export function commitReader({ run = gitShortHead, env = process.env } = {}) {
  /** @type {Promise<string> | undefined} */
  let cached;
  return () => {
    if (cached === undefined) {
      const fromEnv = env.BV_COMMIT?.trim();
      cached = fromEnv ? Promise.resolve(fromEnv) : run().then((out) => out.trim() || "?", () => "?");
    }
    return cached;
  };
}
