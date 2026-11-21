"""The viewer server's config: one YAML file naming the git repo to show and
the connections to show it on. See docs/server.md.

Every fault raises ConfigError with a message safe to print: it names the
path or the connection, never a field's value."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..connect import parse_driver_config
from ..drivers import DRIVERS
from ..drivers.base import DriverConfig
from ..drivers.duckdb import _is_folder

DEFAULT_CONFIG_PATH = Path("/etc/queryview/server.yaml")
DEFAULT_SYNC_INTERVAL = 60  # seconds between fetches


class ConfigError(Exception):
    """The config file cannot be used; the message is shown at startup."""


@dataclass(frozen=True)
class Connection:
    name: str
    type: str
    config: DriverConfig
    # The one database this connection runs on; None where the driver has no picker.
    database: str | None


@dataclass(frozen=True)
class ServerConfig:
    remote: str
    branch: str
    sync_interval: float
    connections: dict[str, Connection]  # by name, in file order


def config_path() -> Path:
    env = os.environ.get("QV_CONFIG")
    return Path(env) if env else DEFAULT_CONFIG_PATH


def _connection(entry: object, position: int) -> Connection:
    if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"].strip():
        raise ConfigError(f"connection #{position}: name required")
    name = entry["name"].strip()

    def fault(message: str) -> ConfigError:
        return ConfigError(f"connection {name!r}: {message}")

    conn_type, config, error = parse_driver_config(entry)
    if error or config is None:
        raise fault(error or "invalid config")
    if conn_type == "duckdb" and _is_folder(config.path):  # type: ignore[union-attr]
        # A folder connection's SQL can read any local file, this config included.
        raise fault("a DuckDB folder is not allowed on the server")
    raw = entry.get("database")
    database = raw.strip() if isinstance(raw, str) and raw.strip() else None
    if DRIVERS[conn_type].requires_database and database is None:
        raise fault("database required")
    return Connection(name=name, type=conn_type, config=config, database=database)


def _git(doc: dict[str, Any]) -> tuple[str, str, float]:
    git = doc.get("git")
    if not isinstance(git, dict):
        raise ConfigError("git: a mapping with `remote` is required")
    remote, branch, interval = (
        git.get("remote"),
        git.get("branch", "main"),
        git.get("sync_interval", DEFAULT_SYNC_INTERVAL),
    )
    if not isinstance(remote, str) or not remote.strip():
        raise ConfigError("git.remote is required")
    if not isinstance(branch, str) or not branch.strip():
        raise ConfigError("git.branch must be a branch name")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
        raise ConfigError("git.sync_interval must be a number of seconds above 0")
    return remote.strip(), branch.strip(), interval


def load_config(path: Path) -> ServerConfig:
    try:
        text = Path(path).read_text()
    except OSError as e:
        raise ConfigError(f"cannot read config {path}: {e.strerror or e}") from e
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as e:
        # The error's own text quotes the file around the fault: report only where.
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark is not None else ""
        raise ConfigError(f"config {path} is not valid YAML{where}") from None
    if not isinstance(doc, dict):
        raise ConfigError(f"config {path} must be a mapping with `git` and `connections`")
    remote, branch, interval = _git(doc)
    entries = doc.get("connections")
    if not isinstance(entries, list) or not entries:
        raise ConfigError("connections: at least one is required")
    connections: dict[str, Connection] = {}
    for i, entry in enumerate(entries, start=1):
        conn = _connection(entry, i)
        if conn.name in connections:
            raise ConfigError(f"connection {conn.name!r}: duplicate name")
        connections[conn.name] = conn
    return ServerConfig(remote=remote, branch=branch, sync_interval=interval, connections=connections)
