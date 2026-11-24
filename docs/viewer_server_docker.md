# Running the viewer server

The [viewer server](./system/viewer_server.md) ships in the same package and
[image](docker.md) as the app; pass the command `queryview-server` and mount
its [config file](./system/viewer_server.md#the-config-file):

```bash
docker run -d --name queryview-server \
  -p 127.0.0.1:8000:8000 \
  -v ./server.yaml:/etc/queryview/server.yaml:ro \
  ghcr.io/kolodkin/queryview:latest queryview-server
```

- **Config:** `QV_CONFIG` names the file, default `/etc/queryview/server.yaml`.
  Mount it as a secret: it holds the passwords and the git token.
- **Port:** `--port`, else `PORT`, else 8000.
- **State:** none to keep. `DATA_DIR` holds only the repo's clone, made afresh
  at every start, so replicas need no shared disk.
- **Startup fails loudly:** a malformed config, an invalid connection or a
  failed first clone exits non-zero, naming the connection or the git error.

## Related docs

- [viewer_server.md](./system/viewer_server.md) — the viewer server and its config file.
- [docker.md](docker.md) — the image, and running the app from it.
