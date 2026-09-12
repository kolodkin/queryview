"""Git sync: per-entity backup/restore of predefined queries and dashboards to
each workspace's git remote. Operations take a resolved workspaces.WorkspaceRec;
every workspace has its own clone and lock. Versions are git commits — store
makes one commit per entity, restore reads objects at a ref (git show) and
upserts the DB row; HEAD never moves. Docs: docs/gitsync.md, docs/workspace.md."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import yaml

from .workspaces import WorkspaceRec
from .yamlio import YamlIOError, dashboard_from_data, dump_yaml, query_from_data, query_to_data, slug


class GitSyncError(Exception):
    """Git-sync failure carrying an HTTP-ish status for the API layer:
    409 unconfigured, 404 entity/ref not found, 502 git or parse failure."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


# --- Serialization ---------------------------------------------------------
# The entity <-> mapping codec (and the literal-block dumper and slug) lives
# in yamlio.py, shared with YAML export/import; this section only owns the
# repo file layout: query files carry no `type` (the path does), a dashboard
# splits into meta.yaml / dashboard.html / queries.yaml.


def query_relpath(conn_type: str, name: str) -> str:
    return f"queries/{slug(conn_type)}/{slug(name)}.yaml"


def dashboard_reldir(name: str) -> str:
    return f"dashboards/{slug(name)}"


def query_to_yaml(row: dict[str, Any]) -> str:
    """One predefined-query row (as returned by list_predefined_queries) as
    YAML. cell_view stays a verbatim string; order_by/fields are stored in the
    DB as JSON text and exported as parsed YAML values. None keys are omitted."""
    return dump_yaml(query_to_data(row))


def query_from_yaml(text: str) -> dict[str, Any]:
    """Inverse of query_to_yaml, back to the DB row shape (order_by/fields as
    JSON text or None)."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise GitSyncError(f"malformed query file: {e}") from e
    try:
        return query_from_data(data)
    except YamlIOError as e:
        raise GitSyncError(str(e)) from e


def dashboard_to_files(d: dict[str, Any]) -> dict[str, str]:
    """A dashboard (as returned by get_dashboard) as its three repo files."""
    return {
        "meta.yaml": dump_yaml({"name": d["name"], "connection": d["connection"]}),
        "dashboard.html": d["html"],
        "queries.yaml": dump_yaml(d["queries"] or {}),
    }


def dashboard_from_files(files: dict[str, str]) -> dict[str, Any]:
    """Inverse of dashboard_to_files."""
    try:
        meta = yaml.safe_load(files.get("meta.yaml") or "")
        queries = yaml.safe_load(files.get("queries.yaml") or "")
    except yaml.YAMLError as e:
        raise GitSyncError(f"malformed dashboard file: {e}") from e
    data = {**(meta if isinstance(meta, dict) else {}), "html": files.get("dashboard.html", ""), "queries": queries}
    try:
        return dashboard_from_data(data, require_html=False)
    except YamlIOError as e:
        raise GitSyncError(str(e)) from e


# --- Configuration ---------------------------------------------------------
# Runtime config lives on the workspace row (GIT_SYNC_REMOTE/GIT_SYNC_BRANCH
# are read once, by the workspaces migration, to seed the default workspace).


def _require_remote(ws: WorkspaceRec) -> str:
    if not ws.remote:
        raise GitSyncError(f"workspace {ws.name!r} has no git remote configured", status=409)
    return ws.remote


def _clone_base() -> Path:
    """Where every workspace's sync clone lives, inside the data dir."""
    from .connect import _data_dir

    return _data_dir() / "gitsync"


def _workdir(ws: WorkspaceRec) -> Path:
    """This workspace's clone: {base}/{workspace id}. Keyed by id so renaming
    a workspace never orphans its clone."""
    return _clone_base() / str(ws.id)


def configured(ws: WorkspaceRec) -> bool:
    return bool(ws.remote)


