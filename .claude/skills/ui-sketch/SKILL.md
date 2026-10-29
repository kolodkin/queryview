---
name: ui-sketch
description: Use when a doc page, design note or chat answer needs to show a screen, panel or layout — draws the ASCII layout sketch this repo's docs use.
---

# UI sketch

One box per screen or panel, drawn with `┌ ─ ┐ │ └ ┘`, followed by a bullet
per control. Show structure, not pixels: a reader should see what is where
and what it is called. Example: the query panel.

```
┌───────────────────────────────────────────────┐
│ 🟢 default              ← connection status    │
│ [ query ]  [ Predefined queries… ▾ ]  [ Save ] │
│ ┌───────────────────────────────────────────┐  │
│                                                │  SELECT …                                  │ │  ← SQL textarea
│ └───────────────────────────────────────────┘  │
│ [Execute] [Fields]  Limit [100]  Offset [0]    │
└───────────────────────────────────────────────┘
```

- `[Label]` is a button, `[ value ]` an input, `▾` a dropdown, `…` content
  cut short, `🟢` a status dot.
- A nested box is a region: textarea, table, card, sidebar.
- Annotate with `← note` to the right, outside or at the edge of the box;
  no prose inside the drawing.
- Labels read exactly as the screen shows them, and the bullets below use the
  same labels in **bold**.
- Keep it under 15 lines; a second sketch is for a different state (a
  modal, an empty state), not more detail.
