import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // The widget bundle is a separate build (vite.widgets.config.ts) the
      // backend serves from dist/.
      '/widgets.js': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
