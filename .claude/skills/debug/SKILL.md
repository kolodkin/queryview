---
name: debug
description: Run this repo's QueryView on a port (default 8000) via `npm run debug` and point the queryview MCP server at it, e.g. "/debug 9000".
argument-hint: "[port]"
---

Port: `$ARGUMENTS`, or `8000` if empty.

1. Unless `curl -sf http://localhost:<port>/api/health` already succeeds, run
   `npm ci` if `node_modules` is missing, then start it with
   `run_in_background: true` and poll that URL until it's up:

   ```bash
   PORT=<port> npm run debug
   ```

2. Register the MCP server (local scope, never in `.mcp.json`):

   ```bash
   claude mcp remove queryview -s local 2>/dev/null
   claude mcp add --transport http -s local queryview http://localhost:<port>/mcp/
   ```

3. Tell the user to reconnect via `/mcp` to load the tools.
