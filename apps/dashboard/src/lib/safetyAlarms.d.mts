import type { Alarm, AlarmKind, JobOptions } from "./types";

export interface SafetyRuleForm {
  enabled: boolean;
  /** Metin olarak (giriş alanı); "4,5" gibi virgüllü yazım kabul edilir */
  seconds: string;
}
export interface SafetyForm {
  handsUp: SafetyRuleForm;
  lying: SafetyRuleForm;
}
export interface AlarmRow {
  key: number;
  kind: AlarmKind;
  label: string;
  startS: number;
  clock: string;
  duration: string;
  /** `alarm-N.jpg`; resim yoksa ya da sonuçta listelenmemişse null */
  image: string | null;
}

export const SAFETY_RULES: Record<"handsUp" | "lying", { title: string; min: number; max: number; def: number }>;
export const NO_RULE_ON: string;
export const ALARM_LABELS: Record<AlarmKind, string>;
export function defaultSafetyForm(): SafetyForm;
export function safetyOptions(form: SafetyForm): JobOptions | string;
export function formatClock(s: number | undefined): string;
export function alarmRows(result: { alarms?: Alarm[]; files?: readonly string[] } | undefined): AlarmRow[];
export function rulesSummary(safety: JobOptions["safety"]): string;
export function alarmCounts(list: ReadonlyArray<{ type: string; falseAlarm?: boolean }>, types: readonly string[]):
  Record<string, number> & { total: number; false: number };
