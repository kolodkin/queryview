"""Git sync: per-entity backup/restore of predefined queries and dashboards to
each workspace's git remote. Operations take a resolved workspaces.WorkspaceRec;
every workspace has its own clone and lock. Versions are git commits — store
makes one commit per entity, restore reads objects at a ref (git show) and
upserts the DB row; HEAD never moves. Docs: docs/gitsync.md, docs/workspace.md."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import yaml

from .connect import _data_dir
from .workspaces import WorkspaceRec, split_credential
from .yamlio import YamlIOError, dashboard_from_data, dump_yaml, query_from_data, query_to_data, slug


class GitSyncError(Exception):
    """Git-sync failure carrying an HTTP-ish status for the API layer:
    409 unconfigured, 404 entity/ref not found, 502 git or parse failure."""

    def __init__(self, message: str, status: int = 502, rejected: bool = False):
        super().__init__(message)
        self.status = status
        self.rejected = rejected  # push refused because the remote moved under us


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


# Order matters: sync state records the oids joined in this order as "agreed".
DASHBOARD_FILES = ("meta.yaml", "dashboard.html", "queries.yaml")


def dashboard_to_files(d: dict[str, Any]) -> dict[str, str]:
    """A dashboard (as returned by get_dashboard) as its three repo files."""
    return {
        # params only when declared, keeping params-free dashboards' meta.yaml as is.
        "meta.yaml": dump_yaml({"name": d["name"], **({"params": d["params"]} if d.get("params") else {})}),
        "dashboard.html": d["html"],
        "queries.yaml": dump_yaml(d["queries"] or {}),
    }


def dashboard_from_files(files: dict[str, str]) -> dict[str, Any]:
    """Inverse of dashboard_to_files."""
    try:
        meta = yaml.safe_load(files["meta.yaml"])
        queries = yaml.safe_load(files["queries.yaml"])
    except yaml.YAMLError as e:
        raise GitSyncError(f"malformed dashboard file: {e}") from e
    data = {**(meta if isinstance(meta, dict) else {}), "html": files["dashboard.html"], "queries": queries}
    try:
        return dashboard_from_data(data, require_html=False)
    except YamlIOError as e:
        raise GitSyncError(str(e)) from e


# --- Configuration ---------------------------------------------------------
# All config lives on the workspace row; there is no environment fallback.


def _require_remote(ws: WorkspaceRec) -> str:
    if not ws.remote:
        raise GitSyncError(f"workspace {ws.name!r} has no git remote configured", status=409)
    return ws.remote


def _clone_base() -> Path:
    """Where every workspace's sync clone lives, inside the data dir."""
    return _data_dir() / "gitsync"


def _workdir(ws: WorkspaceRec) -> Path:
    """This workspace's clone: {base}/{workspace id}. Keyed by id so renaming
    a workspace never orphans its clone."""
    return _clone_base() / str(ws.id)


def configured(ws: WorkspaceRec) -> bool:
    return bool(ws.remote)


def forget(workspace_id: int) -> None:
    """Drop a workspace's clone and sync state — its remote or branch changed
    (or it is gone), so both describe a repo it no longer syncs with."""
    shutil.rmtree(_clone_base() / str(workspace_id), ignore_errors=True)
    (_clone_base() / f"{workspace_id}.sync.json").unlink(missing_ok=True)


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


# Seconds before a git invocation is killed; only network calls come close.
_GIT_TIMEOUT_S = 120

# Feeds the credential back per invocation from the child's environment, so it
# reaches neither the repo's config nor our argv. Git calls a helper with "get",
# "store" or "erase"; answering only "get" avoids writing it anywhere.
_CREDENTIAL_HELPER = (
    '!f() { test "$1" = get && printf "username=%s\\npassword=%s\\n" "$QV_GIT_USERNAME" "$QV_GIT_PASSWORD"; }; f'
)


def _credential(ws: WorkspaceRec) -> tuple[str, str] | None:
    """This workspace's git credential, if its remote embeds one."""
    return split_credential(_require_remote(ws))[1]


