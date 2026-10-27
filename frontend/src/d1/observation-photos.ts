/**
 * Bounded photo-object-URL cache for the observation editor.
 *
 * The authenticated binary endpoint is read with the app session header, so
 * images are fetched as Blobs (an <img src> can never carry the session).
 * Only the currently displayed chunk keeps object URLs alive; leaving a chunk
 * or unmounting revokes them, so 600 images are never resident at once.
 */

export interface PhotoUrlCacheOptions {
  load: (assetId: string, signal?: AbortSignal) => Promise<Blob>
  createUrl?: (blob: Blob) => string
  revokeUrl?: (url: string) => void
  max?: number
  maxPending?: number
}

export class PhotoUrlCache {
  private readonly load: (assetId: string, signal?: AbortSignal) => Promise<Blob>
  private readonly createUrl: (blob: Blob) => string
  private readonly revokeUrl: (url: string) => void
  private readonly max: number
  private readonly maxPending: number
  private readonly urls = new Map<string, string>()
  private readonly order: string[] = []
  private readonly pending = new Map<string, Promise<string | null>>()
  private readonly tokens = new Map<string, object>()
  private readonly controllers = new Map<string, AbortController>()
  private generation = 0
  private disposed = false

  constructor(options: PhotoUrlCacheOptions) {
    this.load = options.load
    this.createUrl =
      options.createUrl ??
      ((blob) => URL.createObjectURL(blob))
    this.revokeUrl =
      options.revokeUrl ??
      ((url) => URL.revokeObjectURL(url))
    this.max = options.max ?? 24
    this.maxPending = options.maxPending ?? 8
  }

  /** Live object URL for one asset, loading it on demand. */
  async ensure(assetId: string): Promise<string | null> {
    if (this.disposed) return null
    const existing = this.urls.get(assetId)
    if (existing) {
      this.touch(assetId)
      return existing
    }
    const pending = this.pending.get(assetId)
    if (pending) return pending
    const generation = this.generation
    while (this.pending.size >= this.maxPending) {
      await Promise.race([...this.pending.values()])
      if (this.disposed || generation !== this.generation) return null
    }
    if (this.disposed || generation !== this.generation) return null
    const queued = this.pending.get(assetId)
    if (queued) return queued
    const token = {}
    const controller = new AbortController()
    const request = (async () => {
      try {
        const blob = await this.load(assetId, controller.signal)
        if (this.disposed || generation !== this.generation) return null
        const url = this.createUrl(blob)
        this.urls.set(assetId, url)
        this.order.push(assetId)
        this.evict()
        return url
      } finally {
        if (this.tokens.get(assetId) === token) {
          this.pending.delete(assetId)
          this.tokens.delete(assetId)
          this.controllers.delete(assetId)
        }
      }
    })()
    this.tokens.set(assetId, token)
    this.controllers.set(assetId, controller)
    this.pending.set(assetId, request)
    return request
  }

  /** Invalidate every in-flight and cached read (chunk/version switch). */
  invalidate(): void {
    this.generation += 1
    for (const controller of this.controllers.values()) controller.abort()
    this.controllers.clear()
    this.pending.clear()
    this.tokens.clear()
    this.releaseAll()
  }

  /** Release every URL except the given keep-set (current chunk). */
  releaseExcept(keep: Iterable<string>): void {
    const keepSet = new Set(keep)
    for (const assetId of [...this.urls.keys()]) {
      if (!keepSet.has(assetId)) this.release(assetId)
    }
  }

  release(assetId: string): void {
    this.controllers.get(assetId)?.abort()
    this.controllers.delete(assetId)
    const url = this.urls.get(assetId)
    if (url === undefined) return
    this.urls.delete(assetId)
    const index = this.order.indexOf(assetId)
    if (index >= 0) this.order.splice(index, 1)
    this.revokeUrl(url)
  }

  releaseAll(): void {
    for (const assetId of [...this.urls.keys()]) this.release(assetId)
  }

  dispose(): void {
    this.disposed = true
    this.generation += 1
    for (const controller of this.controllers.values()) controller.abort()
    this.controllers.clear()
    this.releaseAll()
    this.pending.clear()
    this.tokens.clear()
  }

  size(): number {
    return this.urls.size
  }

  private touch(assetId: string): void {
    const index = this.order.indexOf(assetId)
    if (index >= 0) this.order.splice(index, 1)
    this.order.push(assetId)
  }

  private evict(): void {
    while (this.order.length > this.max) {
      const oldest = this.order[0]
      this.release(oldest)
    }
  }
}
