"use client";

import { useEffect, useState } from "react";

/** Şifre formu: istek tarayıcıdan gider, başarıda göreli adrese geçilir (ana makine adı değişmez, çerez kaybolmaz). */
export default function LoginForm({ next }: { next: string }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Sayfa yüklenmeden (JS hazır değilken) basılırsa tarayıcı formu kendisi gönderirdi: şifre adres satırına düşer,
  // giriş olmaz. Düğme hazır olana kadar kapalı; form ayrıca POST (şifre hiçbir durumda adrese yazılmaz).
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (r.ok) {
        window.location.assign(next);
        return;
      }
      setError(r.status === 401 ? "Şifre yanlış."
        : r.status === 429 ? "Çok fazla hatalı deneme; biraz sonra yeniden deneyin."
        : "Giriş yapılamadı, tekrar dene.");
    } catch {
      setError("Sunucuya ulaşılamadı.");
    }
    setBusy(false);
  }

  return (
    <form method="post" action="/api/login" onSubmit={submit}>
      <label className="block text-[12.5px] text-pl-muted">Şifre
        <input name="password" type="password" autoComplete="current-password" required autoFocus value={password}
               onChange={(e) => setPassword(e.target.value)}
               className="pl-input mt-1 h-9 w-full" />
      </label>
      {error && <p role="alert" data-testid="login-error" className="mt-3 rounded-[2px] border border-nok-line bg-nok-50 px-3 py-2 text-[13px] text-nok-ink">{error}</p>}
      <button type="submit" disabled={busy || !ready} className="pl-btn pl-btn-primary mt-4 h-9 w-full justify-center">
        {busy ? "Giriş yapılıyor…" : "Giriş yap"}
      </button>
    </form>
  );
}
