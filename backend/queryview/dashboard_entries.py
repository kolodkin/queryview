"""A dashboard query entry: a SQL string, run on the viewer's connection, or a
map `{connection, sql, database?}` naming a stored connection and, optionally,
its database. A dashboard is one kind: every entry and every `options_sql`
param names a connection (federated), or none does; `MIXED` otherwise.

Two checks share the shape. `queries_error` is strict, for the agent tools,
import and git sync: it names what is malformed. `clean_queries` is lenient,
for Save and run requests: it keeps the entries that can run and drops the
rest. A string entry is never judged here beyond being a string."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

Entry = str | dict[str, str]

MIXED = "every query and options_sql names a connection, or none does"

_KEYS = ("connection", "sql", "database")


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def map_error(entry: dict[str, Any]) -> str | None:
    """Why a map entry is malformed, or None."""
    for key in entry:
        if key not in _KEYS:
            return f"unknown key {key!r}"
    for key in ("sql", "connection"):
        if not _text(entry.get(key)):
            return f"{key} must be a non-empty string"
    if "database" in entry and not _text(entry["database"]):
        return "database must be a non-empty string"
    return None


def queries_error(raw: object) -> str | None:
    """Strict: why `raw` is not a {name: entry} map, or None. Strings pass whatever they hold."""
    if not isinstance(raw, dict):
        return "queries must be a {name: SQL} map"
    for name, entry in raw.items():
        if not isinstance(name, str) or not isinstance(entry, (str, dict)):
            return "queries must be a {name: SQL} map"
        if isinstance(entry, dict) and (why := map_error(entry)):
            return f"query {name!r}: {why}"
    return None


def clean_queries(raw: object) -> dict[str, Entry]:
    """Lenient: the entries of `raw` with a non-empty name that can run."""
    if not isinstance(raw, dict):
        return {}
    return {
        k: v
        for k, v in raw.items()
        if isinstance(k, str) and k and (v.strip() if isinstance(v, str) else isinstance(v, dict) and not map_error(v))
    }


def entry_sql(entry: Entry) -> str:
    return entry if isinstance(entry, str) else entry["sql"]


def entry_connection(entry: Entry) -> tuple[str, str | None] | None:
    """`(connection, database)` of a map entry, None for a string."""
    return None if isinstance(entry, str) else (entry["connection"], entry.get("database"))


def is_federated(queries: Mapping[str, Entry], params: object) -> bool:
    """Whether the dashboard names connections; ValueError(MIXED) when it only partly does."""
    named = [not isinstance(e, str) for e in queries.values()]
    if isinstance(params, list):
        named += [bool(p.get("connection")) for p in params if isinstance(p, dict) and p.get("options_sql")]
    if any(named) and not all(named):
        raise ValueError(MIXED)
    return bool(named) and named[0]
