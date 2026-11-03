#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
action="${1:-help}"
if [[ $# -gt 0 ]]; then shift; fi
if [[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 &&
      ( $# -eq 0 || ( $# -eq 1 && "$1" == qwen ) ) ]]; then
  case "$action" in
    up|stop|down|status|ps|logs)
      mac_python="$project_dir/services/voice-ai/.venv/bin/python"
      if [[ "$action" == up && ! -x "$mac_python" ]]; then
        uv venv --python 3.12 "$project_dir/services/voice-ai/.venv"
        uv pip install --python "$mac_python" -r "$project_dir/services/voice-ai/requirements-mac.txt"
      fi
      if [[ ! -x "$mac_python" ]]; then echo 'Run bash ai.sh up first.' >&2; exit 1; fi
      [[ "$action" == down ]] && action=stop
      [[ "$action" == ps ]] && action=status
      exec "$mac_python" "$project_dir/services/voice-ai/scripts/macos.py" "$action"
      ;;
  esac
fi
case "$action" in
  help|-h|--help)
    echo 'Usage: bash ai.sh up|stop|status|logs [qwen]'
    echo 'Apple Silicon: native MLX Qwen. Other explicit services use Docker Compose.'
    ;;
  up) exec bash "$project_dir/services/voice-ai/scripts/local.sh" up -d --build "${@:-qwen}" ;;
  stop|down|logs|ps) exec bash "$project_dir/services/voice-ai/scripts/local.sh" "$action" "$@" ;;
  status) exec bash "$project_dir/services/voice-ai/scripts/local.sh" ps -a "$@" ;;
  *) echo "Unknown action: $action" >&2; exit 2 ;;
esac
