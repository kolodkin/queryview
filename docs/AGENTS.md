# Docs

- `docs/` is the doc of record: one page per feature, describing what the app
  does today. Before adding or editing a page, load the project `docs-writing`
  skill.
- A new page joins the docs list at the end of `README.md`.
- **A design is written before it is built**, as
  `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` (the
  `superpowers:brainstorming` shape), and the user reads it first. Never into
  `future.md`: that page holds proposals nobody is building yet.
- **Remove superpowers plans and designs once implemented.** Files under
  `docs/superpowers/plans/` and `docs/superpowers/specs/` exist only while the
  work is pending; when a plan ships, delete its plan and spec in the same
  change and fix any links that pointed at them.
