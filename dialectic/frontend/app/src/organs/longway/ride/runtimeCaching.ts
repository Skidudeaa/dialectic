/// <reference lib="webworker" />
// Imported only into sw.ts by the scoped injectManifest Vite plugin.
import { registerRoute } from 'workbox-routing'
import { CacheFirst, NetworkFirst } from 'workbox-strategies'
import { CacheableResponsePlugin } from 'workbox-cacheable-response'
import { ExpirationPlugin } from 'workbox-expiration'
import type { RideLeg } from '../types'

const guideImages = new Set<string>()
function rememberImages(leg: RideLeg) {
  for (const entry of Object.values(leg.guide ?? {})) if (entry.img?.startsWith('https://')) guideImages.add(entry.img)
}
// Cache keys include a digest of both credentials. Room paths alone must never let
// a second signed-in identity read the first identity's cached movement.
export async function privateRideKey(request: Request): Promise<string> {
  const identity = `${request.headers.get('Authorization') ?? ''}\n${request.headers.get('X-Room-Token') ?? ''}`
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(identity))
  const url = new URL(request.url)
  url.searchParams.set('__ride_identity', Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join(''))
  return url.href
}
const privateKey = { cacheKeyWillBeUsed: ({ request }: { request: Request }) => privateRideKey(request) }
const success = () => new CacheableResponsePlugin({ statuses: [200] })
const legName = 'longway-ride-legs-v1'
// Cache the chart gate too: an offline room reopen still needs its bound trip.
registerRoute(
  ({ url, sameOrigin }) => sameOrigin && /^\/rooms\/[^/]+\/longway\/(ride|chart)$/.test(url.pathname),
  new NetworkFirst({ cacheName: 'longway-rides-v1', networkTimeoutSeconds: 3, plugins: [privateKey, success(), new ExpirationPlugin({ maxEntries: 30, maxAgeSeconds: 7 * 86400 })] }),
)
registerRoute(
  ({ url, sameOrigin }) => sameOrigin && /^\/rooms\/[^/]+\/longway\/ride\/leg$/.test(url.pathname),
  new CacheFirst({ cacheName: legName, plugins: [privateKey, success(), new ExpirationPlugin({ maxEntries: 20, maxAgeSeconds: 86400 }), {
    async fetchDidSucceed({ response }: { response: Response }) {
      if (response.ok) rememberImages(await response.clone().json() as RideLeg)
      return response
    },
    async cacheDidUpdate({ newResponse }: { newResponse: Response }) { rememberImages(await newResponse.clone().json() as RideLeg) },
    async cachedResponseWillBeUsed({ cachedResponse }: { cachedResponse?: Response }) {
      if (cachedResponse) rememberImages(await cachedResponse.clone().json() as RideLeg)
      return cachedResponse
    },
  }] }),
)
registerRoute(
  ({ url, request }) => request.destination === 'image' && url.protocol === 'https:' &&
    (['upload.wikimedia.org', 'thumb.wikimedia.org'].includes(url.hostname) || guideImages.has(url.href)),
  new CacheFirst({ cacheName: 'longway-guide-images-v1', plugins: [new CacheableResponsePlugin({ statuses: [0, 200] }), new ExpirationPlugin({ maxEntries: 200, maxAgeSeconds: 30 * 86400 })] }),
)
// A restarted worker can see photo requests before the client asks for its leg.
void caches.open(legName).then(async cache => {
  for (const request of await cache.keys()) {
    const response = await cache.match(request)
    if (response) rememberImages(await response.json() as RideLeg)
  }
}).catch(() => { /* Storage can be unavailable; in-memory live behavior still works. */ })
