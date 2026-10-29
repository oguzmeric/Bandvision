import type { TileRef, ViewLayout } from "./views";

/** Editörde düzenlenen şablon içeriği */
export interface Draft { layout: string; tiles: Array<TileRef | null>; name: string }
export interface History { past: Draft[]; present: Draft; future: Draft[] }

export const EDITOR_LAYOUTS: readonly string[];
export const HISTORY_LIMIT: number;
export function refKey(ref: TileRef): string;
export function sameContent(a: Pick<Draft, "layout" | "tiles">, b: Pick<Draft, "layout" | "tiles">): boolean;
export function retile(tiles: Array<TileRef | null>, count: number): { tiles: Array<TileRef | null>; dropped: number };
export function newDraft(catalog: ViewLayout[]): Draft;
export function newName(taken: Iterable<string>): string;
export function applyLayout(draft: Draft, layoutId: string, catalog: ViewLayout[]): { draft: Draft; dropped: number };
export function assign(draft: Draft, index: number, ref: TileRef | null): Draft;
export function swap(draft: Draft, a: number, b: number): Draft;
export function initHistory(draft: Draft): History;
export function push(h: History, draft: Draft): History;
export function undo(h: History): History;
export function redo(h: History): History;
export function canUndo(h: History): boolean;
export function canRedo(h: History): boolean;
export function isDirty(h: History, saved: Pick<Draft, "layout" | "tiles"> | null): boolean;
export function validateGrid(rows: number, cols: number): string | null;
