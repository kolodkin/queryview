# syntax=docker/dockerfile:1
# queryview image: QueryView API server + bundled SPA.
# Build-arg QUERYVIEW_VERSION pins the wheel to install from PyPI.
FROM python:3.13-slim

ARG QUERYVIEW_VERSION
ARG PIP_INDEX_URL=https://pypi.org/simple/

LABEL org.opencontainers.image.source="https://github.com/kolodkin/queryview"
LABEL org.opencontainers.image.description="QueryView API server + SPA"

# git for workspace git sync (the backend shells out to it); openssh-client so
# ssh:// remotes work when a key is mounted into /home/queryview/.ssh.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    --index-url "${PIP_INDEX_URL}" \
    "queryview==${QUERYVIEW_VERSION}"

# Run as a non-root user.
RUN useradd --create-home --uid 1000 queryview
WORKDIR /home/queryview
USER queryview

# The default is the user-data dir (/home/queryview/.local/share/queryview);
# pin the SQLite file (and its sibling .key file and git-sync clones) to the top
# of the home dir instead, so a volume mounted at /home/queryview persists all
# state at a flat, documented path.
ENV DB_PATH=/home/queryview/queryview.db

EXPOSE 8000

# Health probe uses stdlib (slim image has no curl).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["queryview"]
