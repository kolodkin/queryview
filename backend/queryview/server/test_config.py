"""The viewer server's config file (docs/server.md): git remote, sync
interval and the connections, validated at startup."""

from __future__ import annotations

import pytest
import yaml

from queryview.server.config import DEFAULT_CONFIG_PATH, ConfigError, config_path, load_config

GIT = {"remote": "https://example.internal/dashboards.git"}


def _write(tmp_path, doc) -> object:
    path = tmp_path / "server.yaml"
    path.write_text(doc if isinstance(doc, str) else yaml.safe_dump(doc))
    return path


def _sqlite(tmp_path, name="local"):
    return {"name": name, "type": "sqlite", "path": str(tmp_path / f"{name}.sqlite")}


def test_loads_git_and_connections_with_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, {"git": GIT, "connections": [_sqlite(tmp_path)]}))
    assert (cfg.remote, cfg.branch, cfg.sync_interval) == (GIT["remote"], "main", 60)
    assert list(cfg.connections) == ["local"]
    local = cfg.connections["local"]
    assert (local.name, local.type, local.database) == ("local", "sqlite", None)
    assert local.config.path == str(tmp_path / "local.sqlite")


def test_reads_branch_interval_and_a_fixed_database(tmp_path):
    pg = {"name": "sales", "type": "postgres", "host": "db.example.internal", "port": 5432, "database": "reporting"}
    doc = {"git": {**GIT, "branch": "live", "sync_interval": 5}, "connections": [_sqlite(tmp_path), pg]}
    cfg = load_config(_write(tmp_path, doc))
    assert (cfg.branch, cfg.sync_interval) == ("live", 5)
    assert list(cfg.connections) == ["local", "sales"]  # file order
    assert cfg.connections["sales"].database == "reporting"


def test_config_path_reads_the_env_var(monkeypatch, tmp_path):
    monkeypatch.delenv("QV_CONFIG", raising=False)
    assert config_path() == DEFAULT_CONFIG_PATH
    assert str(DEFAULT_CONFIG_PATH) == "/etc/queryview/server.yaml"
    monkeypatch.setenv("QV_CONFIG", str(tmp_path / "x.yaml"))
    assert config_path() == tmp_path / "x.yaml"


def test_a_missing_file_names_the_path(tmp_path):
    with pytest.raises(ConfigError, match="nope.yaml"):
        load_config(tmp_path / "nope.yaml")


@pytest.mark.parametrize(
    "doc",
    [
        "",
        "- a",
        {"git": {}, "connections": [{"name": "x", "type": "sqlite", "path": "/x"}]},
        {"git": "r", "connections": [{"name": "x", "type": "sqlite", "path": "/x"}]},
        {"git": GIT},
        {"git": GIT, "connections": []},
        {"git": GIT, "connections": {}},
        {"git": GIT, "connections": ["x"]},
        {"git": GIT, "connections": [{"type": "sqlite", "path": "/x"}]},  # nameless
        {"git": {**GIT, "branch": 5}, "connections": [{"name": "x", "type": "sqlite", "path": "/x"}]},
    ],
)
def test_rejects_a_malformed_document(tmp_path, doc):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, doc))


@pytest.mark.parametrize("interval", [0, -5, "soon", True, None])
def test_rejects_a_bad_interval(tmp_path, interval):
    doc = {"git": {**GIT, "sync_interval": interval}, "connections": [_sqlite(tmp_path)]}
    with pytest.raises(ConfigError, match="sync_interval"):
        load_config(_write(tmp_path, doc))


def test_rejects_duplicate_names(tmp_path):
    doc = {"git": GIT, "connections": [_sqlite(tmp_path), _sqlite(tmp_path)]}
    with pytest.raises(ConfigError, match="connection 'local': duplicate name"):
        load_config(_write(tmp_path, doc))


def test_rejects_an_unknown_type(tmp_path):
    doc = {"git": GIT, "connections": [{"name": "odd", "type": "oracle"}]}
    with pytest.raises(ConfigError, match="connection 'odd': unknown connection type: oracle"):
        load_config(_write(tmp_path, doc))


def test_reports_the_drivers_own_validation(tmp_path):
    doc = {"git": GIT, "connections": [{"name": "nopath", "type": "sqlite"}]}
    with pytest.raises(ConfigError, match="connection 'nopath': path required"):
        load_config(_write(tmp_path, doc))


def test_requires_a_database_where_the_driver_has_a_picker(tmp_path):
    pg = {"name": "sales", "type": "postgres", "host": "db.example.internal", "port": 5432}
    with pytest.raises(ConfigError, match="connection 'sales': database required"):
        load_config(_write(tmp_path, {"git": GIT, "connections": [pg]}))


def test_refuses_a_duckdb_folder(tmp_path):
    doc = {"git": GIT, "connections": [{"name": "files", "type": "duckdb", "path": str(tmp_path)}]}
    with pytest.raises(ConfigError, match="connection 'files': a DuckDB folder is not allowed on the server"):
        load_config(_write(tmp_path, doc))


def test_allows_a_duckdb_file(tmp_path):
    doc = {"git": GIT, "connections": [{"name": "duck", "type": "duckdb", "path": str(tmp_path / "d.duckdb")}]}
    assert load_config(_write(tmp_path, doc)).connections["duck"].type == "duckdb"


def test_errors_never_echo_a_password(tmp_path):
    pg = {"name": "pg", "type": "postgres", "host": "h", "port": "x", "password": "s3cret-example", "database": "d"}
    with pytest.raises(ConfigError) as e:
        load_config(_write(tmp_path, {"git": GIT, "connections": [pg]}))
    assert "s3cret-example" not in str(e.value) and "connection 'pg'" in str(e.value)


def test_a_yaml_syntax_error_never_echoes_the_file(tmp_path):
    text = "git: {remote: r}\nconnections:\n  - name: pg\n    password: s3cret-example\n   bad: [\n"
    with pytest.raises(ConfigError) as e:
        load_config(_write(tmp_path, text))
    assert "s3cret-example" not in str(e.value) and "line" in str(e.value)
