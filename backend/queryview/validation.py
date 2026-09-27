"""Strict validation for the presentation fields carried on a push, a
predefined-query save, or a YAML import/restore: order_by/fields (structured)
and cell_view (raw YAML text, checked against the contract in
docs/query.md#cell-views). Shared by every write path so they all enforce the
same rules; reads stay lenient (the client drops entries it can't use)."""

from __future__ import annotations

import yaml

MAX_LIMIT = 10000


def presentation_error(order_by: object, fields: object) -> str | None:
    """Return an error message if order_by/fields are malformed, else None.
    None inputs are valid (the field is simply absent/unchanged)."""
    if order_by is not None:
        if not isinstance(order_by, list):
            return "invalid order_by: must be a list"
        for col in order_by:
            if not isinstance(col, dict):
                return "invalid order_by: each entry must be an object"
            name = col.get("name")
            if not isinstance(name, str) or not name:
                return "invalid order_by: name must be a non-empty string"
            if "`" in name:
                return "invalid order_by: name must not contain a backtick"
            direction = col.get("dir")
            if not isinstance(direction, str) or direction.upper() not in ("ASC", "DESC"):
                return "invalid order_by: dir must be ASC or DESC"
    if fields is not None:
        if not isinstance(fields, list):
            return "invalid fields: must be a list"
        for f in fields:
            if not isinstance(f, str) or not f:
                return "invalid fields: each column must be a non-empty string"
    return None


def _selector_error(entry: object, label: str) -> str | None:
    """One selector spec's shared rules — a name and exactly one of `options` /
    `options_sql` — with messages prefixed by `label` (e.g. "cell_view: params[0]")."""
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


def _cell_view_params_error(raw: object) -> str | None:
    """Validate the reserved `params:` selector list (see docs/query.md)."""
    if not isinstance(raw, list):
        return "invalid cell_view: params must be a list of selector specs"
    for i, entry in enumerate(raw):
        err = _selector_error(entry, f"cell_view: params[{i}]")
        if err:
            return err
    return None


DASHBOARD_PARAM_KINDS = ("value", "identifier", "dimension")


def dashboard_params_error(raw: object) -> str | None:
    """Validate a dashboard's `params` (see docs/dashboard.md#dashboard-parameters):
    the query selector rules, plus a `kind` and an optional `default: none`. A
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


def cell_view_error(cell_view: object) -> str | None:
    """Return an error message if a cell_view YAML text is malformed, else None.
    None / empty text is valid (no custom views). The contract
    (docs/query.md#cell-views): a YAML mapping whose reserved `params` key holds
    selector specs and whose other entries are column -> {type: link|custom,
    value: str} (extra keys are allowed)."""
    if cell_view is None:
        return None
    if not isinstance(cell_view, str):
        return "invalid cell_view: must be YAML text"
    if not cell_view.strip():
        return None
    try:
        doc = yaml.safe_load(cell_view)
    except yaml.YAMLError as e:
        return f"invalid cell_view: not valid YAML ({e})"
    if doc is None:
        return None
    if not isinstance(doc, dict):
        return "invalid cell_view: must be a YAML mapping of column -> {type, value}"
    for key, entry in doc.items():
        if not isinstance(key, str) or not key:
            return "invalid cell_view: column names must be non-empty strings"
        if key == "params":
            perr = _cell_view_params_error(entry)
            if perr is not None:
                return perr
            continue
        if not isinstance(entry, dict):
            return f"invalid cell_view: entry {key!r} must be a {{type, value}} mapping"
        if entry.get("type") not in ("link", "custom"):
            return f"invalid cell_view: entry {key!r} type must be 'link' or 'custom'"
        value = entry.get("value")
        if not isinstance(value, str) or not value:
            return f"invalid cell_view: entry {key!r} value must be a non-empty string"
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
