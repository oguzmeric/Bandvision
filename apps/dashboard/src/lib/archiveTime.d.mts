export type Range = readonly [number, number];
export interface Segment { start: number; end: number; left: number; width: number }

export const MAX_EXPORT_S: number;
export const POLL_MS: number;
export const MONTHS: readonly string[];
export const WEEKDAYS: readonly string[];

export function dayStart(at: number): number;
export function dayOf(year: number, month: number, day: number): number;
export function dayEnd(day: number): number;
export function partsOf(at: number): { year: number; month: number; day: number };
export function shiftMonth(year: number, month: number, delta: number): { year: number; month: number };
export function daysInMonth(year: number, month: number): number;
export function monthGrid(year: number, month: number): Array<Array<number | null>>;
export function clock(at: number): string;
export function dateLabel(at: number): string;
export function longDate(year: number, month: number, day: number): string;
export function toPercent(at: number, day: number, end: number): number;
export function fromPercent(percent: number, day: number, end: number): number;
export function clampToDay(at: number, day: number, end: number): number;
export function segments(ranges: readonly Range[], day: number, end: number): Segment[];
export function nextRangeStart(ranges: readonly Range[], at: number): number | null;
export function defaultCursor(ranges: readonly Range[], day: number, end: number): number;
export function toLocalInput(at: number): string;
export function fromLocalInput(value: string | null | undefined): number | null;
export function exportProblem(start: number | null, end: number | null): string | null;
export function fileStamp(at: number): string;
export function fallbackFilename(start: number): string;
export function dispositionFilename(header: string | null | undefined, fallback: string): string;
