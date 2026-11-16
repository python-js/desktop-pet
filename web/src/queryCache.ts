type Entry<T = unknown> = { value: T; updatedAt: number }

const entries = new Map<string, Entry>()
const pending = new Map<string, Promise<unknown>>()
const revisions = new Map<string, number>()

export function readCache<T>(key: string): T | undefined {
  return entries.get(key)?.value as T | undefined
}

export function writeCache<T>(key: string, value: T): T {
  entries.set(key, { value, updatedAt: Date.now() })
  return value
}

export function invalidateCache(key?: string) {
  if (!key) {
    entries.clear()
    pending.clear()
    revisions.clear()
    return
  }
  entries.delete(key)
  pending.delete(key)
  revisions.set(key, (revisions.get(key) ?? 0) + 1)
}

export function isFresh(key: string, maxAgeMs: number): boolean {
  const entry = entries.get(key)
  return !!entry && Date.now() - entry.updatedAt < maxAgeMs
}

export function fetchCached<T>(key: string, load: () => Promise<T>, maxAgeMs = 20_000): Promise<T> {
  const cached = readCache<T>(key)
  if (cached !== undefined && isFresh(key, maxAgeMs)) return Promise.resolve(cached)
  const running = pending.get(key) as Promise<T> | undefined
  if (running) return running
  const revision = revisions.get(key) ?? 0
  const request = load().then((value) => {
    if ((revisions.get(key) ?? 0) === revision) return writeCache(key, value)
    return readCache<T>(key) ?? value
  }).finally(() => {
    if (pending.get(key) === request) pending.delete(key)
  })
  pending.set(key, request)
  return request
}
