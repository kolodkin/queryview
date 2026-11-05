# Docker

Every release publishes `ghcr.io/kolodkin/queryview` (`linux/amd64`,
`linux/arm64`), tagged `vX.Y.Z` and, for non-pre-releases, `latest`:

```bash
mkdir -p ~/.queryview
docker run -d --name queryview \
  -p 127.0.0.1:8000:8000 \
  -v ~/.queryview:/var/lib/queryview \
  ghcr.io/kolodkin/queryview:latest
```

- **State:** everything (`db.sqlite`, `encryption.key`, `gitsync/` clones)
  lives in `/var/lib/queryview`, so the mount keeps it across restarts and
  upgrades. Without `-v` it is lost when the container is removed.
- **Shared with `uvx`:** `~/.queryview` is also where a local `uvx queryview`
  keeps its state. Don't run both at once.
- **Ownership:** the container runs as UID 1000. Create the directory first so
  Docker doesn't make it root-owned; if `id -u` isn't 1000, add
  `--user "$(id -u):$(id -g)"`. A named volume (`-v queryview-data:/var/lib/queryview`)
  avoids this but no longer shares state with `uvx`.
- **Port:** the container listens on 8000; remap the host side,
  `-p 127.0.0.1:9000:8000`. Keep `127.0.0.1` — QueryView has no login.

## Connecting to databases on your machine

Inside the container, `localhost` is the container itself. To reach a database:

- **On the host:** use `host.docker.internal` (on Linux, add
  `--add-host=host.docker.internal:host-gateway`).
- **In another container:** `docker network connect <net> queryview`, then use
  its container name as the host.
- **Host networking:** `--network host` makes `localhost` your machine (Linux,
  or Docker Desktop 4.34+ with host networking enabled); `-p` is then ignored.

## Git sync

The image ships `git`, and the mount above covers the clones. Give the
workspace an HTTPS remote carrying a scoped, expiring token —
[gitsync.md](./gitsync.md) has the URL form and what becomes of the credential.

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
