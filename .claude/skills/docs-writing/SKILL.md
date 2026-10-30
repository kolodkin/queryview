---
name: docs-writing
description: Use when adding or editing a page under docs/ in this repo — it adds the house style that devpowers:shortify leaves to project convention.
---

# Docs writing

This extends `devpowers:shortify`, which owns brevity, heading depth, and
link hygiene; its checklist is not repeated here. Finish every docs edit by
running shortify on the pages you touched.

## House style

- One page per feature, `docs/<feature>.md`; a change to an existing feature
  is a section on its page. Copy the shape of the nearest existing page.
- Present tense, describing current behavior.
  No history ("now", "previously", "since vX"); proposals go in `future.md`
  and move into the feature's page when they ship.
- The opening paragraph names the route (`/queryview`, `/explorer`, …) and
  links the neighboring pages a reader may have meant instead.
- UI labels are **bold**, exactly as the screen shows them. A page about a
  screen may open with a layout sketch; the `devpowers:ui-sketch` skill draws it.
- `api.md` is the endpoint reference. A feature page's `## API` section names
  its endpoints and links there, as `scripts.md` does; bodies and responses are
  not repeated.
- Links are relative, `./page.md#anchor`. Code is named only when the reader
  must open it, as a module or package path. Code and docstrings that back-link
  a heading quote it word for word, so grep for the old text when renaming one.
- End with `## Related docs`: a bullet per linked page with a short phrase.
- Example names are invented (`sales_reporting`, `example.internal`), per the
  root `AGENTS.md` privacy rule.
