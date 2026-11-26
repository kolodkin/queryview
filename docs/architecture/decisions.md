# Decisions

Decisions that span several architecture pages.

## Why folder mode lists one level at a time

The folder list is read per level, centred on the selected folder, rather than
scanned across the whole tree at connect:

- **The limit trims a view, not reachability.** With a whole-tree scan, a cap
  hides deep folders whenever the tree grows or the cap drops, and a restart
  or a saved dashboard then loses the selected folder. Per level, the selected
  folder is reached by its path, so neither can drop it.
- **Connect costs one directory read** on any root size, instead of a scan
  bounded only by the cap.
- **Checking each step of the path,** not just the final folder, is what keeps
  a symlink partway along (`link` -> `/etc`) from leading outside the root.
- **A missing step stops at the nearest parent** rather than the root, so a
  deleted folder leaves the user as close as possible to where they were.
- The cost: the menu re-reads a level on each pick, and an agent listing
  folders without a selection sees only the root's top level.

## Why a param value is matched as the page's text

A request's param value ([api.md](./api.md), [mcp.md](./mcp.md),
[viewer_server_api.md](./viewer_server_api.md)) is compared with the options
as the text the page shows for them. A number or boolean becomes that text
(`2`, `true`), and a value no option offers takes the param's default without
an error:

- **One rule for every caller.** The page sends the option text it showed, so
  an agent or a script sending `2` selects the same option the page would.
- **No guessing across spellings.** `false` does not select an option declared
  as the string `"False"`: matching case-insensitively would make `"false"`
  and `"False"` one option where a dashboard declares both.
- **A stale value is not an error.** A selection saved before the options
  changed falls back to the default, so an unoffered value has to do the same.
- The cost: a mistyped value runs the default silently. The reply's `params`
  carries each param's `options` and chosen `value`, which is where a caller
  sees it.

## Related docs

- [explorer.md](../system/explorer.md) — the table navigator.
- [dashboard.md](../system/dashboard.md#dashboard-parameters) — dashboard parameters.
