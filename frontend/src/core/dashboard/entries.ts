// A dashboard query entry is a SQL string, or a map `{connection, sql,
// database?}` naming the connection it runs on. A dashboard is **federated**
// when its queries are maps or its `options_sql` params carry `connection`,
// **unfederated** when neither does; the backend
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

const mapValues = (queries: Queries, f: (e: QueryEntry) => QueryEntry): Queries =>
  Object.fromEntries(Object.entries(queries).map(([n, e]) => [n, f(e)]))

const hasOptionsSql = (p: unknown): p is Record<string, unknown> =>
  !!p && typeof p === 'object' && 'options_sql' in p

const paramConnections = (params: unknown[]): string[] =>
  params.flatMap((p) => (hasOptionsSql(p) && typeof p.connection === 'string' ? [p.connection] : []))

// A query map, or (with no query naming one) an `options_sql` param's connection.
export const isFederated = (queries: Queries, params: unknown[] = []): boolean =>
  Object.values(queries).some((e) => typeof e !== 'string') || paramConnections(params).length > 0

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

// The federated pill's rows: every connection the dashboard names (its
// queries, a widget's included, then its `options_sql` params), in first-use
// order; each as the run's `reply` reports it (one row per database), else
// the name alone. A run leaves widget queries out, so its reply alone may miss one.
export function federatedRows(
  queries: Queries,
  params: unknown[],
  reply?: FederatedConnection[],
): (FederatedConnection | string)[] {
  const names = new Set([...connectionNames(queries), ...paramConnections(params)])
  return [...names].flatMap((n): (FederatedConnection | string)[] => {
    const rows = reply?.filter((c) => c.name === n) ?? []
    return rows.length ? rows : [n]
  })
}
