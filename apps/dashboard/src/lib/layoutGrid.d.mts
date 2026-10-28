import type { ViewLayout } from "./views";

export const MAX_TILES: number;
export function parseGrid(id: string): { rows: number; cols: number } | null;
export function gridId(rows: number, cols: number): string;
export function layoutFor(id: string, catalog: ViewLayout[]): ViewLayout | null;
