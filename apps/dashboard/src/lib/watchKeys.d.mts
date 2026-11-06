export type Shortcut =
  | { type: "toggle-single" } | { type: "escape" } | { type: "pause" } | { type: "swallow" }
  | { type: "step"; dir: 1 | -1 } | { type: "tab"; index: number } | { type: "help" };
export interface ShortcutContext { blocked: boolean; single: boolean; touring: boolean; control: boolean }

export function shortcutsBlocked(target: Element | null, doc: Pick<Document, "querySelector">): boolean;
export function shortcutFor(e: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "repeat">, ctx: ShortcutContext): Shortcut | null;
export function moveTab(ids: readonly string[], id: string, target: string): string[];
