# Decisions

Decisions that span several architecture pages.

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

- [dashboard.md](../user_guide/dashboard.md#dashboard-parameters) — dashboard parameters.
