import type { AlarmType } from "@/lib/live";

/**
 * Alarm türünün küçük çizgi simgesi (emoji değil): alev (yangın), duman bulutu (duman), kollarını kaldırmış kişi (eller
 * yukarı), yerde yatan kişi, telefon, zil (deneme alarmı). Renk `currentColor` (çağıranın yazı rengi), boyut `className`.
 * Süsleme: ekran okuyucudan gizlidir (tür adı yanında yazılıdır).
 */
export default function AlarmIcon({ type, className = "h-5 w-5" }: { type: AlarmType; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
         className={className} aria-hidden="true" focusable="false" data-icon={type}>
      {PATHS[type]}
    </svg>
  );
}

const PATHS: Record<AlarmType, React.ReactNode> = {
  fire: (
    <>
      <path d="M12 2.5c.6 3.2 4.8 5.4 4.8 10.2a4.8 4.8 0 0 1-9.6 0c0-2.4 1.1-3.9 2.4-5.1.2 1.7 1 2.7 2 3.1.2-2.9.4-5.3.4-8.2z" fill="currentColor" stroke="none" />
      <path d="M12 20.5a2.2 2.2 0 0 1-2.2-2.2c0-1.3.9-2 1.6-2.8.3.9.8 1.3 1.4 1.5a2 2 0 0 1 1.4 1.3 2.2 2.2 0 0 1-2.2 2.2z" fill="white" stroke="none" opacity={0.85} />
    </>
  ),
  smoke: (
    <>
      <path d="M7 17.5h9.5a3.5 3.5 0 0 0 .4-7 5 5 0 0 0-9.6-1A4 4 0 0 0 7 17.5z" />
      <path d="M5 21h6M14 21h4" />
    </>
  ),
  hands_up: (
    <>
      <circle cx="12" cy="7" r="2" />
      <path d="M5 2.5l4 6h6l4-6" />
      <path d="M9 8.5v5.5h6V8.5" />
      <path d="M10 14l-1 7.5M14 14l1 7.5" />
    </>
  ),
  lying: (
    <>
      <circle cx="5" cy="13" r="2" />
      <path d="M8 14h7l5 1.5" />
      <path d="M11 14l1.5-3" />
      <path d="M2 18.5h20" />
    </>
  ),
  phone: (
    <>
      <rect x="7" y="2.5" width="10" height="19" rx="2" />
      <path d="M11 18h2" />
    </>
  ),
  test: (
    <>
      <path d="M6 16.5V11a6 6 0 1 1 12 0v5.5l1.5 2h-15z" />
      <path d="M10 21a2 2 0 0 0 4 0" />
    </>
  ),
};
