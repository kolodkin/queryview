import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The dashboard widget bundle (src/widgets.tsx): one classic script the
// sandboxed dashboard frame loads. An IIFE, not a module, because a module
// script would need CORS from the frame's opaque origin.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { 'process.env.NODE_ENV': '"production"' },
  build: {
    outDir: 'dist',
    emptyOutDir: false,
    copyPublicDir: false,
    lib: {
      entry: 'src/widgets.tsx',
      formats: ['iife'],
      name: 'QvWidgets',
      fileName: () => 'widgets.js',
    },
  },
})
