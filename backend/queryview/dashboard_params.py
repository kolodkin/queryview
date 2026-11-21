"""Dashboard parameters: selectors declared in a dashboard's `params` and
substituted into its queries via `{name}` placeholders.

See docs/dashboard.md — "Dashboard parameters".

    value       a literal: {region} -> 'eu'
    identifier  a table/column: {field} -> "city"
    dimension   an optional GROUP BY column: checked -> its own column, else ''
    text        whatever the user typed, as a literal: {note} -> 'o''k'

Pure: no session, request or driver. The caller passes the dialect and a
runner for `options_sql`."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

# The longest text a page may send into a query.
MAX_TEXT_PARAM = 10_000

KINDS = ("value", "identifier", "dimension", "text")
CASTS = ("literal", "identifier")
# `{name}` substitutes per the param's kind; `{name:literal}` / `{name:identifier}`
# override it for that one spot: a table is an identifier in `FROM {table}` but
# a string in `WHERE table = {table:literal}`.
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::([A-Za-z_]+))?\}")


class ParamError(ValueError):
    """A value or declaration that cannot be substituted; the message is shown to the user."""


@dataclass(frozen=True)
class Dialect:
    """How a connection quotes: its identifier quote, and whether backslash escapes."""

    quote: str
    backslash_escapes: bool


@dataclass(frozen=True)
class Param:
    name: str
    kind: str
    options: tuple[str, ...] | None = None
    options_sql: str | None = None
    # Whether the first option is chosen for you. `default: none` leaves the
    # selector empty, holding back queries that need it until a choice is made.
    auto_select: bool = True
    # A text param's opening value (its `default`, else empty).
    text: str | None = None


# One options_sql -> its first column's values. Raises ParamError on failure.
Runner = Callable[[str], Awaitable[list[Any]]]


def option_text(v: Any) -> str:
    """An option as the browser's String() showed it, so stored selections keep matching."""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def parse_params(raw: object) -> list[Param]:
    """The `params` list. Defensive: a malformed entry is dropped, so a broken
    declaration costs one selector, not the dashboard."""
    if not isinstance(raw, list):
        return []
    out: list[Param] = []
    for o in raw:
        if not isinstance(o, dict):
            continue
        name = o.get("name")
        if not isinstance(name, str) or not name:
            continue
        kind = "value" if o.get("kind") is None else o["kind"]
        if kind not in KINDS:
            continue
        default = o.get("default")
        auto_select = default != "none"
        options = o.get("options")
        has_options = isinstance(options, list)
        sql = o["options_sql"].strip() if isinstance(o.get("options_sql"), str) else ""
        if has_options and sql:
            continue  # ambiguous
        if kind == "text":
            if has_options or sql:
                continue  # free input has no list to pick from
            text = default if auto_select and isinstance(default, str) else ""
            out.append(Param(name, kind, auto_select=auto_select, text=text))
        elif sql:
            out.append(Param(name, kind, options_sql=sql, auto_select=auto_select))
        elif has_options:
            texts = tuple(option_text(v) for v in options if v is not None and not isinstance(v, (dict, list)))
            if texts:
                out.append(Param(name, kind, options=texts, auto_select=auto_select))
        elif kind == "dimension":
            out.append(Param(name, kind, auto_select=auto_select))  # a checkbox: no option list
    return out


def placeholders_in(sql: str) -> list[str]:
    """The `{name}` placeholders a query references, in order of first appearance."""
    return list(dict.fromkeys(m.group(1) for m in _PLACEHOLDER.finditer(sql)))


def _quote_literal(value: str, dialect: Dialect) -> str:
    """A quoted SQL string literal: single quotes doubled, and backslashes too
    where the dialect reads them as escapes."""
    v = value.replace("\\", "\\\\") if dialect.backslash_escapes else value
    return "'" + v.replace("'", "''") + "'"


def _quote_identifier(name: str, param: str, dialect: Dialect) -> str:
    # A quote character (or a backslash that would escape it) can't be trusted
    # through string assembly, and no real name carries one, so reject it.
    if dialect.quote in name or (dialect.backslash_escapes and "\\" in name):
        raise ParamError(f"invalid identifier for {{{param}}}: {name}")
    return f"{dialect.quote}{name}{dialect.quote}"


def _is_checked(v: str | None) -> bool:
    """A dimension's checkbox state; a page may send 0 for unchecked."""
    return bool(v) and v != "0"