# --- Git plumbing ----------------------------------------------------------

# One git operation at a time per workspace; each workdir is shared mutable
# state, but different workspaces' clones are independent, so their syncs
# don't serialize each other. The lock is per (event loop, workspace):
# asyncio.Lock binds to the loop that first acquires it, and tests run each
# operation under a fresh asyncio.run loop; production has a single loop.
_locks: dict[tuple[int, int], asyncio.Lock] = {}


def _lock(ws: WorkspaceRec) -> asyncio.Lock:
    key = (id(asyncio.get_running_loop()), ws.id)
    lock = _locks.get(key)
    if lock is None:
        lock = _locks[key] = asyncio.Lock()
    return lock


# Seconds any single git invocation may take before it is killed. Network calls
# are the slow ones; everything else finishes in milliseconds.
_GIT_TIMEOUT_S = 120

# Feeds the credential back to git per invocation, reading it from the child's
# environment so it reaches neither the repo's config nor our argv. Git calls a
# helper with "get", "store" or "erase"; answering only "get" keeps us from
# writing the credential anywhere.
_CREDENTIAL_HELPER = (
    '!f() { test "$1" = get && printf "username=%s\\npassword=%s\\n" "$QV_GIT_USERNAME" "$QV_GIT_PASSWORD"; }; f'
)


def _split_credential(url: str) -> tuple[str, tuple[str, str] | None]:
    """Separate an http(s) URL's embedded credential from the URL itself, so the
    URL can be handed to git (and persisted in the clone's config) without it.

    Only http(s) userinfo is a secret. `git@host:path` and `ssh://git@host` name
    an SSH login, not a credential, so those URLs are returned untouched."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not (parts.username or parts.password):
        return url, None
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    sanitized = urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
    return sanitized, (unquote(parts.username or ""), unquote(parts.password or ""))


async def _git(*args: str, cwd: Path | None = None, credential: tuple[str, str] | None = None) -> str:
    """Run one git command. Never interactive: stdin is closed and every prompt
    git might raise (terminal, SSH passphrase, unknown host) is turned into a
    failure, so a request can't block on input nobody is there to give. A
    credential, when passed, reaches git through the environment."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    if credential is not None:
        env["QV_GIT_USERNAME"], env["QV_GIT_PASSWORD"] = credential
        # The empty value first clears helpers inherited from system/global
        # config, so ours is the only one asked.
        args = ("-c", "credential.helper=", "-c", f"credential.helper={_CREDENTIAL_HELPER}", *args)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        # No `git` on PATH: a deployment problem, not a repo problem — say so
        # instead of surfacing a bare FileNotFoundError as a 500.
        raise GitSyncError("git is not installed on the server") from e
    verb = args[0] if credential is None else args[4]
    try:
        out, err = await asyncio.wait_for(proc.communicate(), _GIT_TIMEOUT_S)
    except TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise GitSyncError(f"git {verb} timed out after {_GIT_TIMEOUT_S}s") from e
    if proc.returncode != 0:
        tail = err.decode("utf-8", "replace").strip()[-500:]
        raise GitSyncError(f"git {verb} failed: {tail}")
    return out.decode("utf-8", "replace")


