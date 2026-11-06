import type { TileRef } from "./views";

export const TOUR_INTERVALS: readonly number[];
export const DEFAULT_TOUR_S: number;
export const TOUR_COOKIE: string;
export function filledIndexes(tiles: ReadonlyArray<TileRef | null>): number[];
export function stepFilled(tiles: ReadonlyArray<TileRef | null>, from: number, dir: 1 | -1): number | null;
export function tourPosition(tiles: ReadonlyArray<TileRef | null>, index: number): { n: number; total: number };
export function readCookie(cookies: string | null | undefined, name: string): string | null;
export function parseTourInterval(raw: string | null | undefined): number;
export function tourCookie(seconds: number): string;