def substitute(sql: str, params: list[Param], values: dict[str, str], dialect: Dialect) -> str:
    """Replace every declared `{name}`; placeholders with no matching param are
    left alone (they may be literal braces in the SQL)."""
    by_name = {p.name: p for p in params}

    def replace(m: re.Match[str]) -> str:
        name, cast = m.group(1), m.group(2)
        p = by_name.get(name)
        if p is None:
            return m.group(0)
        if cast and cast not in CASTS:
            raise ParamError(f"unknown cast for {{{name}}}: {cast}")
        raw = values.get(name)
        if p.kind == "dimension":
            # Unchecked: an empty literal keeps the query's shape; the column
            # just contributes nothing to the grouping.
            return _quote_identifier(name, name, dialect) if _is_checked(raw) else "''"
        if p.kind == "text":
            # Typed text is only ever a string: never quoted into a name.
            if cast == "identifier":
                raise ParamError(f"{{{name}}} is text: it cannot be an identifier")
            return _quote_literal(raw or "", dialect)
        if not raw:
            raise ParamError(f"no value selected for {{{name}}}")
        as_identifier = cast == "identifier" if cast else p.kind == "identifier"
        return _quote_identifier(raw, name, dialect) if as_identifier else _quote_literal(raw, dialect)

    return _PLACEHOLDER.sub(replace, sql)


def resolve_order(params: list[Param]) -> list[Param]:
    """Declaration order, except a param whose options_sql references another
    is resolved after it. Raises on a cycle rather than spinning."""
    by_name = {p.name: p for p in params}
    ordered: list[Param] = []
    done: set[str] = set()
    visiting: set[str] = set()

    def visit(p: Param) -> None:
        if p.name in done:
            return
        if p.name in visiting:
            raise ParamError(f"params dependency cycle at {p.name}")
        visiting.add(p.name)
        for dep in placeholders_in(p.options_sql or ""):
            if dep in by_name:
                visit(by_name[dep])
        visiting.discard(p.name)
        done.add(p.name)
        ordered.append(p)

    for p in params:
        visit(p)
    return ordered


def missing(sql: str, params: list[Param], values: dict[str, str]) -> list[str]:
    """The declared params a query still needs a value for. Dimensions and text
    never count: an unchecked one is off, and an empty text is a value."""
    by_name = {p.name: p for p in params}
    return [
        name
        for name in placeholders_in(sql)
        if name in by_name and by_name[name].kind not in ("dimension", "text") and not values.get(name)
    ]


async def resolve(params: list[Param], values: dict[str, str], run: Runner, dialect: Dialect) -> list[dict[str, Any]]:
    """Every selector's options and chosen value, in dependency order:
    `[{name, kind, options, value}]`. A value is kept only while its options
    still offer it. A param whose options_sql depends on one not chosen yet
    resolves to no options and no value — with `default: none` that is the
    normal opening state, not a failure. A text left out opens on its default."""
    resolved: list[dict[str, Any]] = []
    chosen: dict[str, str] = {}

    def settle(p: Param, options: list[str], value: str) -> None:
        chosen[p.name] = value
        resolved.append({"name": p.name, "kind": p.kind, "options": options, "value": value})

    for p in resolve_order(params):
        want = values.get(p.name)
        if p.kind == "text":
            settle(p, [], (p.text or "" if want is None else want)[:MAX_TEXT_PARAM])
            continue
        options = list(p.options or ())
        if p.options_sql:
            if missing(p.options_sql, params, chosen):
                settle(p, [], "")
                continue
            options = [option_text(v) for v in await run(substitute(p.options_sql, params, chosen, dialect))]
        if p.kind == "dimension":
            settle(p, options, want if want is not None and _is_checked(want) else "")
        elif want and want in options:
            settle(p, options, want)
        else:
            settle(p, options, options[0] if p.auto_select and options else "")
    return resolved


def apply_to_queries(
    queries: dict[str, str], params: list[Param], resolved: list[dict[str, Any]], dialect: Dialect
) -> dict[str, str]:
    """The queries with the selections substituted. A query whose selectors
    aren't all chosen yet is left out rather than run half-blank."""
    values = {p["name"]: p["value"] for p in resolved}
    return {
        name: substitute(sql, params, values, dialect)
        for name, sql in queries.items()
        if not missing(sql, params, values)
    }
