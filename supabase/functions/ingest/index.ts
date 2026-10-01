// BantVision ingest — docs/02-contracts.md §3–§4
// Dağıtım: supabase functions deploy ingest --no-verify-jwt   (cihazlar JWT değil X-Device-Key kullanır)
import { createClient } from "jsr:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

async function sha256Hex(s: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(d)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function newDeviceKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return "bvk_" + Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TYPES = new Set(["count", "inspection", "state", "heartbeat"]);

Deno.serve(async (req) => {
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);
  const path = new URL(req.url).pathname.replace(/^.*\/ingest/, "") || "/";

  // ---- eşleme (anahtarsız) ----
  if (path === "/pair") {
    const b = await req.json().catch(() => null);
    if (!b?.code || !b?.deviceInfo?.kind) return json({ error: "bad_request" }, 400);
    const key = newDeviceKey();
    const { data, error } = await supabase.rpc("pair_device", {
      p_code: String(b.code).toUpperCase(),
      p_kind: b.deviceInfo.kind,
      p_model: b.deviceInfo.model ?? null,
      p_app_version: b.deviceInfo.appVersion ?? null,
      p_name: b.deviceInfo.hostname ?? null,
      p_key_hash: await sha256Hex(key),
    });
    if (error || !data?.length) return json({ error: "invalid_or_expired_code" }, 400);
    const row = data[0];
    return json({ deviceId: row.device_id, deviceKey: key, lineId: row.line_id, orgId: row.org_id });
  }

  // ---- cihaz doğrulama ----
  const key = req.headers.get("x-device-key");
  if (!key) return json({ error: "missing_device_key" }, 401);
  const { data: dev } = await supabase
    .from("devices").select("id, org_id, line_id").eq("key_hash", await sha256Hex(key)).maybeSingle();
  if (!dev) return json({ error: "unknown_device" }, 401);

  // ---- NOK görseli yükleme URL'si ----
  if (path === "/upload-url") {
    const b = await req.json().catch(() => ({}));
    const day = new Date().toISOString().slice(0, 10);
    const cam = String(b.cameraId ?? "cam").replace(/[^A-Za-z0-9_-]/g, "");
    const track = Number.isInteger(b.trackId) ? b.trackId : 0;
    const objectPath = `${dev.org_id}/${dev.line_id ?? "unassigned"}/${day}/${cam}-${track}-${crypto.randomUUID()}.jpg`;
    const { data, error } = await supabase.storage.from("nok-images").createSignedUploadUrl(objectPath);
    if (error) return json({ error: "storage_error" }, 500);
    return json({ uploadUrl: data.signedUrl, imageRef: objectPath });
  }

  // ---- olay paketi ----
  if (path === "/") {
    const batch = await req.json().catch(() => null);
    if (batch?.schema !== "bantvision.batch.v1" || !Array.isArray(batch.events)) {
      return json({ error: "bad_batch" }, 400);
    }
    if (batch.events.length > 500) return json({ error: "too_many_events" }, 400);
    for (const e of batch.events) {
      if (e?.schema !== "bantvision.event.v1" || !UUID_RE.test(e.eventId ?? "") || !TYPES.has(e.type) ||
          e.deviceId !== dev.id || Number.isNaN(Date.parse(e.ts))) {
        return json({ error: "bad_event", eventId: e?.eventId ?? null }, 400);
      }
      if (e.profileId && !UUID_RE.test(e.profileId)) e.profileId = null;
    }
    if (batch.events.length === 0) return json({ accepted: 0, duplicates: 0 });
    const { data, error } = await supabase.rpc("ingest_events", { p_device_id: dev.id, p_events: batch.events });
    if (error) return json({ error: "ingest_failed" }, 500);
    return json(data);
  }

  return json({ error: "not_found" }, 404);
});
