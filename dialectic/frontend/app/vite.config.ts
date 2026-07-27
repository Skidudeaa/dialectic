import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
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
