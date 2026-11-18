export type SoundGroup = "fire" | "person" | "phone";
export interface AlarmSound { id: string; name: string; file: string }

export const SOUNDS: ReadonlyArray<AlarmSound>;
export const SOUND_GROUPS: ReadonlyArray<{ id: SoundGroup; name: string; hint: string }>;
export const DEFAULT_SOUND: Readonly<Record<SoundGroup, string>>;
export const DEFAULT_VOLUME: number;
export const MIN_VOLUME: number;
export const SOUND_REPEAT_MS: number;

export function soundGroup(type: string): SoundGroup;
export function soundFile(id: string): string | null;
export function parseSound(group: SoundGroup, raw: string | null): string;
export function parseVolume(raw: string | null): number;
