export function commitReader(deps?: {
  run?: () => Promise<string>;
  env?: Record<string, string | undefined>;
}): () => Promise<string>;
