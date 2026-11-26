"""The viewer server's dashboards: read from the git repo at its branch head
and held in memory, refreshed by polling. Nothing is merged, committed or
pushed. See docs/system/viewer_server.md."""

from __future__ import annotations

import logging
from typing import Any

from ..gitsync import (
    GitSyncError,
    _ensure_repo,
    _git,
    _origin_head,
    _read_repo_entity,
    _repo_entities,
    forget,
)
from ..workspaces import WorkspaceRec

log = logging.getLogger("queryview.server")

# The clone's slot under the data dir. Workspace rows start at 1, so an app
# sharing the data dir never uses it.
_CLONE_ID = 0


class Repo:
    def __init__(self, remote: str, branch: str) -> None:
        self._ws = WorkspaceRec(id=_CLONE_ID, name="server", remote=remote, branch=branch)
        self._dashboards: dict[str, dict[str, Any]] = {}
        self._head: str | None = None
        self._started = False

    async def refresh(self) -> bool:
        """Fetch, and re-read the dashboards when the branch head moved: True
        when it did. A fetch failure raises GitSyncError and keeps the last
        copy. The first call clones afresh, dropping a clone an earlier run
        (perhaps of another remote) left behind."""
        if not self._started:
            forget(_CLONE_ID)
        wd = await _ensure_repo(self._ws)
        ref = await _origin_head(wd, self._ws)  # None: an empty remote
        head = (await _git("rev-parse", ref, cwd=wd)).strip() if ref else None
        if self._started and head == self._head:
            return False
        dashboards: dict[str, dict[str, Any]] = {}
        for entity in await _repo_entities(wd, head) if head else []:
            try:
                d = await _read_repo_entity(wd, head, entity["relpath"], entity["files"])  # type: ignore[arg-type]
            except GitSyncError as e:
                log.warning("skipping %s: %s", entity["relpath"], e)
                continue
            dashboards[d["name"]] = d  # a folder is one name: no two share it
        # Swapped whole, so a request never sees half a refresh.
        self._dashboards, self._head, self._started = dashboards, head, True
        log.info("showing %d dashboards at %s", len(dashboards), head or "an empty repo")
        return True

    def names(self) -> list[str]:
        return sorted(self._dashboards)

    def get(self, name: str) -> dict[str, Any] | None:
        """{name, html, queries, params}, or None."""
        return self._dashboards.get(name)