async def _git(*args: str, cwd: Path | None = None, credential: tuple[str, str] | None = None) -> str:
    """Run one git command, never interactively: stdin is closed and any prompt
    (terminal, SSH passphrase, unknown host) becomes a failure rather than a
    blocked request. A credential, when passed, arrives via the environment."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_SSH_COMMAND"] = f"{os.environ.get('GIT_SSH_COMMAND', 'ssh')} -o BatchMode=yes"
    if credential is not None:
        env["QV_GIT_USERNAME"], env["QV_GIT_PASSWORD"] = credential
        # Config through the environment, not `-c` flags, so argv stays exactly
        # what the caller passed. The empty first value clears any helper
        # inherited from system/global config, leaving ours the only one asked.
        env["GIT_CONFIG_COUNT"] = "2"
        env["GIT_CONFIG_KEY_0"], env["GIT_CONFIG_VALUE_0"] = "credential.helper", ""
        env["GIT_CONFIG_KEY_1"], env["GIT_CONFIG_VALUE_1"] = "credential.helper", _CREDENTIAL_HELPER
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
    try:
        out, err = await asyncio.wait_for(proc.communicate(), _GIT_TIMEOUT_S)
    except TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise GitSyncError(f"git {args[0]} timed out after {_GIT_TIMEOUT_S}s") from e
    if proc.returncode != 0:
        tail = err.decode("utf-8", "replace").strip()[-500:]
        # Lost a race with another push: "[rejected]" (behind), or a server-side ref-lock race.
        rejected = args[0] == "push" and (b"! [rejected]" in err or b"cannot lock ref" in err)
        raise GitSyncError(f"git {args[0]} failed: {tail}", rejected=rejected)
    return out.decode("utf-8", "replace")


async def _ensure_repo(ws: WorkspaceRec) -> Path:
    """The workspace's sync clone, cloning (or, for an empty remote, init +
    remote add) on first use. Idempotent."""
    branch, wd = ws.branch, _workdir(ws)
    if (wd / ".git").exists():
        return wd
    wd.parent.mkdir(parents=True, exist_ok=True)
    # The clone records its remote in .git/config, so only the credential-free
    # URL goes to git as an argument; the credential travels out of band.
    remote, cred = split_credential(_require_remote(ws))
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
    await _git("fetch", "origin", cwd=wd, credential=_credential(ws))
    ref = f"origin/{ws.branch}"
    try:
        await _git("rev-parse", "--verify", ref, cwd=wd)
    except GitSyncError:
        return None
    return ref


async def _resolve_ref(wd: Path, ref: str) -> str:
    """A user-supplied ref for `git show`. A branch name is read as the
    fetched `origin/<name>`: the local branch only moves on store, so it can
    be behind. Shas and anything else pass through unchanged."""
    try:
        await _git("rev-parse", "--verify", "--quiet", f"origin/{ref}^{{commit}}", cwd=wd)
    except GitSyncError:
        return ref
    return f"origin/{ref}"


# --- Entities --------------------------------------------------------------


def _check_kind(kind: str, conn_type: str | None) -> None:
    """Validate kind/conn_type here so every caller (REST, MCP, future ones)
    inherits it instead of each layer re-implementing the check."""
    if kind not in ("query", "dashboard"):
        raise GitSyncError(f"unknown kind {kind!r} (expected 'query' or 'dashboard')", status=400)
    if kind == "query" and not conn_type:
        raise GitSyncError("conn_type is required for queries", status=400)


def _entity_paths(kind: str, name: str, conn_type: str | None) -> list[str]:
    """The entity's repo path: a query's file or a dashboard's dir."""
    return [query_relpath(conn_type or "", name) if kind == "query" else dashboard_reldir(name)]


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


# --- Merge-in --------------------------------------------------------------
# Every sync (attaching a remote, Commit, Restore, opening history) first
# merges the repo head into the DB: entities missing locally are imported
# (unless deleted or renamed here after we last agreed on the repo's copy), and
# nothing local is ever overwritten. An entity is a *conflict* when the repo's
# copy changed since this workspace last agreed with it and differs from the
# local one; a local edit on top of an unchanged repo copy is not.
#
# State lives beside the clone, {base}/{id}.sync.json:
#   {"agreed": {entity key: repo object id}, "conflicts": [{kind, name, conn_type}]}


