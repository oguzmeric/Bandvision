"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ALARM_LABELS, api, type Alarm } from "@/lib/live";

/** Her panel sayfasında: onaylanmamış güvenlik alarmları (2 sn'de bir). Ses yok (sessiz alarm). */
export default function AlarmBanner() {
  const [alarms, setAlarms] = useState<Alarm[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => api<Alarm[]>("alarms?active=1").then((a) => alive && setAlarms(a)).catch(() => undefined);
    load();
    const t = setInterval(load, 2000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (alarms.length === 0) return null;
  const time = (s: number) => new Date(s * 1000).toLocaleTimeString("tr-TR");
  return (
    <div role="alert" aria-label="Güvenlik alarmı" className="mb-4 grid gap-2">
      {alarms.slice(0, 3).map((a) => (
        <div key={a.id} className="flex flex-wrap items-center gap-3 rounded-2xl bg-nok-600 px-4 py-3 text-white shadow-lg">
          <span className="text-lg" aria-hidden="true">🚨</span>
          <p className="min-w-0 flex-1 text-sm font-semibold">
            {ALARM_LABELS[a.type]} — {a.camera} · {time(a.firedAt)}
            {a.endedAt === null && a.type !== "test" && <span className="ml-2 rounded-full bg-white/20 px-2 py-0.5 text-[11px]">devam ediyor</span>}
          </p>
          {a.sessionId && <Link href={`/live?s=${a.sessionId}`} className="text-[13px] font-medium underline">Kamerayı aç</Link>}
          <button type="button" onClick={() => api(`alarms/${a.id}/ack`, { method: "POST" }).then(() => setAlarms((x) => x.filter((y) => y.id !== a.id)))}
                  className="h-8 rounded-[9px] bg-white px-3 text-[13px] font-semibold text-nok-600">Gördüm</button>
        </div>
      ))}
    </div>
  );
}
