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

`src/core` never fetches, routes, or reads app state; `npm run lint` enforces
that.
