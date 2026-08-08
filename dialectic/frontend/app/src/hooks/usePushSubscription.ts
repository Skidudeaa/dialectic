import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api.ts'

/**
 * Web Push subscription lifecycle.
 *
 * WHY the split between auto and explicit: browsers only allow a permission
 * prompt from a user gesture (iOS enforces this hard), so the hook silently
 * subscribes when permission is already granted and exposes `enable()` for a
 * button when it isn't. The server upsert is idempotent, so re-subscribing on
 * every launch is cheap and self-heals rotated subscriptions.
 */

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4)
  const normalized = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = window.atob(normalized)
  return Uint8Array.from(raw, (c) => c.charCodeAt(0))
}

export type PushState = 'unsupported' | 'prompt' | 'denied' | 'subscribed' | 'error'

async function subscribeAndRegister(): Promise<boolean> {
  const registration = await navigator.serviceWorker.ready
  let subscription = await registration.pushManager.getSubscription()
  if (!subscription) {
    const { public_key } = await api.getVapidPublicKey() as { public_key: string }
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key) as BufferSource,
    })
  }
  const json = subscription.toJSON()
  if (!json.endpoint || !json.keys) return false
  await api.registerWebPushSubscription({
    endpoint: json.endpoint,
    keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
    user_agent: navigator.userAgent,
  })
  return true
}

export function usePushSubscription(active: boolean): { state: PushState; enable: () => void } {
  const [state, setState] = useState<PushState>(() => {
    if (typeof Notification === 'undefined' || !('serviceWorker' in navigator) || !('PushManager' in window)) {
      return 'unsupported'
    }
    if (Notification.permission === 'denied') return 'denied'
    return 'prompt'
  })

  // Permission already granted (or just granted): subscribe silently.
  useEffect(() => {
    if (!active || state === 'unsupported' || state === 'denied' || state === 'subscribed') return
    if (Notification.permission !== 'granted') return
    let cancelled = false
    subscribeAndRegister()
      .then((ok) => { if (!cancelled) setState(ok ? 'subscribed' : 'error') })
      .catch((error) => {
        console.error('Push subscription failed:', error)
        if (!cancelled) setState('error')
      })
    return () => { cancelled = true }
  }, [active, state])

  // Explicit user gesture — the only context iOS allows the prompt in.
  const enable = useCallback(() => {
    if (typeof Notification === 'undefined') return
    void Notification.requestPermission().then((permission) => {
      if (permission === 'granted') {
        subscribeAndRegister()
          .then((ok) => setState(ok ? 'subscribed' : 'error'))
          .catch(() => setState('error'))
      } else if (permission === 'denied') {
        setState('denied')
      }
    })
  }, [])

  return { state, enable }
}
