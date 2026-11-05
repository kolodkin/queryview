# Docker

Every release publishes `ghcr.io/kolodkin/queryview` to GHCR for `linux/amd64`
and `linux/arm64`, tagged `vX.Y.Z` and (for non-pre-releases) `latest`:

```bash
docker run -p 127.0.0.1:8000:8000 ghcr.io/kolodkin/queryview:latest
```

To serve on a different host port, remap it (the container keeps listening on
8000, which its healthcheck probes): `docker run -p 127.0.0.1:9000:8000 ...`.
This keeps state inside the container, so it is lost when the container is
removed — see [Persisting it](#persisting-it).

The image runs as the non-root user `queryview` (UID 1000) and sets
`DATA_DIR=/var/lib/queryview`, so every piece of state lives directly under that
one directory:

| Path | Contents |
|---|---|
| `/var/lib/queryview/db.sqlite` | SQLite store: connections, workspaces, queries, dashboards |
| `/var/lib/queryview/encryption.key` | Key that encrypts stored connection passwords |
| `/var/lib/queryview/gitsync/` | Local clones used by workspace git sync |

Mount a volume at `/var/lib/queryview` and all three persist across container
restarts, removals and upgrades.

## Persisting it

```bash
mkdir -p ~/.queryview
docker run -d --name queryview \
  -p 127.0.0.1:8000:8000 \
  -v ~/.queryview:/var/lib/queryview \
  ghcr.io/kolodkin/queryview:latest
```

Create the directory first so Docker doesn't create it owned by root. The
container runs as UID 1000, the first user on most Linux distributions; if
`id -u` prints something else, add `--user "$(id -u):$(id -g)"` so the
container writes the files as you.

`~/.queryview` is also where a local `uvx queryview` keeps its state, so the
container and a local run share one database, key and set of clones with no
extra setup. Don't run both at once: each would serve the same SQLite file.

To let Docker own the location instead, swap the path for a named volume,
`-v queryview-data:/var/lib/queryview`. Docker seeds it from the image, so
ownership is already right and there is nothing to create up front, but the
state no longer lines up with a local run.

## Connecting to databases on your machine

Inside the container, `localhost` is the container itself. To reach a database:

- **On the host:** use `host.docker.internal` (on Linux, add
  `--add-host=host.docker.internal:host-gateway`).
- **In another container:** `docker network connect <net> queryview`, then use
  its container name as the host.
- **Host networking:** `--network host` makes `localhost` your machine (Linux,
  or Docker Desktop 4.34+ with host networking enabled); `-p` is then ignored.

## Git sync

The image ships `git`, so workspace git sync works in the container, and its
clones live under `/var/lib/queryview/gitsync/`, which the mount above already
covers. Give the workspace an HTTPS remote carrying a scoped, expiring token —
[gitsync.md](./gitsync.md) has the URL form and what becomes of the
credential.

SSH also works, but nothing in the container can answer a prompt: the key must
be passphrase-free and `known_hosts` must already list the host. Mount one
dedicated deploy key, not your whole `.ssh`, readable by UID 1000:

```bash
docker run -d --name queryview \
  -p 127.0.0.1:8000:8000 \
  -v ~/.queryview:/var/lib/queryview \
  -v ~/.ssh/queryview_deploy:/home/queryview/.ssh/id_ed25519:ro \
  -v ~/.ssh/known_hosts:/home/queryview/.ssh/known_hosts:ro \
  ghcr.io/kolodkin/queryview:latest
```

## Related docs

- [gitsync.md](./gitsync.md) — workspace git sync, remote URLs and credentials.
- [connect.md](./connect.md) — connections and drivers.
