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

# All mutable state goes in one FHS-conventional directory rather than the
# platform user-data dir under $HOME. Pinning DB_PATH puts the SQLite file and
# its siblings (the .key file, the git-sync clones) there at a flat, documented
# path; pre-creating it owned by the app user means a named volume mounted
# there is seeded with the right ownership.
RUN mkdir -p /var/lib/queryview && chown queryview:queryview /var/lib/queryview
ENV DB_PATH=/var/lib/queryview/queryview.db

WORKDIR /home/queryview
USER queryview

EXPOSE 8000

# Health probe uses stdlib (slim image has no curl).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["queryview"]
