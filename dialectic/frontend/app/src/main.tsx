import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'

/**
 * Hand-rolled SW registration (vite-plugin-pwa's injectRegister is OFF).
 *
 * WHY: the injected one-liner registered the worker and then never spoke to
 * it again — no update check, no reload when a new worker took control. On
 * an installed iOS PWA that meant a deployed release could sit invisible
 * behind the old precache indefinitely (2026-08-15: the owner reviewed a
 * day of shipped UI work through a stale bundle and reasonably asked "did
 * you even fix anything?"). Three duties the one-liner never did:
 *
 *  - updateViaCache: 'none' — the SW script fetch bypasses the HTTP cache,
 *    which matters because Cloudflare stamps .js with max-age=14400.
 *  - update() on visibility resume + hourly — resume IS the moment an iPad
 *    comes back to a stale app.
 *  - one reload on controllerchange — skipWaiting/clientsClaim already make
 *    the new worker take over; without a reload the page keeps rendering
 *    the old assets it booted with. The flag guards against reload loops.
 */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js', { scope: '/', updateViaCache: 'none' })
      .then((registration) => {
        const check = () => registration.update().catch(() => {})
        document.addEventListener('visibilitychange', () => {
          if (document.visibilityState === 'visible') check()
        })
        window.setInterval(check, 60 * 60 * 1000)
      })
      .catch(() => {})

    // clientsClaim also fires controllerchange when a FIRST worker adopts an
    // uncontrolled page — that's adoption, not an update, and must not reload.
    let hadController = !!navigator.serviceWorker.controller
    let reloaded = false
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!hadController) {
        hadController = true
        return
      }
      if (reloaded) return
      reloaded = true
      window.location.reload()
    })
  })
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
