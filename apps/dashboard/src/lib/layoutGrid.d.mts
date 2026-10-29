import type { ViewLayout } from "./views";

export const MAX_TILES: number;
export function parseGrid(id: string): { rows: number; cols: number } | null;
export function gridId(rows: number, cols: number): string;
export function layoutFor(id: string, catalog: ViewLayout[]): ViewLayout | null;

/** Kutu katmanının yoğunluğu (kutunun dış boyutuna göre) */
export type TileTier = "full" | "small" | "tiny";
export const TILE_FULL: Readonly<{ w: number; h: number }>;
export const TILE_SMALL: Readonly<{ w: number; h: number }>;
export function tileTier(layout: Pick<ViewLayout, "cols" | "rows" | "cells">, index: number,
  grid: { w: number; h: number } | null): TileTier;
