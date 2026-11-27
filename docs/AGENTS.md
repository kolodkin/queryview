# Docs

- `docs/` is the doc of record: what the app does today. Before adding or
  editing a page, load the project `vmodel` skill.
- One folder per layer:
  - `docs/user_guide/`: one page per feature, a guide to what you can see and
    do; published from `README.md`.
  - `docs/architecture/`: topology, data model, wire contracts, security model.
  - `docs/designs/`: how components work together inside the system.
- A page holds one layer's content. A statement a test proves carries a
  `<!-- req: <slug> -->` comment on the line above it (the page's path gives
  the ID's prefix); the project `vmodel` skill says how.
- The viewer server (`queryview-server`) follows the same layers. Its docs
  never go in an app page; an app page only links in.
- A new guide page joins the `README.md` docs list; any other new page joins
  `CONTRIBUTING.md`.
- **A design is written before it is built**, as
  `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` (the
  `superpowers:brainstorming` shape), and the user reads it first. Never into
  `future.md`: that page holds proposals nobody is building yet.
- **Remove superpowers plans and designs once implemented.** Files under
  `docs/superpowers/plans/` and `docs/superpowers/specs/` exist only while the
  work is pending; when a plan ships, delete its plan and spec in the same
  change and fix any links that pointed at them.
