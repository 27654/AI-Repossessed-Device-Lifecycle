import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dev server proxies API requests to Django so the browser sees
// a single origin: session and CSRF cookies work without cross-site setup.
const backend = process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
    },
  },
})
