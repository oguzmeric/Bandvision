export function classifyListenError(code: string | undefined): "free" | "busy";
export function canListen(port: number, host: string, ipv6Only?: boolean): Promise<boolean>;
export function isFree(port: number): Promise<boolean>;
