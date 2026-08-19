/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import type { ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// WHY parameterized: browser acceptance runs the built app against an
// ISOLATED backend (test database, spare port) — never production .env.
// Default stays the dev backend on 8002.
const backend = process.env.DIALECTIC_BACKEND_URL ?? 'http://localhost:8002'
const backendWs = backend.replace(/^http/, 'ws')

// WHY this list exists twice in the repo: nginx proxies the same set in
// production (see the location regex in sites-available/dialectic), but dev
// was missing entries — so /messages/search returned index.html here and
// JSON in production. Keep the two lists in step.
function proxyMap(): Record<string, ProxyOptions> {
  return {
    '/api': { target: backend, changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') },
    // Attachments stream through the backend with auth headers; without
    // this line `npm run dev` serves the SPA fallback for them (media
    // broken in dev only — prod routes via nginx).
    '/attachments': { target: backend, changeOrigin: true },
    '/ws': { target: backendWs, ws: true },
    '/auth': { target: backend, changeOrigin: true },
    '/rooms': { target: backend, changeOrigin: true },
    '/threads': { target: backend, changeOrigin: true },
    '/users': { target: backend, changeOrigin: true },
    '/health': { target: backend, changeOrigin: true },
    '/analytics': { target: backend, changeOrigin: true },
    '/graph': { target: backend, changeOrigin: true },
    '/replay': { target: backend, changeOrigin: true },
    '/stakes': { target: backend, changeOrigin: true },
    '/messages': { target: backend, changeOrigin: true },
    '/memories': { target: backend, changeOrigin: true },
    '/personas': { target: backend, changeOrigin: true },
    '/notifications': { target: backend, changeOrigin: true },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      // Hand-written worker (src/sw.ts): precaching + SPA fallback + fonts,
      // PLUS the push/notificationclick handlers generateSW cannot express.
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      registerType: 'autoUpdate',
      // Registration lives in main.tsx (updateViaCache + resume checks +
      // controllerchange reload) — the injectable one-liner can't do any of
      // that and is what let installed PWAs run stale bundles for hours.
      injectRegister: false,
      includeAssets: ['icons/apple-touch-icon.png', 'icons/favicon.svg', 'fonts/*.woff2', 'fonts/DSEG-LICENSE.txt'],
      manifest: {
        name: 'Dialectic',
        short_name: 'Dialectic',
        description: 'Two humans and an LLM co-reasoning in real time.',
        start_url: '/',
        display: 'standalone',
        background_color: '#120C06',
        theme_color: '#120C06',
        icons: [
          { src: '/icons/pwa-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/pwa-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/pwa-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
    }),
  ],
  server: {
    port: 3000,
    proxy: proxyMap(),
  },
  // Browser acceptance drives the PRODUCTION build through vite preview,
  // pointed at the isolated backend via DIALECTIC_BACKEND_URL.
  preview: {
    port: 4173,
    proxy: proxyMap(),
  },
  // WHY here and not a separate vitest.config.ts: one Vite configuration means
  // the test run and the dev/preview servers cannot drift apart on the proxy
  // map above, which is the seam browser acceptance depends on.
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    restoreMocks: true,
  },
})
