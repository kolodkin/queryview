"""Fixtures for the viewer server's tests: a local bare repo to show."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from queryview.gitsync import dashboard_reldir, dashboard_to_files


@dataclass
class DashRepo:
    """A bare repo on `main` plus an author's clone to commit dashboards from."""

    remote: Path
    author: Path

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.author, check=True, capture_output=True)

    def commit(self, dashboards: list[dict] = (), remove: list[str] = (), raw: dict[str, str] | None = None) -> None:  # type: ignore[assignment]
        """Commit and push: `dashboards` written as their repo files,
        `remove` (names) deleted, `raw` ({path: text}) written as is."""
        for d in dashboards:
            for fname, text in dashboard_to_files(d).items():
                target = self.author / dashboard_reldir(d["name"]) / fname
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
        for name in remove:
            shutil.rmtree(self.author / dashboard_reldir(name))
        for path, text in (raw or {}).items():
            target = self.author / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self._git("add", "-A")
        self._git("commit", "-m", "update dashboards")
        self._git("push", "origin", "HEAD:main")


@pytest.fixture
def dash_repo(tmp_path, clone_base) -> DashRepo:
    remote, author = tmp_path / "remote.git", tmp_path / "author"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(author)], check=True, capture_output=True)
    repo = DashRepo(remote=remote, author=author)
    repo._git("remote", "add", "origin", str(remote))
    repo._git("config", "user.name", "author")
    repo._git("config", "user.email", "author@example.internal")
    return repo
