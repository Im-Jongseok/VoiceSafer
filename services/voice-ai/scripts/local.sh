#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then python3 scripts/configure.py; fi
if [[ "$(uname -s)" == Darwin || "${VOICE_DEVICE:-}" == cpu ]]; then
  exec docker compose -f compose.yml -f compose.cpu.yml "$@"
fi
exec docker compose -f compose.yml "$@"
