import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { existsSync, readFileSync } from 'node:fs'
import type { Plugin } from 'vite'

// The dashboard widget bundle is its own build (vite.widgets.config.ts, run in
// watch mode by `npm run dev`); the dev server hands out its output.
const widgetsBundle: Plugin = {
  name: 'widgets-bundle',
  configureServer(server) {
    server.middlewares.use('/widgets.js', (_req, res) => {
      if (!existsSync('dist/widgets.js')) {
        res.statusCode = 404
        res.end('// widgets.js is still building')
        return
      }
      res.setHeader('Content-Type', 'text/javascript')
      res.end(readFileSync('dist/widgets.js'))
    })
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), widgetsBundle],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
