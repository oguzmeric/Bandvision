export type AlarmSeverity = "critical" | "warning";
export interface InsetCrop { scale: number; left: number; top: number }

export function alarmSeverity(type: string): AlarmSeverity;
export function sortAlarms<T extends { type: string; firedAt: number }>(list: T[]): T[];
export function liveStreamUrl(
  a: { sessionId: string | null; sourceId?: string | null; channelId?: string | null },
  liveSessionIds: ReadonlySet<string>,
): string | null;
export function insetCrop(box: unknown): InsetCrop | null;
export function insetSide(box: unknown): "left" | "right";
export function agoText(seconds: number): string;
