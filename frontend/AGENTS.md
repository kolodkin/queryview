# Frontend

- `src/core` is backend-agnostic: it never fetches, routes, or reads app state
  (`npm run lint` enforces this). `src/app` imports it only through
  `src/core/index.ts`.
- `README.md` here describes the layout and commands.
