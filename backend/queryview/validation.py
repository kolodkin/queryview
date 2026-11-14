"""Strict validation shared by the write paths: a dashboard's `params`
(docs/dashboard.md#dashboard-parameters) and query paging."""

from __future__ import annotations

MAX_LIMIT = 10000


def _selector_error(entry: object, label: str) -> str | None:
    """One selector spec's shared rules — a name and exactly one of `options` /
    `options_sql` — with messages prefixed by `label` (e.g. "params[0]")."""
    if not isinstance(entry, dict):
        return f"invalid {label} must be a mapping"
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        return f"invalid {label} name must be a non-empty string"
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


DASHBOARD_PARAM_KINDS = ("value", "identifier", "dimension")


def dashboard_params_error(raw: object) -> str | None:
    """Validate a dashboard's `params` (see docs/dashboard.md#dashboard-parameters):
    the selector rules, plus a `kind` and an optional `default: none`. A
    `dimension` is a checkbox, so it needs no options. None is no params."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        return "invalid params: must be a list of selector specs"
    for i, entry in enumerate(raw):
        label = f"params[{i}]"
        if not isinstance(entry, dict):
            return f"invalid {label} must be a mapping"
        kind = entry.get("kind", "value")
        if kind not in DASHBOARD_PARAM_KINDS:
            return f"invalid {label} kind must be one of {', '.join(DASHBOARD_PARAM_KINDS)}"
        if entry.get("default") not in (None, "none"):
            return f"invalid {label} default must be 'none' when given"
        if kind == "dimension" and entry.get("options") is None and entry.get("options_sql") is None:
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                return f"invalid {label} name must be a non-empty string"
            continue
        err = _selector_error(entry, label)
        if err:
            return err
    return None


def clamp_paging(limit: object, offset: object) -> tuple[int, int]:
    """Coerce/clamp limit & offset to safe ints: 0 <= limit <= MAX_LIMIT, offset >= 0."""
    try:
        lim = int(limit)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        lim = 100
    try:
        off = int(offset)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        off = 0
    return max(0, min(lim, MAX_LIMIT)), max(0, off)
