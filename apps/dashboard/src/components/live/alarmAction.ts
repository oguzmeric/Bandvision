import type { Alarm } from "@/lib/live";

/** Alarm penceresinin ve köşe kartlarının iki işlemi: "Gördüm" ve "Yanlış alarm" (işaretliyse geri alır) */
export type AlarmAction = "ack" | "false";

export interface AlarmActionHandlers {
  onAck: (a: Alarm) => Promise<boolean>;
  onFalseAlarm: (a: Alarm) => Promise<boolean>;
  /** İstek başlarken (onay sorulduktan sonra): düğmeleri kilitle, eski hatayı sil */
  onStart: () => void;
  /** İstek bitince (başarılı ya da değil) */
  onEnd: () => void;
}

/**
 * İşlemi yapar; "Yanlış alarm" önce onay sorar (vazgeçilirse hiçbir şey yapılmaz). Dönen değer kullanıcıya gösterilecek hata
 * metnidir; başarıda ve vazgeçilince null. Pencere ve köşe kartı aynı metinleri kullanır (biri değişince öteki kaymasın).
 */
export async function runAlarmAction(a: Alarm, kind: AlarmAction, h: AlarmActionHandlers): Promise<string | null> {
  const undo = kind === "false" && Boolean(a.falseAlarm);
  if (kind === "false" && !confirm(undo
    ? "Yanlış alarm işareti kaldırılsın mı? Alarm onaylanmış olarak kalır."
    : "Bu alarm yanlış alarm olarak işaretlensin mi? Alarm kapanır ve listede «Yanlış alarm» olarak görünür.")) return null;
  h.onStart();
  const ok = await (kind === "ack" ? h.onAck(a) : h.onFalseAlarm(a));
  h.onEnd();
  if (ok) return null;
  return kind === "ack" ? "Gördüm kaydedilemedi; alarm açık kalıyor. Tekrar deneyin."
    : undo ? "Yanlış alarm işareti kaldırılamadı. Tekrar deneyin." : "Yanlış alarm kaydedilemedi. Tekrar deneyin.";
}
