import type { FireConfig } from "./live";
import type { FireSensitivity, JobOptions } from "./types";

export type Zone = Array<[number, number]>;

export interface FireRuleForm {
  enabled: boolean;
  /** Metin olarak (giriş alanı); "4,5" gibi virgüllü yazım kabul edilir */
  seconds: string;
}
export interface FireForm {
  fire: FireRuleForm;
  smoke: FireRuleForm;
  sensitivity: FireSensitivity;
}

export const FIRE_RULES: Record<"fire" | "smoke", { title: string; min: number; max: number; def: number }>;
export const SENSITIVITIES: FireSensitivity[];
export const SENSITIVITY_LABELS: Record<FireSensitivity, string>;
export const FIRE_WARNING: string;
export const FIRE_MODEL_MISSING: string;
export const MAX_ZONES: number;
export const MIN_ZONE_POINTS: number;
export const MAX_ZONE_POINTS: number;
export const FIRE_DEFAULTS: Readonly<FireConfig>;

export function fireConfig(v: unknown): FireConfig;
export function fireModelLine(status: { model?: string; modelError?: string | null } | null | undefined):
  { text: string; tone: "ok" | "muted" | "warn" } | null;
export function defaultFireForm(): FireForm;
export function fireOptions(form: FireForm): JobOptions | string;
export function fireRulesSummary(fire: JobOptions["fire"]): string;
export function newZone(i: number): Zone;
export function addZone(zones: Zone[]): Zone[];
export function removeZone(zones: Zone[], z: number): Zone[];
export function moveVertex(zones: Zone[], z: number, v: number, pt: [number, number]): Zone[];
export function insertVertex(zones: Zone[], z: number, after: number, pt: [number, number]): Zone[];
export function deleteVertex(zones: Zone[], z: number, v: number): Zone[];
export function translateZone(zones0: Zone[], z: number, dx: number, dy: number): Zone[];
export function insideZone(zone: Zone, p: [number, number]): boolean;
export function zonesProblem(zones: unknown): string | null;
