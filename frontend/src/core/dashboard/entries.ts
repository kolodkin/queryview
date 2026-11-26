// A dashboard query entry is a SQL string, or a map `{connection, sql,
// database?}` naming the connection it runs on. A dashboard is **federated**
// when its queries are maps (each `options_sql` param then carries
// `connection` too), **unfederated** when they are strings; the backend
// refuses a mix (backend/queryview/dashboard_entries.py). These accessors let
// the page read and edit either kind, and switch a whole dashboard between them.

export type QueryEntry = string | { connection: string; sql: string; database?: string }

// One connection of a federated run's reply, in first-use order.
export type FederatedConnection = {
  name: string
  database: string | null
  status: 'ok' | 'failed' | 'locked' | 'unknown'
  queries: string[]
  message?: string
}

type Queries = Record<string, QueryEntry>

export const entrySql = (e: QueryEntry): string => (typeof e === 'string' ? e : e.sql)

export const entryConnection = (e: QueryEntry): string | null =>
  typeof e === 'string' ? null : e.connection

// A string stays a string; a map keeps its connection and database.
export const withSql = (e: QueryEntry, sql: string): QueryEntry =>
  typeof e === 'string' ? sql : { ...e, sql }

// The database belongs to the connection: kept only when the name is unchanged.
export function withConnection(e: QueryEntry, connection: string): QueryEntry {
  if (typeof e !== 'string' && e.connection === connection) return e
  return { connection, sql: entrySql(e) }
}

export const isFederated = (queries: Queries): boolean =>
  Object.values(queries).some((e) => typeof e !== 'string')

const mapValues = (queries: Queries, f: (e: QueryEntry) => QueryEntry): Queries =>
  Object.fromEntries(Object.entries(queries).map(([n, e]) => [n, f(e)]))

const hasOptionsSql = (p: unknown): p is Record<string, unknown> =>
  !!p && typeof p === 'object' && 'options_sql' in p

// Every query and `options_sql` param runs on `connection`.
export function federate(queries: Queries, params: unknown[], connection: string) {
  return {
    queries: mapValues(queries, (e) => withConnection(e, connection)),
    params: params.map((p) => (hasOptionsSql(p) ? { ...p, connection } : p)),
  }
}

// Every query becomes its SQL; params drop `connection` and `database`.
export function unfederate(queries: Queries, params: unknown[]) {
  return {
    queries: mapValues(queries, entrySql),
    params: params.map((p) => {
      if (!p || typeof p !== 'object') return p
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { connection, database, ...rest } = p as Record<string, unknown>
      return rest
    }),
  }
}

// The connections the queries name, in first-use order, each once.
export const connectionNames = (queries: Queries): string[] => [
  ...new Set(Object.values(queries).flatMap((e) => entryConnection(e) ?? [])),
]
