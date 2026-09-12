"""Where QueryView's state lives.

One data directory holds the SQLite store, the password-encryption key and the
git-sync clones. `DATA_DIR` moves it; the names inside are fixed. The default,
`~/.queryview`, is also the image's mount point, so a local run and a container
share state.

It used to be package-relative (`Path(__file__).parent.parent`), which meant
`backend/queryview.db` in a checkout but `<site-packages>/queryview.db` once the
wheel shipped — under `uvx`, inside uv's *cache*, where a `uv cache clean` or a
version bump silently takes the DB with it.
"""

from __future__ import annotations

from pathlib import Path

import queryview
from queryview.connect import _data_dir, _db_path, _key_path
from queryview.gitsync import _clone_base


def test_data_dir_defaults_to_a_dotdir_in_home(monkeypatch):
    """One path on every OS, matching the image's mount point."""
    monkeypatch.delenv("DATA_DIR", raising=False)
    assert _data_dir() == Path.home() / ".queryview"


def test_data_dir_is_not_inside_the_installed_package(monkeypatch):
    """The regression: a package-relative default puts user data in
    site-packages (and under uvx, in a disposable cache directory)."""
    monkeypatch.delenv("DATA_DIR", raising=False)
    package_root = Path(queryview.__file__).resolve().parent.parent
    assert package_root not in _data_dir().resolve().parents


def test_every_path_hangs_off_the_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert _db_path() == tmp_path / "db.sqlite"
    assert _key_path() == tmp_path / "encryption.key"
    assert _clone_base() == tmp_path / "gitsync"


def test_ensure_schema_creates_a_missing_data_dir(monkeypatch, tmp_path):
    """The data dir does not exist on a fresh install, so startup has to create
    it — SQLite will not create a missing parent directory."""
    import asyncio

    import queryview.connect as c

    target = tmp_path / "fresh" / "nested"
    monkeypatch.setenv("DATA_DIR", str(target))
    monkeypatch.setattr(c, "_engine", None)
    monkeypatch.setattr(c, "_schema_ready", False)
    assert not target.exists()

    asyncio.run(c._ensure_schema())

    assert target.is_dir()
    assert (target / "db.sqlite").exists()
