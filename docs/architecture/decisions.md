# Decisions

The decisions behind how folder mode lists folders ([explorer.md](../system/explorer.md)).

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

## Related docs

- [explorer.md](../system/explorer.md) — the table navigator.
