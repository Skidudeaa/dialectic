import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

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