async def _ensure_repo(ws: WorkspaceRec) -> Path:
    """The workspace's sync clone, cloning (or, for an empty remote, init +
    remote add) on first use. Idempotent."""
    remote, branch, wd = _require_remote(ws), ws.branch, _workdir(ws)
    if (wd / ".git").exists():
        return wd
    wd.parent.mkdir(parents=True, exist_ok=True)
    # The clone records its remote in .git/config, so only the credential-free
    # URL goes to git as an argument; the credential travels out of band.
    remote, cred = _split_credential(remote)
    try:
        await _git("clone", "--branch", branch, remote, str(wd), credential=cred)
    except GitSyncError as clone_err:
        # Clone can fail either because the branch genuinely doesn't exist yet
        # on an empty remote (the only case we should paper over with a local
        # init) or because the remote itself is unreachable/misconfigured. Ask
        # the remote directly to tell the two apart.
        try:
            heads = await _git("ls-remote", "--heads", remote, branch, credential=cred)
        except GitSyncError as probe_err:
            raise GitSyncError(f"git remote unreachable: {probe_err}") from probe_err
        if heads.strip():
            raise clone_err
        # Empty remote (branch doesn't exist yet): start locally, attach remote.
        if wd.exists():
            shutil.rmtree(wd)  # clean up any partial clone before init
        await _git("init", "-b", branch, str(wd))
        await _git("remote", "add", "origin", remote, cwd=wd)
    await _git("config", "user.name", "queryview", cwd=wd)
    await _git("config", "user.email", "queryview@localhost", cwd=wd)
    return wd


async def _origin_head(wd: Path, ws: WorkspaceRec) -> str | None:
    """Fetch, then the remote branch ref if it exists (None on an empty remote).
    Network/auth failures raise."""
    await _git("fetch", "origin", cwd=wd, credential=_split_credential(_require_remote(ws))[1])
    ref = f"origin/{ws.branch}"
    try:
        await _git("rev-parse", "--verify", ref, cwd=wd)
    except GitSyncError:
        return None
    return ref


# --- Entities --------------------------------------------------------------


def _check_kind(kind: str, conn_type: str | None) -> None:
    """Validate kind/conn_type here so every caller (REST, MCP, future ones)
    inherits it instead of each layer re-implementing the check."""
    if kind not in ("query", "dashboard"):
        raise GitSyncError(f"unknown kind {kind!r} (expected 'query' or 'dashboard')", status=400)
    if kind == "query" and not conn_type:
        raise GitSyncError("conn_type is required for queries", status=400)


def entity_relpath(kind: str, name: str, conn_type: str | None) -> str:
    return query_relpath(conn_type or "", name) if kind == "query" else dashboard_reldir(name)


async def _load_entity(ws: WorkspaceRec, kind: str, name: str, conn_type: str | None) -> dict[str, Any]:
    if kind == "query":
        from .queries import get_predefined_query

        row = await get_predefined_query(conn_type or "", name, ws.id)
        if row is None:
            raise GitSyncError(f"query {name!r} not found", status=404)
        return row
    from .dashboards import get_dashboard

    d = await get_dashboard(name, ws.id)
    if d is None:
        raise GitSyncError(f"dashboard {name!r} not found", status=404)
    return d


# --- Operations ------------------------------------------------------------


