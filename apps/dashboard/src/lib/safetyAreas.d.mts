import type { SafetyArea, SafetyConfig, SafetyRuleKey } from "./live";

export const MAX_AREAS: number;
export const AREA_NAME_MAX: number;
export const AREA_RULES: SafetyRuleKey[];
export const AREA_RULE_LABELS: Record<SafetyRuleKey, string>;
export const AREAS_HELP: string;

export function enabledRules(safety: Partial<SafetyConfig> | undefined | null): SafetyRuleKey[];
export function safetyAreas(safety: Partial<SafetyConfig> | undefined | null): SafetyArea[];
export function nextAreaName(areas: SafetyArea[]): string;
export function areaSlot(i: number): Array<[number, number]>;
export function addArea(areas: SafetyArea[], rules: SafetyRuleKey[]): SafetyArea[];
export function removeArea(areas: SafetyArea[], i: number): SafetyArea[];
export function renameArea(areas: SafetyArea[], i: number, raw: string): SafetyArea[];
export function toggleAreaRule(areas: SafetyArea[], i: number, rule: SafetyRuleKey, on: boolean): SafetyArea[];
export function withAreaPoints(areas: SafetyArea[], zones: Array<Array<[number, number]>>): SafetyArea[];
export function withAreas<T extends { areas?: SafetyArea[] }>(safety: T, areas: SafetyArea[]): T;
export function duplicateAreaNames(areas: SafetyArea[]): Set<number>;
export function addAreaBlocked(areas: SafetyArea[], rules: SafetyRuleKey[]): string | null;
export function areaWatches(area: SafetyArea, safety: Partial<SafetyConfig> | undefined | null): boolean;
