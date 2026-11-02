export function hostName(hostHeader: string | null | undefined): string | null;
export function isLoopbackHost(hostHeader: string | null | undefined): boolean;
export function isLoopbackOrigin(origin: string | null | undefined): boolean;
export const CROSS_SITE_REFUSED: string;
export function crossSiteRefused(origin: string | null | undefined, secFetchSite: string | null | undefined): boolean;
