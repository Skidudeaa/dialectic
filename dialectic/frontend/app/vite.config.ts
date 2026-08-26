/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import type { ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { cpSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import type { Plugin } from 'vite'
import sirv from 'sirv'

// CesiumJS needs its static tree (Workers, Assets, ThirdParty, Widgets) served
// at a known URL — `window.CESIUM_BASE_URL`. Dev serves it straight from
// node_modules; build copies it into dist/cesium. ~8MB that must NEVER enter
// the PWA precache (see globIgnores below) — World is opened on purpose, and
// the vision forbids a bundle or cache regression for users who never open it.
function cesiumAssets(): Plugin {
  const require = createRequire(import.meta.url)
  const root = join(dirname(require.resolve('cesium/package.json')), 'Build', 'Cesium')
  const dirs = ['Workers', 'Assets', 'ThirdParty', 'Widgets']
  return {
    name: 'dialectic-cesium-assets',
    configureServer(server) {
      server.middlewares.use('/cesium', sirv(root, { dev: true }))
    },
    configurePreviewServer(server) {
      server.middlewares.use('/cesium', sirv(root, { dev: true }))
    },
    closeBundle() {
      if (!existsSync(root)) return
      for (const dir of dirs) cpSync(join(root, dir), join('dist', 'cesium', dir), { recursive: true })
    },
  }
}

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
  define: { CESIUM_BASE_URL: JSON.stringify('/cesium/') },
  plugins: [
    react(),
    cesiumAssets(),
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
      injectManifest: {
        // React.lazy owns the complete WorldView/Cesium dependency graph.
        // Neither that JS/CSS nor Cesium's static tree belongs in the base
        // install; all are fetched only when a person opens World.
        globIgnores: ['**/WorldView-*.js', '**/WorldView-*.css', 'cesium/**', '**/node_modules/**'],
      },
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
