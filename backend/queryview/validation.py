"""Strict validation shared by the write paths: a dashboard's `params`
(docs/dashboard.md#dashboard-parameters) and query paging."""

from __future__ import annotations

from .dashboard_params import parse_params

MAX_LIMIT = 10000


def _selector_error(entry: object, label: str) -> str | None:
    """One selector spec's option rule — exactly one of `options` /
    `options_sql` — with messages prefixed by `label` (e.g. "params[0]")."""
    if not isinstance(entry, dict):
        return f"invalid {label} must be a mapping"
    options, sql = entry.get("options"), entry.get("options_sql")
    if (options is None) == (sql is None):
        return f"invalid {label} must declare exactly one of options or options_sql"
    if sql is not None and (not isinstance(sql, str) or not sql.strip()):
        return f"invalid {label} options_sql must be a non-empty string"
    if options is not None:
        if not isinstance(options, list) or not options:
            return f"invalid {label} options must be a non-empty list"
        if any(isinstance(v, (dict, list)) or v is None for v in options):
            return f"invalid {label} options must be scalars"
    return None


DASHBOARD_PARAM_KINDS = ("value", "identifier", "dimension", "text")


def _shown(name: str) -> str:
    """A param's name as a message carries it: quoted, and cut when very long."""
    return repr(name if len(name) <= 40 else name[:40] + "…")


def _entry_error(entry: object, label: str) -> str | None:
    """One `params` entry's own rules, with messages prefixed by `label`
    (e.g. "params[0]") and, once the name is known, the name."""
    if not isinstance(entry, dict):
        return f"invalid {label} must be a mapping"
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        return f"invalid {label} name must be a non-empty string"
    label = f"{label} {_shown(name)}"
    kind = entry.get("kind", "value")
    if kind not in DASHBOARD_PARAM_KINDS:
        return f"invalid {label} kind must be one of {', '.join(DASHBOARD_PARAM_KINDS)}"
    if kind == "text":
        # Free input: an optional opening text, no list to pick from.
        if entry.get("options") is not None or entry.get("options_sql") is not None:
            return f"invalid {label} a text param takes no options"
        default = entry.get("default")
        if default is not None and not isinstance(default, str):
            return f"invalid {label} default must be a string"
        return None
    if entry.get("default") not in (None, "none"):
        return f"invalid {label} default must be 'none' when given"
    if kind == "dimension" and entry.get("options") is None and entry.get("options_sql") is None:
        return None
    return _selector_error(entry, label)


def _name_of(entry: object) -> str | None:
    name = entry.get("name") if isinstance(entry, dict) else None
    return name if isinstance(name, str) and name else None


def dashboard_params_error(raw: object) -> str | None:
    """Validate a dashboard's `params` (see docs/dashboard.md#dashboard-parameters):
    the selector rules, plus a `kind` and an optional `default: none`. A
    `dimension` is a checkbox, so it needs no options; a `text` is free input
    with an optional `default` string. None is no params."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        return "invalid params: must be a list of selector specs"
    names: set[str] = set()
    for i, entry in enumerate(raw):
        label = f"params[{i}]"
        name = _name_of(entry)
        if name is not None and name in names:
            return f"invalid {label} {_shown(name)} is declared twice"
        err = _entry_error(entry, label)
        if err:
            return err
        if name is not None:
            names.add(name)
    return None


def dashboard_params_dropped(raw: object) -> list[str]:
    """What reading leaves out of a stored `params`, one message per entry,
    worded as saving would. Reading (dashboard_params.parse_params) is more
    lenient than saving, so an entry it keeps is not reported."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        return ["invalid params: must be a list of selector specs"]
    dropped: list[str] = []
    names: set[str] = set()
    for i, entry in enumerate(raw):
        label = f"params[{i}]"
        name = _name_of(entry)
        if name is not None and name in names:
            dropped.append(f"invalid {label} {_shown(name)} is declared twice")
            continue
        if name is not None:
            names.add(name)  # as parse_params: a malformed first still takes the name
        if not parse_params([entry]):
            dropped.append(_entry_error(entry, label) or f"invalid {label} is left out")
    return dropped


# A widget page's bounds: /api/db/query's, and the viewer server's /api/query.
PAGE_DEFAULT, PAGE_MAX = 100, 1000


def _int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def page_bounds(limit: object, offset: object) -> tuple[int, int]:
    """A request's limit and offset as safe ints: 1 <= limit <= PAGE_MAX (the
    default when absent or below 1), offset >= 0."""
    lim = _int(limit, PAGE_DEFAULT)
    return (PAGE_DEFAULT if lim < 1 else min(lim, PAGE_MAX)), max(0, _int(offset, 0))
