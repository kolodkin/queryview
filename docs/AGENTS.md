# Docs

- `docs/` is the doc of record: what the app does today. Before adding or
  editing a page, load the project `vmodel` skill.
- One folder per layer:
  - `docs/requirements/`: what a user needs; no design, no screen detail.
  - `docs/system/`: one page per feature, what a user can see or do.
  - `docs/architecture/`: components, contracts between them, storage,
    interface references.
- A page holds one layer's content. A statement a test proves carries a
  `<!-- req: <id> -->` comment on the line above it; the project `vmodel` skill
  says how.
- The viewer server (`queryview-server`) follows the same layers. Its docs
  never go in an app page; an app page only links in.
- A new page joins the `README.md` docs list under its layer's heading. A page
  with no layer (it states nothing a test in the repo can prove) goes at the
  root of `docs/`.
- **A design is written before it is built**, as
  `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` (the
  `superpowers:brainstorming` shape), and the user reads it first. Never into
  `future.md`: that page holds proposals nobody is building yet.
- **Remove superpowers plans and designs once implemented.** Files under
  `docs/superpowers/plans/` and `docs/superpowers/specs/` exist only while the
  work is pending; when a plan ships, delete its plan and spec in the same
  change and fix any links that pointed at them.
