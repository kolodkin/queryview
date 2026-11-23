"""The entry point (`queryview`, `python -m queryview`): its arguments pick
the port and which app factory uvicorn imports."""

from __future__ import annotations

import pytest
import uvicorn

from queryview import serving
from queryview.__main__ import run


@pytest.fixture
def started(monkeypatch):
    """What uvicorn was asked to run, instead of running it."""
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(uvicorn, "run", lambda target, **kwargs: calls.append((target, kwargs)))
    monkeypatch.delenv("PORT", raising=False)
    return calls


def test_runs_the_full_app_by_default(started):
    run([])
    assert started == [
        ("queryview.app:create_app", {"factory": True, "host": "0.0.0.0", "port": 8000, "reload": False})
    ]


def test_api_only_reload_and_port(started):
    run(["--api-only", "--reload", "--port", "9000"])
    assert started == [
        ("queryview.app:create_api_app", {"factory": True, "host": "0.0.0.0", "port": 9000, "reload": True})
    ]


@pytest.mark.parametrize("argv", [["--nope"], ["--port", "x"], ["extra"]])
def test_a_bad_argument_is_a_usage_error(argv, started):
    with pytest.raises(SystemExit) as e:
        run(argv)
    assert e.value.code == 2 and started == []


def test_port_flag_beats_env(monkeypatch):
    monkeypatch.setenv("PORT", "7777")
    assert serving.resolve_port(["--port", "9000"]) == 9000


def test_port_env_used_without_flag(monkeypatch, started):
    monkeypatch.setenv("PORT", "7777")
    assert serving.resolve_port([]) == 7777
    run([])
    assert started[0][1]["port"] == 7777


def test_port_defaults_to_8000(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert serving.resolve_port([]) == 8000


def test_host_is_an_argument(started):
    # The app has no login: the dev scripts pass 127.0.0.1 so a developer's
    # machine does not serve it to the network.
    run(["--host", "127.0.0.1"])
    assert started[0][1]["host"] == "127.0.0.1"
