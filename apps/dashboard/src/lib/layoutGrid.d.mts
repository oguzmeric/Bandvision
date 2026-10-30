import type { ViewLayout } from "./views";

export const MAX_TILES: number;
export function parseGrid(id: string): { rows: number; cols: number } | null;
export function gridId(rows: number, cols: number): string;
export function layoutFor(id: string, catalog: ViewLayout[]): ViewLayout | null;

/** Kutu katmanının yoğunluğu (kutunun dış boyutuna ve durum metni olup olmadığına göre) */
export type TileTier = "full" | "small" | "tiny" | "micro";
export const TILE_FULL: Readonly<{ w: number; h: number }>;
export const TILE_SMALL: Readonly<{ w: number; h: number }>;
export const TILE_TINY: Readonly<{ w: number; h: number }>;
export const FULL_CHROME_H: number;
export const STATE_LINE_H: number;
export function tileSize(layout: Pick<ViewLayout, "cols" | "rows" | "cells">, index: number,
  grid: { w: number; h: number } | null): { w: number; h: number } | null;
export function stateLines(h: number): number;
export function tileTier(layout: Pick<ViewLayout, "cols" | "rows" | "cells">, index: number,
  grid: { w: number; h: number } | null, withState?: boolean): TileTier;
