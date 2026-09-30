// Frontend driver registry: drives the Connect page's "new connection" cards,
// the badge on each saved card, and the connection form.
export type DriverField = {
  key: string
  label: string
  testid: string
  type: 'text' | 'password'
  default: string
}

export type DriverMeta = {
  type: string
  label: string
  // One line under the driver's name on its "new connection" card.
  blurb: string
  // Two-letter monogram and its tint, shared by the new and saved cards.
  mark: string
  accent: string
  fields: DriverField[]
  formTestid: string
  testTestid: string
  connectTestid: string
  resultTestid: string
}

export const DRIVERS: Record<string, DriverMeta> = {
  clickhouse: {
    type: 'clickhouse',
    label: 'ClickHouse',
    blurb: 'Columnar analytics over HTTP',
    mark: 'CH',
    accent: 'bg-amber-400/15 text-amber-200 ring-amber-300/30',
    formTestid: 'clickhouse-form',
    testTestid: 'ch-test',
    connectTestid: 'ch-connect',
    resultTestid: 'ch-result',
    fields: [
      { key: 'name', label: 'Name', testid: 'ch-name', type: 'text', default: 'clickhouse' },
      { key: 'host', label: 'Host', testid: 'ch-host', type: 'text', default: 'localhost' },
      { key: 'port', label: 'Port', testid: 'ch-port', type: 'text', default: '8123' },
      { key: 'username', label: 'Username', testid: 'ch-username', type: 'text', default: 'default' },
      { key: 'password', label: 'Password', testid: 'ch-password', type: 'password', default: '' },
    ],
  },
  postgres: {
    type: 'postgres',
    label: 'Postgres',
    blurb: 'Relational database server',
    mark: 'PG',
    accent: 'bg-sky-400/15 text-sky-200 ring-sky-300/30',
    formTestid: 'postgres-form',
    testTestid: 'pg-test',
    connectTestid: 'pg-connect',
    resultTestid: 'pg-result',
    fields: [
      { key: 'name', label: 'Name', testid: 'pg-name', type: 'text', default: 'postgres' },
      { key: 'host', label: 'Host', testid: 'pg-host', type: 'text', default: 'localhost' },
      { key: 'port', label: 'Port', testid: 'pg-port', type: 'text', default: '5432' },
      { key: 'username', label: 'Username', testid: 'pg-username', type: 'text', default: 'postgres' },
      { key: 'password', label: 'Password', testid: 'pg-password', type: 'password', default: '' },
    ],
  },
  duckdb: {
    type: 'duckdb',
    label: 'DuckDB',
    blurb: 'Local file or in-memory',
    mark: 'DK',
    accent: 'bg-lime-400/15 text-lime-200 ring-lime-300/30',
    formTestid: 'duckdb-form',
    testTestid: 'duck-test',
    connectTestid: 'duck-connect',
    resultTestid: 'duck-result',
    fields: [
      { key: 'name', label: 'Name', testid: 'duck-name', type: 'text', default: 'duckdb' },
      { key: 'path', label: 'Path', testid: 'duck-path', type: 'text', default: ':memory:' },
    ],
  },
}
