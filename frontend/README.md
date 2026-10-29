# QueryView frontend

React 19 + TypeScript + Vite + Tailwind. `npm run dev` proxies `/api` to the
backend on port 8000; `npm run build` emits `dist/`, which the release workflow
copies into the Python package.

## Layout

```
src/
  core/    backend-agnostic kernel — result parsing, cell rendering, query
           params, presentation pickers, the dashboard sandbox
  app/     the QueryView application — pages, connections, workspaces, git sync
  main.tsx
```

Tests sit next to their modules (`npm test`); `npm run lint` checks the
`core`/`app` boundary described in `AGENTS.md`.
