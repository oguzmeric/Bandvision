import type { ViewLayout } from "./views";

export const MAX_TILES: number;
export function parseGrid(id: string): { rows: number; cols: number } | null;
export function gridId(rows: number, cols: number): string;
export function layoutFor(id: string, catalog: ViewLayout[]): ViewLayout | null;

/** Kutu katmanının yoğunluğu (kutunun dış boyutuna ve kök yazı boyutuna göre; kameranın durumundan bağımsız) */
export type TileTier = "full" | "small" | "tiny" | "micro";
/** Varsayılan kök yazı boyutu (px) */
export const ROOT_PX: number;
/** Eşikler ve ölçüler rem cinsinden (× kök yazı boyutu = px) */
export const TILE_FULL: Readonly<{ w: number; h: number }>;
export const TILE_SMALL: Readonly<{ w: number; h: number }>;
export const TILE_TINY: Readonly<{ w: number; h: number }>;
export const FULL_CHROME_H: number;
export const STATE_LINE_H: number;
export function tileSize(layout: Pick<ViewLayout, "cols" | "rows" | "cells">, index: number,
  grid: { w: number; h: number } | null): { w: number; h: number } | null;
/** `h`: kutu yüksekliği (px); `rem`: kök yazı boyutu (px) */
export function stateLines(h: number, rem?: number): number;
/** `grid`: ızgaranın boyutu (px); `rem`: kök yazı boyutu (px) */
export function tileTier(layout: Pick<ViewLayout, "cols" | "rows" | "cells">, index: number,
  grid: { w: number; h: number } | null, rem?: number): TileTier;
