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
    // Phase 1c polish: 拆 vendor bundle 提升 cache hit rate
    // React 单独 chunk 几乎不变；UI 库（Mantine + recharts + dayjs）也单独
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
          'ui-vendor': [
            '@mantine/core',
            '@mantine/hooks',
            '@mantine/notifications',
            '@mantine/charts',
            '@mantine/dates',
            'dayjs',
            'recharts',
          ],
        },
      },
    },
    chunkSizeWarningLimit: 800,  // raised from default 500 to accommodate vendor chunks
  },
})
