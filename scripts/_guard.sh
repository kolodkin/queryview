#!/usr/bin/env bash
# Refuse to run outside the Claude Code web (cloud) environment: these scripts
# install and start throwaway e2e services under .cache/ and mutate on-disk
# state, which is almost never intended on a developer's own machine.
# CLAUDE_CODE_REMOTE=true is set only in the web container (CLAUDECODE=1 is set
# for local sessions too, so it can't gate on that).
#
# Sourced near the top of each scripts/setup*.sh. Override for a deliberate
# local run with CLAUDEAI_ALLOW_LOCAL=1.
if [ "${CLAUDEAI_ALLOW_LOCAL:-}" != "1" ] && [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  printf '\033[31m[claudeai]\033[0m %s\n' \
    "Refusing to run: not the Claude Code web environment (CLAUDE_CODE_REMOTE != true)." \
    "Set CLAUDEAI_ALLOW_LOCAL=1 to override for a deliberate local run." >&2
  exit 1
fi
