# Commit Guideline

1. Avoid `Co-Authored-By: Claude` (and similar Claude/AI attribution) trailers in
   commit messages and PR bodies.

# Data Privacy

1. **Never commit tenant data.** Real customer, tenant, or environment
   identifiers (database and table names, hostnames, account or user names,
   query results, screenshots of live data) must not appear in code, tests,
   fixtures, docs, or commit messages.
2. **Always anonymize.** When an example needs realistic-looking data, invent
   generic names (e.g. `sales_reporting`, `example.internal`). Rewrite any
   pasted samples before using them.
3. If tenant data slips into history, rewrite the commits to remove it and
   force-push the branch rather than adding a follow-up commit.

# Operational Guidelines

1. Use `uv run` (e.g. `uv run pytest`, `uv run python ...`), not `python -m` or a
   manually activated virtualenv.

# Tests

1. Pytest tests live side by side with the code they test, inside the relevant
   module package (e.g. `backend/queryview/test_queries.py`,
   `backend/queryview/drivers/test_clickhouse.py`), with shared fixtures in
   `backend/queryview/conftest.py`. They ship in the wheel, and the release
   workflow runs them against the installed package
   (`pytest --pyargs queryview`).
2. Exception: e2e (Playwright) tests live in the top-level `e2e/` folder —
   they test the running app through its HTTP surface, not a module.

# Conventions

## Docs

- **Remove superpowers plans and designs once implemented.** Files under
  `docs/superpowers/plans/` and `docs/superpowers/specs/` exist only while the
  work is pending; when a plan ships, delete its plan and spec in the same
  change (the feature's page under `docs/` is the doc of record) and fix any
  links that pointed at them.

## Python

- **Avoid `__all__`.** Don't declare `__all__` in modules or packages. Keep the
  public surface implicit: import a name where it's defined (e.g.
  `from queryview.drivers.base import DriverConfig`) rather than re-exporting it
  through a package `__init__` and listing it in `__all__`. A package `__init__`
  may still import names it genuinely uses (e.g. building a registry), but it
  should not maintain an explicit export list.
