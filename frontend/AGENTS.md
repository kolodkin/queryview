# Frontend

React 19 + TypeScript + Vite + Tailwind. `npm run dev` proxies `/api` to the
backend on port 8000; `npm run build` emits `dist/`.

```
src/
  core/    backend-agnostic kernel — result parsing, cell rendering, query
           params, presentation pickers, the dashboard sandbox
  app/     the QueryView application — pages, connections, workspaces, git sync
  main.tsx
```

`src/core` never fetches, routes, reads app state, or imports outside itself;
`npm run lint` enforces that. It brings its own stylesheet (`core/kernel.css`,
which the app's `index.css` imports); never hardcode an accent colour in core
markup, read a `--qv-*` token (`text-[var(--qv-accent-text)]`) so hosts can
theme it.