async def store(
    ws: WorkspaceRec,
    kind: str,
    name: str,
    conn_type: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """Export one entity's saved DB state into the clone, commit, push.
    The workdir is reset to the remote head first — exports are deterministic
    from the DB and each commit touches one entity, so this is always safe and
    avoids push rejections."""
    _check_kind(kind, conn_type)
    _require_remote(ws)  # unconfigured -> 409 before any DB/entity lookup
    entity = await _load_entity(ws, kind, name, conn_type)
    async with _lock(ws):
        wd = await _ensure_repo(ws)
        head = await _origin_head(wd, ws)
        if head:
            await _git("reset", "--hard", head, cwd=wd)
        relpath = entity_relpath(kind, name, conn_type)
        if kind == "query":
            path = wd / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(query_to_yaml(entity), encoding="utf-8")
        else:
            ddir = wd / relpath
            if ddir.exists():
                shutil.rmtree(ddir)
            ddir.mkdir(parents=True, exist_ok=True)
            for fname, content in dashboard_to_files(entity).items():
                (ddir / fname).write_text(content, encoding="utf-8")
        await _git("add", "-A", "--", relpath, cwd=wd)
        if not (await _git("status", "--porcelain", "--", relpath, cwd=wd)).strip():
            return {"committed": False, "sha": None, "message": "no changes"}
        label = f"{conn_type}/{name}" if kind == "query" else name
        await _git("commit", "-m", message or f"store {kind} {label}", cwd=wd)
        await _git("push", "origin", ws.branch, cwd=wd, credential=_split_credential(_require_remote(ws))[1])
        sha = (await _git("rev-parse", "HEAD", cwd=wd)).strip()
        return {"committed": True, "sha": sha, "message": "stored"}


async def history(
    ws: WorkspaceRec,
    kind: str,
    name: str,
    conn_type: str | None = None,
    before: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Commits touching the entity's path, newest first. `before=<sha>` pages
    strictly older commits. Reads objects only — never touches the working tree."""
    _check_kind(kind, conn_type)
    _require_remote(ws)
    relpath = entity_relpath(kind, name, conn_type)
    async with _lock(ws):
        wd = await _ensure_repo(ws)
        head = await _origin_head(wd, ws)
        if head is None:
            return {"revisions": [], "has_more": False}
        start = head
        if before:
            try:
                await _git("rev-parse", "--verify", "--quiet", f"{before}^{{commit}}", cwd=wd)
            except GitSyncError as e:
                raise GitSyncError(f"unknown revision {before!r}", status=404) from e
            try:
                await _git("rev-parse", "--verify", "--quiet", f"{before}^", cwd=wd)
            except GitSyncError:
                # `before` is the oldest commit: <sha>^ doesn't resolve.
                return {"revisions": [], "has_more": False}
            start = f"{before}^"
        out = await _git(
            "log",
            f"--max-count={limit + 1}",
            "--format=%H%x1f%ct%x1f%s",
            start,
            "--",
            relpath,
            cwd=wd,
        )
    revisions = []
    for line in out.splitlines():
        sha, ct, subject = line.split("\x1f", 2)
        revisions.append({"sha": sha, "date": int(ct) * 1000, "message": subject})
    return {"revisions": revisions[:limit], "has_more": len(revisions) > limit}


async def restore(
    ws: WorkspaceRec,
    kind: str,
    name: str,
    conn_type: str | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    """Overwrite the local DB row with the entity's content at `ref` (default:
    the remote branch head). Reads via `git show` — HEAD never moves, history
    is never rewritten. Parses fully before writing, so the DB row is either
    untouched or fully replaced."""
    _check_kind(kind, conn_type)
    _require_remote(ws)
    relpath = entity_relpath(kind, name, conn_type)
    async with _lock(ws):
        wd = await _ensure_repo(ws)
        head = await _origin_head(wd, ws)
        resolved = ref if ref and ref != "HEAD" else head
        if resolved is None:
            raise GitSyncError(f"{kind} {name!r} not found in git", status=404)

        async def _show(path: str) -> str:
            return await _git("show", f"{resolved}:{path}", cwd=wd)

        if kind == "query":
            try:
                text = await _show(relpath)
            except GitSyncError:
                raise GitSyncError(f"query {name!r} not found at {resolved}", status=404) from None
            data = query_from_yaml(text)
        else:
            files: dict[str, str] = {}
            for fname in ("meta.yaml", "dashboard.html", "queries.yaml"):
                try:
                    files[fname] = await _show(f"{relpath}/{fname}")
                except GitSyncError:
                    if fname == "meta.yaml":
                        raise GitSyncError(f"dashboard {name!r} not found at {resolved}", status=404) from None
            data = dashboard_from_files(files)

    # DB upsert happens outside the git lock — it doesn't touch the workdir.
    if kind == "query":
        from .queries import save_predefined_query

        await save_predefined_query(
            data["query_name"],
            conn_type or "",
            data["query"],
            data["cell_view"],
            data["order_by"],
            data["fields"],
            workspace_id=ws.id,
        )
    else:
        from .dashboards import upsert_dashboard

        await upsert_dashboard(
            data["name"],
            data["connection"],
            data["html"],
            data["queries"],
            workspace_id=ws.id,
        )
    return {"restored": True, "sha": resolved}
