import { api } from "./live";

/** Analiz sunucusunun cihaz uçları (`/api/v1/live/devices`, panelde `/api/live/devices`). */
export interface DeviceInfo { id: string; kind: "cpu" | "gpu"; name: string; memoryMb?: number }
/** Modelin gerçekte çalıştığı cihaz; `note`: işlemciye düşüş gibi kullanıcıya gösterilecek Türkçe not */
export interface UsedDevice { id: string; kind: "cpu" | "gpu"; name: string; note: string | null }
export interface InUse {
  state: "idle" | "loading" | "ready" | "error";
  /** hazır: çalışan cihaz; yükleniyor: yeni cihaz gelene dek hizmet veren ESKİ cihaz; hata/boşta: null */
  device: UsedDevice | null;
  note: string | null;
}
export type Choice = string;   // "auto" | "cpu" | ekran kartı kimliği
export interface Choices { detector: Choice; pose: Choice; video: Choice }
export interface DevicesState {
  gpuSupport: { available: boolean; reason: string | null };
  devices: DeviceInfo[];
  auto: string;
  choices: Choices;
  inUse: { detector: InUse; pose: InUse };
}
export interface BenchResult { device: UsedDevice; msPerFrame: number; loadS: number }

export const fetchDevices = () => api<DevicesState>("devices");
export const saveDevices = (choices: Choices) => api<DevicesState>("devices", { method: "PUT", json: { choices } });
export const runBenchmark = (device: string) => api<BenchResult>("devices/benchmark", { method: "POST", json: { device } });
