import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: Vite 5173 + FastAPI 18787 (separate processes). /api proxied.
// Prod: uvicorn serves both bundle and API on 18787 (StaticFiles mount).
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:18787',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
