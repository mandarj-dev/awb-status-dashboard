import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// In dev, /api is proxied to the FastAPI backend.
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: { '/api': { target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000', changeOrigin: true } },
  },
})
