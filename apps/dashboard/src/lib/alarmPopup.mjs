// Alarm penceresi / köşe kartları için saf yardımcılar (DOM'suz; node --test ile sınanır).

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const round = (v, d) => {
  const f = 10 ** d;
  const r = Math.round(v * f) / f;
  return r === 0 ? 0 : r; // -0 → 0
};

/** Telefon kullanımı uyarı; diğer her alarm kritik */
export function alarmSeverity(type) {
  return type === "phone" ? "warning" : "critical";
}

/** Önce kritikler, grup içinde yeni (firedAt büyük) üstte; eşitlikte giriş sırası korunur. Yeni dizi döner. */
export function sortAlarms(list) {
  return list
    .map((a, i) => ({ a, i }))
    .sort((x, y) => {
      const sx = alarmSeverity(x.a.type) === "critical" ? 0 : 1;
      const sy = alarmSeverity(y.a.type) === "critical" ? 0 : 1;
      return sx - sy || y.a.firedAt - x.a.firedAt || x.i - y.i;
    })
    .map((e) => e.a);
}

/** Canlı akış adresi: oturum canlıysa oturumun akışı; değilse kaynağın alt akışı; yoksa null */
export function liveStreamUrl(a, liveSessionIds) {
  if (a.sessionId && liveSessionIds.has(a.sessionId)) {
    return `/api/live/sessions/${encodeURIComponent(a.sessionId)}/stream`;
  }
  if (a.sourceId) {
    const q = new URLSearchParams({ source: a.sourceId });
    if (a.channelId) q.set("channel", a.channelId);
    q.set("quality", "sub");
    return `/api/live/cameras/stream?${q.toString()}`;
  }
  return null;
}

function validBox(box) {
  if (!Array.isArray(box) || box.length !== 4) return null;
  if (!box.every((n) => typeof n === "number" && Number.isFinite(n))) return null;
  const [x1, y1, x2, y2] = box;
  if (x2 <= x1 || y2 <= y1) return null;
  return box;
}

/** Kutuya yakınlaştırılmış kırpım: görüntü width/height = scale·100 %, left/top yüzde. Geçersizse null. */
export function insetCrop(box) {
  const b = validBox(box);
  if (!b) return null;
  const [x1, y1, x2, y2] = b;
  const scale = clamp(1 / (1.6 * Math.max(x2 - x1, y2 - y1)), 1, 4);
  const pos = (c) => clamp((0.5 - c * scale) * 100, (1 - scale) * 100, 0);
  return { scale: round(scale, 3), left: round(pos((x1 + x2) / 2), 2), top: round(pos((y1 + y2) / 2), 2) };
}

/** Kutu sağ yarıdaysa küçük pencere solda, aksi halde sağda durur */
export function insetSide(box) {
  const b = validBox(box);
  return b && (b[0] + b[2]) / 2 > 0.5 ? "left" : "right";
}

/** "38 sn önce" / "9 dk önce" / "2 sa önce" */
export function agoText(seconds) {
  const s = Math.max(0, seconds);
  if (s < 60) return `${Math.floor(s)} sn önce`;
  if (s < 3600) return `${Math.floor(s / 60)} dk önce`;
  return `${Math.floor(s / 3600)} sa önce`;
}
