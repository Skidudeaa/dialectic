import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icons/apple-touch-icon.png', 'icons/favicon.svg'],
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
      workbox: {
        // The SPA fallback must never swallow API or WebSocket routes — nginx
        // proxies this whole set to the backend on the same origin. Keep in
        // step with the dev proxy list below.
        navigateFallbackDenylist: [
          /^\/(api|ws|auth|rooms|threads|users|health|analytics|graph|replay|stakes|messages|memories|personas|notifications|openapi)\b/,
        ],
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/fonts\.googleapis\.com\/.*/i,
            handler: 'StaleWhileRevalidate',
            options: { cacheName: 'google-fonts-css' },
          },
          {
            urlPattern: /^https:\/\/fonts\.gstatic\.com\/.*/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'google-fonts-static',
              expiration: { maxEntries: 24, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
    }),
  ],
  server: {
    port: 3000,
    proxy: {
      '/api': { target: 'http://localhost:8002', changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') },
      '/ws': { target: 'ws://localhost:8002', ws: true },
      '/auth': { target: 'http://localhost:8002', changeOrigin: true },
      '/rooms': { target: 'http://localhost:8002', changeOrigin: true },
      '/threads': { target: 'http://localhost:8002', changeOrigin: true },
      '/users': { target: 'http://localhost:8002', changeOrigin: true },
      '/health': { target: 'http://localhost:8002', changeOrigin: true },
      '/analytics': { target: 'http://localhost:8002', changeOrigin: true },
      '/graph': { target: 'http://localhost:8002', changeOrigin: true },
      '/replay': { target: 'http://localhost:8002', changeOrigin: true },
      '/stakes': { target: 'http://localhost:8002', changeOrigin: true },
      // WHY these were added: nginx proxies this whole set in production
      // (see the location regex in sites-available/dialectic), but dev was
      // missing them — so /messages/search returned index.html here and JSON in
      // production. Keep the two lists in step.
      '/messages': { target: 'http://localhost:8002', changeOrigin: true },
      '/memories': { target: 'http://localhost:8002', changeOrigin: true },
      '/personas': { target: 'http://localhost:8002', changeOrigin: true },
      '/notifications': { target: 'http://localhost:8002', changeOrigin: true },
    },
  },
})
