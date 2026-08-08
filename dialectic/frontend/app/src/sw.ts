/// <reference lib="webworker" />
/**
 * Dialectic service worker.
 *
 * Everything the old generateSW config did (precache, SPA fallback with the
 * API denylist, Google Fonts caching) plus the two handlers that justify a
 * hand-written worker: `push` (a message buzzes the pocket with the app fully
 * closed) and `notificationclick` (lands you in the room it came from).
 */
declare let self: ServiceWorkerGlobalScope

import { clientsClaim } from 'workbox-core'
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute } from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'
import { CacheFirst, StaleWhileRevalidate } from 'workbox-strategies'
import { ExpirationPlugin } from 'workbox-expiration'
import { CacheableResponsePlugin } from 'workbox-cacheable-response'

// Installed PWAs must pick up new workers without a manual reinstall.
self.skipWaiting()
clientsClaim()

cleanupOutdatedCaches()
precacheAndRoute(self.__WB_MANIFEST)

// The SPA fallback must never swallow API or WebSocket routes — nginx proxies
// this whole set to the backend on the same origin. Keep in step with the dev
// proxy list in vite.config.ts.
registerRoute(new NavigationRoute(createHandlerBoundToURL('index.html'), {
  denylist: [
    /^\/(api|ws|auth|rooms|threads|users|health|analytics|graph|replay|stakes|messages|memories|personas|notifications|openapi)\b/,
  ],
}))

registerRoute(
  ({ url }) => url.origin === 'https://fonts.googleapis.com',
  new StaleWhileRevalidate({ cacheName: 'google-fonts-css' }),
)
registerRoute(
  ({ url }) => url.origin === 'https://fonts.gstatic.com',
  new CacheFirst({
    cacheName: 'google-fonts-static',
    plugins: [
      new ExpirationPlugin({ maxEntries: 24, maxAgeSeconds: 60 * 60 * 24 * 365 }),
      new CacheableResponsePlugin({ statuses: [0, 200] }),
    ],
  }),
)

interface PushPayload {
  title?: string
  body?: string
  tag?: string
  data?: { room_id?: string; thread_id?: string; message_id?: string; type?: string }
}

self.addEventListener('push', (event) => {
  if (!event.data) return
  let payload: PushPayload
  try {
    payload = event.data.json() as PushPayload
  } catch {
    return
  }
  event.waitUntil(self.registration.showNotification(payload.title ?? 'Dialectic', {
    body: payload.body ?? '',
    // One notification per room, replaced in place, rather than a stack.
    tag: payload.tag ?? 'dialectic',
    data: payload.data ?? {},
    icon: '/icons/pwa-192.png',
    badge: '/icons/pwa-192.png',
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const roomId: string | undefined = event.notification.data?.room_id
  event.waitUntil((async () => {
    const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    if (clients.length > 0) {
      const client = clients[0]
      await client.focus()
      // An open app switches rooms in place — the page listens for this.
      if (roomId) client.postMessage({ type: 'open-room', roomId })
      return
    }
    await self.clients.openWindow(roomId ? `/?room=${roomId}` : '/')
  })())
})
