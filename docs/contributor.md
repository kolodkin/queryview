# Contributor notes

Notes for working on QueryView that no test proves; setup and the test
commands are in [CONTRIBUTING.md](../CONTRIBUTING.md).

## CI

CI runs a real `clickhouse/clickhouse-server` service container so the e2e suite
exercises an actual connection: it asserts that connecting succeeds, a database
can be selected, the indicator shows `<connection> · <database>`, and a query
against a seeded `test` database returns its rows.

## Related docs

- [storage.md](./architecture/storage.md) — the data directory and migrations.
