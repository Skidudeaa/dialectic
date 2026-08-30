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
    /^\/(api|ws|auth|rooms|threads|users|health|analytics|graph|replay|stakes|messages|memories|notifications|openapi)\b/,
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
  data?: {
    room_id?: string
    room_name?: string
    thread_id?: string
    message_id?: string
    type?: string
  }
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
  const threadId: string | undefined = event.notification.data?.thread_id
  const messageId: string | undefined = event.notification.data?.message_id
  event.waitUntil((async () => {
    const params = new URLSearchParams()
    if (roomId) params.set('room', roomId)
    if (threadId) params.set('thread', threadId)
    if (messageId) params.set('message', messageId)
    const query = params.toString()
    const destination = query ? `/?${query}` : '/'
    const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    if (clients.length > 0) {
      const client = clients.find(candidate => candidate.visibilityState === 'visible') ?? clients[0]
      await client.focus()
      let payload: Record<string, string> | null = null
      if (roomId && threadId && messageId) {
        payload = {
          type: 'open-message', roomId, threadId, messageId,
        }
      } else if (roomId) {
        // Legacy notifications carried only the room destination.
        payload = { type: 'open-room', roomId }
      }
      if (!payload) return

      const channel = new MessageChannel()
      const acknowledged = new Promise<boolean>((resolve) => {
        let settled = false
        const finish = (received: boolean) => {
          if (settled) return
          settled = true
          channel.port1.close()
          resolve(received)
        }
        // A thawing iOS PWA rarely runs its message listener inside 200ms,
        // so the ack path almost never won on the device this was written for.
        const timeout = setTimeout(() => finish(false), 1000)
        channel.port1.onmessage = () => {
          clearTimeout(timeout)
          finish(true)
        }
      })
      client.postMessage(payload, [channel.port2])
      // matchAll({includeUncontrolled:true}) can hand back a client this
      // worker does not control, and navigate() REJECTS for those — the
      // rejection escaped waitUntil and the tap did nothing at all.
      if (!await acknowledged) {
        try {
          await client.navigate(destination)
        } catch {
          await self.clients.openWindow(destination)
        }
      }
      return
    }
    await self.clients.openWindow(destination)
  })())
})
