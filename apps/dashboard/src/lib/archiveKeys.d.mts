export type ArchiveShortcut = { type: "step"; seconds: number } | { type: "toggle" } | { type: "swallow" } | { type: "help" };
export interface ArchiveShortcutContext { blocked: boolean; control: boolean }

export const STEP_S: number;
export const BIG_STEP_S: number;
export function archiveKeysBlocked(target: Element | null, doc: Pick<Document, "querySelector">): boolean;
export function archiveShortcut(
  e: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey" | "repeat">,
  ctx: ArchiveShortcutContext,
): ArchiveShortcut | null;
