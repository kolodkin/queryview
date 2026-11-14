"""YAML export/import of dashboards — one at a time or a whole workspace as a
single bundle. Every exported document is self-describing via a top-level
`kind` (dashboard | workspace), so
import dispatches on file content, never on the filename. Import validates the
whole document before writing anything, then upserts (same overwrite semantics
as gitsync restore). This module also owns the entity <-> plain-mapping codec
and the YAML dumper that gitsync's per-entity repo files build on.
Docs: docs/export-import.md."""

from __future__ import annotations

from typing import Any

import yaml

from .validation import dashboard_params_error
from .workspaces import WorkspaceRec


class YamlIOError(Exception):
    """Export/import failure carrying an HTTP-ish status for the API layer:
    400 malformed document, 404 entity not found."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# --- Dumper (also used by gitsync's per-entity files) -----------------------


def _repr_str(dumper: yaml.SafeDumper, data: str):
    # Multiline strings (SQL, HTML) as literal blocks for readable
    # files and diffs.
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(str, _repr_str)


def dump_yaml(data: Any) -> str:
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True)


_SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._ -")


def slug(name: str) -> str:
    """Filesystem-safe name: percent-encode (UTF-8) anything outside
    [A-Za-z0-9._ -] plus a leading dot. Used for export download filenames and
    gitsync repo paths; the canonical name lives inside the YAML — readers
    trust the file content, never the path."""
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch in _SAFE and not (ch == "." and i == 0):
            out.append(ch)
        else:
            out.append("".join(f"%{b:02X}" for b in ch.encode("utf-8")))
    return "".join(out)


# --- Entity <-> mapping codec (shared with gitsync) -------------------------


def _require_str(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise YamlIOError(f"malformed {where}: {key} must be a non-empty string")
    return value


def dashboard_to_data(d: dict[str, Any]) -> dict[str, Any]:
    """One dashboard (get_dashboard shape) as its exported mapping. Keys are
    listed explicitly to pin the document format independently of what the
    store accessors happen to return."""
    return {
        "name": d["name"],
        "html": d["html"],
        "queries": d["queries"] or {},
        # Only when declared, so a params-free dashboard exports as before.
        **({"params": d["params"]} if d.get("params") else {}),
    }


def dashboard_from_data(data: Any, where: str = "dashboard file", require_html: bool = True) -> dict[str, Any]:
    """Validate a dashboard mapping back to the upsert_dashboard shape.
    gitsync passes require_html=False: its repo format stores the HTML as a
    separate file that may legitimately be empty."""
    if not isinstance(data, dict):
        raise YamlIOError(f"malformed {where}: expected a mapping")
    name = _require_str(data, "name", where)
    # A `connection` key (older documents) is ignored: a dashboard runs on the
    # viewing session's connection.
    html = _require_str(data, "html", where) if require_html else str(data.get("html") or "")
    queries = data.get("queries") or {}
    if not isinstance(queries, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in queries.items()):
        raise YamlIOError(f"malformed {where}: queries must be a {{name: SQL}} map")
    params = data.get("params") or []
    perr = dashboard_params_error(params)
    if perr is not None:
        raise YamlIOError(f"malformed {where}: {perr}")
    return {"name": name, "html": html, "queries": queries, "params": params}


# --- Import documents -------------------------------------------------------


# Saved queries were removed; refuse their documents rather than drop them silently.
_NO_QUERIES = "saved queries are no longer supported"


def parse_document(text: str) -> tuple[str, Any]:
    """Parse + validate an import document. Returns (kind, payload): for
    kind 'dashboard' the payload is one parsed entry; for 'workspace' a
    {'dashboards': [...]} list of parsed entries."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise YamlIOError(f"malformed YAML: {e}") from e
    if not isinstance(data, dict):
        raise YamlIOError("malformed document: expected a YAML mapping")
    kind = data.get("kind")
    if kind == "query":
        raise YamlIOError(_NO_QUERIES)
    if kind == "dashboard":
        return "dashboard", dashboard_from_data(data, "dashboard document")
    if kind == "workspace":
        if data.get("queries"):
            raise YamlIOError(f"{_NO_QUERIES}: remove `queries` from the workspace document")
        raw_dashboards = data.get("dashboards") or []
        if not isinstance(raw_dashboards, list):
            raise YamlIOError("malformed workspace document: dashboards must be a list")
        return "workspace", {
            "dashboards": [dashboard_from_data(d, f"workspace dashboards[{i}]") for i, d in enumerate(raw_dashboards)],
        }
    raise YamlIOError("malformed document: kind must be 'dashboard' or 'workspace'")


# --- Services ---------------------------------------------------------------


async def export(kind: str, name: str, ws: WorkspaceRec) -> tuple[str, str]:
    """Export dispatch shared by every caller (REST today, MCP/CLI tomorrow):
    validates kind/name, loads the document, and owns the `{slug}.{kind}.yaml`
    download-filename convention. Returns (filename, text)."""
    if kind == "query":
        raise YamlIOError(_NO_QUERIES)
    if kind not in ("dashboard", "workspace") or (kind == "dashboard" and not name):
        raise YamlIOError("kind ('dashboard'|'workspace') and (for a dashboard) name are required")
    if kind == "dashboard":
        return f"{slug(name)}.dashboard.yaml", await export_dashboard(name, ws.id)
    return f"{slug(ws.name)}.workspace.yaml", await export_workspace(ws.id)


async def export_dashboard(name: str, workspace_id: int) -> str:
    from .dashboards import get_dashboard

    d = await get_dashboard(name, workspace_id)
    if d is None:
        raise YamlIOError(f"dashboard {name!r} not found", status=404)
    return dump_yaml({"kind": "dashboard", **dashboard_to_data(d)})


async def export_workspace(workspace_id: int) -> str:
    """The whole workspace (every dashboard) as one bundle. Empty workspaces
    export a valid, importable empty bundle."""
    from .dashboards import list_dashboards_full

    dashboards = await list_dashboards_full(workspace_id)
    return dump_yaml({"kind": "workspace", "dashboards": [dashboard_to_data(d) for d in dashboards]})


async def import_text(text: str, workspace_id: int) -> dict[str, Any]:
    """Import a document into a workspace, upserting by name. The whole
    document is validated before the first write, so a malformed file changes
    nothing; the dashboards then write in a single transaction. Returns
    {'kind', 'dashboards'}, the latter a count."""
    from .dashboards import upsert_dashboards

    kind, payload = parse_document(text)
    dashboards = payload["dashboards"] if kind == "workspace" else [payload]
    if dashboards:
        await upsert_dashboards(dashboards, workspace_id=workspace_id)
    return {"kind": kind, "dashboards": len(dashboards)}
