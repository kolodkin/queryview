import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { createHash } from 'node:crypto'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
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

// A built app asks for /widgets.js?v=<hash of the sources>, which the backend
// lets browsers cache for good; the dev server's stays plain so edits show.
function widgetsUrl(): string {
  const hash = createHash('sha256')
  for (const f of readdirSync('src', { recursive: true, withFileTypes: true })) {
    if (f.isFile()) hash.update(readFileSync(`${f.parentPath}/${f.name}`))
  }
  return `/widgets.js?v=${hash.digest('hex').slice(0, 12)}`
}

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  define: { __WIDGETS_URL__: JSON.stringify(command === 'build' ? widgetsUrl() : '/widgets.js') },
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
}))
