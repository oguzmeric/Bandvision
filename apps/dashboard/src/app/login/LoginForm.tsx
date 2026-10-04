"use client";

import { useState } from "react";

/** Şifre formu: istek tarayıcıdan gider, başarıda göreli adrese geçilir (ana makine adı değişmez, çerez kaybolmaz). */
export default function LoginForm({ next }: { next: string }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
      setError(r.status === 401 ? "Şifre yanlış." : "Giriş yapılamadı, tekrar dene.");
    } catch {
      setError("Sunucuya ulaşılamadı.");
    }
    setBusy(false);
  }

  return (
    <form onSubmit={submit}>
      <label className="block text-sm font-medium">Şifre
        <input name="password" type="password" autoComplete="current-password" required autoFocus value={password}
               onChange={(e) => setPassword(e.target.value)}
               className="mt-1.5 h-10 w-full rounded-[10px] border border-line bg-white px-3 text-sm outline-none focus:border-brand-500 focus:ring-3 focus:ring-brand-50" />
      </label>
      {error && <p role="alert" data-testid="login-error" className="mt-3 rounded-xl bg-nok-50 px-3 py-2 text-sm text-nok-600">{error}</p>}
      <button type="submit" disabled={busy}
              className="brand-gradient mt-5 h-11 w-full rounded-[11px] text-sm font-semibold text-white shadow-[0_8px_18px_rgba(109,59,240,0.25)] transition hover:brightness-105 disabled:opacity-70">
        {busy ? "Giriş yapılıyor…" : "Giriş yap"}
      </button>
    </form>
  );
}
