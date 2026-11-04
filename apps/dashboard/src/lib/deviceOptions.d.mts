import type { DeviceInfo, InUse, BenchResult } from "./devices";

export function choiceOptions(devices: DeviceInfo[], auto: string, saved: string): { value: string; label: string }[];
export function inUseText(status: Pick<InUse, "state" | "device" | "note">): { text: string; warn: boolean };
export function benchText(result: Pick<BenchResult, "msPerFrame" | "loadS"> & { device: { note: string | null } }): { text: string; warn: boolean };