def _state_path(ws: WorkspaceRec) -> Path:
    return _clone_base() / f"{ws.id}.sync.json"


def _load_state(ws: WorkspaceRec) -> dict[str, Any]:
    try:
        state = json.loads(_state_path(ws).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    return {"agreed": state.get("agreed") or {}, "conflicts": state.get("conflicts") or []}


def _save_state(ws: WorkspaceRec, state: dict[str, Any]) -> None:
    path = _state_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")


def conflicts(ws: WorkspaceRec) -> list[dict[str, Any]]:
    """Entities the last sync kept local although the repo had another version."""
    return _load_state(ws)["conflicts"] if configured(ws) else []


async def unsynced(ws: WorkspaceRec) -> list[dict[str, Any]]:
    """Entities not in git as they are (no git_sha): a failed or pending
    commit, or not yet compared by a sync."""
    if not configured(ws):
        return []
    from .dashboards import unsynced_dashboards
    from .queries import unsynced_queries

    return [{"kind": "query", "name": n, "conn_type": t} for t, n in await unsynced_queries(ws.id)] + [
        {"kind": "dashboard", "name": n, "conn_type": None} for n in await unsynced_dashboards(ws.id)
    ]


def _key(kind: str, name: str, conn_type: str | None) -> str:
    return f"query/{conn_type}/{name}" if kind == "query" else f"dashboard/{name}"


async def _tree_files(wd: Path, ref: str, *paths: str) -> dict[str, str]:
    """{path: blob oid} for every file in the tree at `ref` (under `paths` if given)."""
    out = await _git("ls-tree", "-r", ref, *(["--", *paths] if paths else []), cwd=wd)
    files: dict[str, str] = {}
    for line in out.splitlines():
        meta, _, fpath = line.partition("\t")
        files[fpath] = meta.split()[2]
    return files


async def _repo_entities(wd: Path, ref: str, *paths: str) -> list[dict[str, Any]]:
    """The entities in the tree at `ref` (under `paths` if given), each with an
    id that changes whenever any of its files does."""
    files = await _tree_files(wd, ref, *paths)
    found = []
    for fpath, oid in files.items():
        parts = fpath.split("/")
        if len(parts) == 3 and parts[0] == "queries" and parts[2].endswith(".yaml"):
            found.append({"kind": "query", "conn_type": unquote(parts[1]), "relpath": fpath, "oid": oid})
        elif len(parts) == 3 and parts[0] == "dashboards" and parts[2] == "meta.yaml":
            ddir = f"dashboards/{parts[1]}"  # skipped when incomplete: a hand edit
            if all(f"{ddir}/{f}" in files for f in DASHBOARD_FILES):
                oid = "+".join(files[f"{ddir}/{f}"] for f in DASHBOARD_FILES)
                found.append({"kind": "dashboard", "conn_type": None, "relpath": ddir, "oid": oid})
    return found


async def _read_repo_entity(wd: Path, ref: str, kind: str, relpath: str) -> dict[str, Any]:
    """An entity's content at `ref`, in the DB row shape. The caller has checked
    a dashboard dir holds all of DASHBOARD_FILES."""
    if kind == "query":
        return query_from_yaml(await _git("show", f"{ref}:{relpath}", cwd=wd))
    return dashboard_from_files({f: await _git("show", f"{ref}:{relpath}/{f}", cwd=wd) for f in DASHBOARD_FILES})


def _empty_merge() -> dict[str, Any]:
    return {"imported": [], "conflicts": []}


async def _merge(ws: WorkspaceRec, wd: Path, head: str) -> dict[str, Any]:
    """Import what the repo has and the DB lacks; record conflicts. Caller
    holds the lock and has fetched."""
    from .dashboards import get_dashboard, upsert_dashboard
    from .queries import get_predefined_query, save_predefined_query

    state = _load_state(ws)
    agreed: dict[str, str] = state["agreed"]
    imported: list[dict[str, Any]] = []
    found_conflicts: list[dict[str, Any]] = []
    head_sha = (await _git("rev-parse", head, cwd=wd)).strip()
    for e in await _repo_entities(wd, head):
        kind, conn_type = e["kind"], e["conn_type"]
        try:
            repo = await _read_repo_entity(wd, head, kind, e["relpath"])
        except GitSyncError:
            continue  # unreadable in the repo: nothing to import or compare
        name = repo["query_name"] if kind == "query" else repo["name"]
        if kind == "query":
            local = await get_predefined_query(conn_type, name, ws.id)
            same = local is not None and query_to_yaml(local) == query_to_yaml(repo)
        else:
            local = await get_dashboard(name, ws.id)
            same = local is not None and dashboard_to_files(local) == dashboard_to_files(repo)
        key = _key(kind, name, conn_type)
        entry = {"kind": kind, "name": name, "conn_type": conn_type}
        if local is None and agreed.get(key) == e["oid"]:
            continue  # deleted or renamed here since we last agreed: a local change
        if local is None:
            if kind == "query":
                await save_predefined_query(
                    name,
                    conn_type,
                    repo["query"],
                    repo["cell_view"],
                    repo["order_by"],
                    repo["fields"],
                    workspace_id=ws.id,
                )
            else:
                await upsert_dashboard(name, repo["html"], repo["queries"], repo["params"], workspace_id=ws.id)
            imported.append(entry)
            agreed[key] = e["oid"]
            await _mark(ws, kind, name, conn_type, head_sha, None)
        elif same:
            agreed[key] = e["oid"]
            await _mark(ws, kind, name, conn_type, head_sha, local)
        elif agreed.get(key) == e["oid"]:
            pass  # only changed here: an uncommitted local change
        else:
            found_conflicts.append(entry)
    state["conflicts"] = found_conflicts
    _save_state(ws, state)
    return {"imported": imported, "conflicts": found_conflicts}


async def _agree(ws: WorkspaceRec, wd: Path, ref: str, kind: str, name: str, conn_type: str | None) -> None:
    """Record that the DB now matches (or deliberately took) the repo's copy of
    one entity at `ref`, clearing any conflict on it."""
    state = _load_state(ws)
    found = await _repo_entities(wd, ref, *_entity_paths(kind, name, conn_type))
    if found:
        state["agreed"][_key(kind, name, conn_type)] = found[0]["oid"]
    state["conflicts"] = [
        c for c in state["conflicts"] if (c["kind"], c["name"], c["conn_type"]) != (kind, name, conn_type)
    ]
    _save_state(ws, state)


async def sync(ws: WorkspaceRec) -> dict[str, Any]:
    """Fetch and merge the repo into the DB (see above): the workspace panel's
    Sync, and saving a remote. Commit, Restore and history run the same merge
    after their own fetch."""
    _require_remote(ws)
    async with _lock(ws):
        wd = await _ensure_repo(ws)
        head = await _origin_head(wd, ws)
        if head is None:
            return _empty_merge()
        return await _merge(ws, wd, head)


# --- Operations ------------------------------------------------------------


async def store(
    ws: WorkspaceRec,
    kind: str,
    name: str,
    conn_type: str | None = None,
    message: str | None = None,
    old_name: str = "",
) -> dict[str, Any]:
    """Export one entity's saved DB state into the clone, commit, push; a
    query renamed from `old_name` drops the old file in the same commit.
    The workdir is reset to the remote head first — exports are deterministic
    from the DB and each commit touches one entity, so this is always safe; a
    push rejected by another instance's concurrent push is retried."""
    _check_kind(kind, conn_type)
    _require_remote(ws)  # unconfigured -> 409 before any DB/entity lookup
    async with _lock(ws):
        return await _retry_if_rejected(lambda: _store_once(ws, kind, name, conn_type, message, old_name))


# Every save pushes, so busy remotes see races; each retry starts from the new head.
_PUSH_ATTEMPTS = 5


async def _retry_if_rejected(op: Callable[[], Awaitable[Any]]) -> Any:
    """Run `op`; while its push is rejected because another instance pushed
    between our fetch and push, run it again from the new head."""
    for _ in range(_PUSH_ATTEMPTS - 1):
        try:
            return await op()
        except GitSyncError as e:
            if not e.rejected:
                raise
    return await op()


async def _store_once(
    ws: WorkspaceRec,
    kind: str,
    name: str,
    conn_type: str | None,
    message: str | None,
    old_name: str = "",
) -> dict[str, Any]:
    """One store attempt; a retry reports only its own merge."""
    wd = await _ensure_repo(ws)
    head = await _origin_head(wd, ws)
    merged = _empty_merge()
    if head:
        await _git("reset", "--hard", head, cwd=wd)
        merged = await _merge(ws, wd, head)
    entity = await _load_entity(ws, kind, name, conn_type)
    paths = _entity_paths(kind, name, conn_type)
    old = query_relpath(conn_type or "", old_name) if old_name else ""
    old = old if old and (wd / old).exists() else ""
    if old:
        await _agree(ws, wd, "HEAD", kind, old_name, conn_type)  # keeps sync from importing it back
        # git mv, not write-then-rm: a case-only rename is one file on a case-insensitive disk.
        await _git("mv", "-f", old, paths[0], cwd=wd)
    if kind == "query":
        (wd / paths[0]).parent.mkdir(parents=True, exist_ok=True)
        (wd / paths[0]).write_text(query_to_yaml(entity), encoding="utf-8")
    else:
        relpath = paths[0]
        ddir = wd / relpath
        if ddir.exists():
            shutil.rmtree(ddir)
        ddir.mkdir(parents=True, exist_ok=True)
        for fname, content in dashboard_to_files(entity).items():
            (ddir / fname).write_text(content, encoding="utf-8")
    await _git("add", "-A", "--", *paths, cwd=wd)
    if not (await _git("status", "--porcelain", "--", *paths, *([old] if old else []), cwd=wd)).strip():
        # Already in git as it is.
        if head:
            await _mark(ws, kind, name, conn_type, (await _git("rev-parse", head, cwd=wd)).strip(), entity)
        return {"committed": False, "sha": None, "message": "no changes", **merged, "conflicts": conflicts(ws)}
    label = f"{conn_type}/{name}" if kind == "query" else name
    verb = "rename" if old else "store"
    await _git("commit", "-m", message or f"{verb} {kind} {label}", cwd=wd)
    await _git("push", "origin", ws.branch, cwd=wd, credential=_credential(ws))
    # Pushed: bookkeeping failing now must not undo the save; the row just stays
    # unmarked (No git sync) until the next save or sync.
    sha = None
    try:
        sha = (await _git("rev-parse", "HEAD", cwd=wd)).strip()
        await _agree(ws, wd, "HEAD", kind, name, conn_type)  # the repo now holds exactly the local copy
        await _mark(ws, kind, name, conn_type, sha, entity)
    except GitSyncError:
        pass
    return {"committed": True, "sha": sha, "message": "stored", **merged, "conflicts": conflicts(ws)}


async def _mark(
    ws: WorkspaceRec, kind: str, name: str, conn_type: str | None, sha: str, entity: dict[str, Any] | None
) -> None:
    """Record `sha` as the commit holding the entity, unless its row changed
    since `entity` was read (None: just written by us)."""
    if kind == "query":
        from .queries import set_query_git_sha

        await set_query_git_sha(conn_type or "", name, ws.id, sha, unchanged_from=entity)
    else:
        from .dashboards import set_dashboard_git_sha

        await set_dashboard_git_sha(name, ws.id, sha, unchanged_from=entity)


async def remove(ws: WorkspaceRec, conn_type: str, name: str) -> None:
    """Drop a deleted query's file from the repo (`delete query …`), so no
    instance imports it back; history keeps it. No file, no commit."""
    _require_remote(ws)
    async with _lock(ws):
        await _retry_if_rejected(lambda: _remove_once(ws, conn_type, name))


async def commit_change(
    ws: WorkspaceRec,
    kind: str,
    name: str,
    conn_type: str | None,
    apply: Callable[[], Awaitable[Any]],
    *,
    old_name: str = "",
    deleted: bool = False,
) -> Any:
    """Apply a DB change (`apply`, returning its result) and commit it as one
    unit when `ws` syncs — the entity stored, or (`deleted`) a query's file
    removed: if git fails, the touched rows (`name`, and a rename's
    `old_name`) are put back as they were and GitSyncError raised."""
    if not configured(ws):
        return await apply()
    from .dashboards import restore_dashboards, snapshot_dashboards
    from .queries import restore_queries, snapshot_queries

    names = [name, old_name] if old_name else [name]
    is_query = kind == "query"
    # shortcut: another write to these rows while git runs is undone too; fine for one user per workspace.
    snap = await (snapshot_queries(conn_type or "", names, ws.id) if is_query else snapshot_dashboards(names, ws.id))
    result = await apply()
    try:
        if deleted:
            await remove(ws, conn_type or "", name)
        else:
            await store(ws, kind, name, conn_type, old_name=old_name)
    except Exception as e:  # any failure (git, disk, DB): undo, so DB and repo never part
        await (restore_queries(conn_type or "", snap, ws.id) if is_query else restore_dashboards(snap, ws.id))
        if isinstance(e, GitSyncError):
            raise GitSyncError(f"not saved: {e}", status=e.status) from e
        raise
    return result


async def _remove_once(ws: WorkspaceRec, conn_type: str, name: str) -> None:
    wd = await _ensure_repo(ws)
    head = await _origin_head(wd, ws)
    path = query_relpath(conn_type, name)
    if head is None:
        return
    await _git("reset", "--hard", head, cwd=wd)
    if not (wd / path).exists():
        return
    # Agreeing on the repo's copy keeps sync from importing an identical one back.
    await _agree(ws, wd, head, "query", name, conn_type)
    await _git("rm", "-q", "--", path, cwd=wd)
    await _git("commit", "-m", f"delete query {conn_type}/{name}", cwd=wd)
    await _git("push", "origin", ws.branch, cwd=wd, credential=_credential(ws))


async def history(
    ws: WorkspaceRec,
    kind: str,
    name: str,
    conn_type: str | None = None,
    before: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Commits touching the entity's path, newest first. `before=<sha>` pages
    strictly older commits. Reads objects only — never touches the working
    tree."""
    _check_kind(kind, conn_type)
    _require_remote(ws)
    paths = _entity_paths(kind, name, conn_type)
    async with _lock(ws):
        wd = await _ensure_repo(ws)
        head = await _origin_head(wd, ws)
        if head is None:
            return {"revisions": [], "has_more": False}
        await _merge(ws, wd, head)
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
            *paths,
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
    the remote branch head), recreating it if it was deleted. Reads via
    `git show` — HEAD never moves, history is never rewritten. Parses fully
    before writing, so the DB row is either untouched or fully replaced."""
    _check_kind(kind, conn_type)
    _require_remote(ws)
    paths = _entity_paths(kind, name, conn_type)
    async with _lock(ws):
        wd = await _ensure_repo(ws)
        head = await _origin_head(wd, ws)
        resolved = await _resolve_ref(wd, ref) if ref and ref != "HEAD" else head
        if resolved is None:
            raise GitSyncError(f"{kind} {name!r} not found in git", status=404)
        merged = await _merge(ws, wd, head) if head else _empty_merge()

        async def _show(path: str) -> str:
            return await _git("show", f"{resolved}:{path}", cwd=wd)

        if kind == "query":
            try:
                text = await _show(paths[0])
            except GitSyncError as e:
                raise GitSyncError(f"query {name!r} not found at {resolved}", status=404) from e
            data = query_from_yaml(text)
        else:
            # All three files or nothing: a dir missing one is a hand edit, and
            # restoring the rest would leave a truncated dashboard.
            try:
                tree = await _tree_files(wd, resolved, paths[0])
            except GitSyncError:
                tree = {}
            missing = [f for f in DASHBOARD_FILES if f"{paths[0]}/{f}" not in tree]
            if missing:
                what = f"is missing {missing[0]}" if tree else "not found"
                raise GitSyncError(f"dashboard {name!r} {what} at {resolved}", status=404)
            data = await _read_repo_entity(wd, resolved, "dashboard", paths[0])

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
            data["html"],
            data["queries"],
            data["params"],
            workspace_id=ws.id,
        )
    # Taking a revision on purpose settles any conflict with the repo's head.
    if head:
        async with _lock(ws):
            await _agree(ws, wd, head, kind, name, conn_type)
    merged["conflicts"] = conflicts(ws)
    return {"restored": True, "sha": resolved, **merged}
