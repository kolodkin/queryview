# Script splitting

How the Scripts page and the server agree on a script's statements. What a
user sees of the split is in [scripts.md](../user_guide/scripts.md#statements).

## One split, twice

<!-- req: same-split -->
The server and the page split a script into the same statements. The server
runs each one; the page uses the split to find the statement under the cursor
(**▶ Run**) and to mark the k-th statement when the k-th result failed. Both
first blank every quote and comment to spaces, keeping the text's length, then
cut at each `;` left; on MySQL both read MySQL's comments. The backend's
version is `mask_sql` in the `queryview/drivers/` package, the page's is in
`frontend/src/app/scriptRun.ts`; one list of scripts and their statements,
`split_cases.json` in the drivers package, is checked against both.

## Why

The page splits for itself because **▶ Run** must know the statement before
anything is sent, without a round trip. The server splits again rather than
trust the page's, because an agent's `run_script` has no page.

## Related docs

- [scripts.md](../user_guide/scripts.md) — the Scripts page and its statements.
- [mcp.md](../architecture/mcp.md) — `run_script`, the agent's way in.
