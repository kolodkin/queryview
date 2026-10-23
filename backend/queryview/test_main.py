"""Tests for the console-script entry point (port resolution)."""

from queryview import main


def test_port_flag_beats_env(monkeypatch):
    monkeypatch.setenv("PORT", "7777")
    assert main._resolve_port(["--port", "9000"]) == 9000


def test_port_env_used_without_flag(monkeypatch):
    monkeypatch.setenv("PORT", "7777")
    assert main._resolve_port([]) == 7777


def test_port_defaults_to_8000(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert main._resolve_port([]) == 8000
