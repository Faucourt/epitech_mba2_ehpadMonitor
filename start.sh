#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_URL="http://localhost:3002"
BACKEND_URL="http://localhost:8001/health"

DOCKER_TIMEOUT_SECONDS="${DOCKER_TIMEOUT_SECONDS:-180}"
SERVICE_TIMEOUT_SECONDS="${SERVICE_TIMEOUT_SECONDS:-180}"
NO_BROWSER="${NO_BROWSER:-0}"

step() { echo "==> $1"; }
has_cmd() { command -v "$1" >/dev/null 2>&1; }

detect_os() {
  case "$(uname -s)" in
    Darwin*)              echo "mac"     ;;
    MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
    *)                    echo "linux"   ;;
  esac
}

docker_daemon_ready() { docker info >/dev/null 2>&1; }

find_docker_desktop_win() {
  local candidates=(
    "$PROGRAMFILES/Docker/Docker/Docker Desktop.exe"
    "$LOCALAPPDATA/Programs/Docker/Docker/Docker Desktop.exe"
  )
  for c in "${candidates[@]}"; do
    [[ -f "$c" ]] && echo "$c" && return 0
  done
  return 1
}

start_docker_desktop() {
  if docker_daemon_ready; then
    step "Docker daemon déjà disponible"
    return
  fi
  local os; os="$(detect_os)"
  case "$os" in
    mac)
      [[ -d "/Applications/Docker.app" ]] || { echo "Docker Desktop introuvable dans /Applications."; exit 1; }
      step "Démarrage de Docker Desktop (macOS)"
      open -a Docker
      ;;
    windows)
      local exe
      if exe="$(find_docker_desktop_win 2>/dev/null)"; then
        step "Démarrage de Docker Desktop (Windows)"
        "$exe" &
      else
        echo "Docker Desktop introuvable. Installe-le puis relance."; exit 1
      fi
      ;;
    *)
      echo "Le daemon Docker n'est pas démarré. Lance le service Docker puis relance."; exit 1
      ;;
  esac
  step "Attente du daemon Docker (max ${DOCKER_TIMEOUT_SECONDS}s)"
  local start_ts; start_ts="$(date +%s)"
  while true; do
    docker_daemon_ready && { step "Docker daemon prêt"; return; }
    (( $(date +%s) - start_ts >= DOCKER_TIMEOUT_SECONDS )) && { echo "Timeout Docker."; exit 1; }
    sleep 4
  done
}

wait_http_ready() {
  local url="$1" timeout="$2" start_ts; start_ts="$(date +%s)"
  while true; do
    if has_cmd curl; then
      curl -fsS --max-time 5 "$url" >/dev/null 2>&1 && return 0
    elif has_cmd wget; then
      wget -q --spider --timeout=5 "$url" && return 0
    fi
    (( $(date +%s) - start_ts >= timeout )) && return 1
    sleep 3
  done
}

show_failure_context() {
  echo; echo "Etat Docker Compose :"; docker compose ps || true
  echo; echo "Derniers logs :"; docker compose logs --tail=60 backend dashboard simulator || true
}

open_browser() {
  local url="$1"
  case "$(detect_os)" in
    mac)     open "$url" >/dev/null 2>&1 || true ;;
    windows) cmd.exe /c start "" "$url" >/dev/null 2>&1 || true ;;
    linux)   xdg-open "$url" >/dev/null 2>&1 || true ;;
  esac
}

main() {
  cd "$PROJECT_ROOT"
  has_cmd docker || { echo "Docker introuvable. Installe Docker Desktop puis relance."; exit 1; }

  step "Vérification Docker Desktop"
  start_docker_desktop

  step "Validation de la configuration"
  docker compose config >/dev/null

  step "Construction et démarrage de la stack EPicare Palace"
  docker compose up --build -d

  step "Attente du backend (port 8001)"
  if ! wait_http_ready "$BACKEND_URL" "$SERVICE_TIMEOUT_SECONDS"; then
    show_failure_context
    echo "Le backend ne répond pas sur $BACKEND_URL"; exit 1
  fi

  step "Attente du dashboard (port 3002)"
  if ! wait_http_ready "$DASHBOARD_URL" "$SERVICE_TIMEOUT_SECONDS"; then
    show_failure_context
    echo "Le dashboard ne répond pas sur $DASHBOARD_URL"; exit 1
  fi

  echo
  echo "╔══════════════════════════════════════════════╗"
  echo "║         EPicare Palace — Stack prête         ║"
  echo "╠══════════════════════════════════════════════╣"
  echo "║  Dashboard soignant : http://localhost:3002  ║"
  echo "║  API backend        : http://localhost:8001  ║"
  echo "║  Docs API           : http://localhost:8001/docs ║"
  echo "╚══════════════════════════════════════════════╝"
  echo
  echo "Logs en direct  : docker compose logs -f --tail=200"
  echo "Arrêt complet   : docker compose down"

  [[ "$NO_BROWSER" != "1" ]] && { step "Ouverture du dashboard"; open_browser "$DASHBOARD_URL"; }
}

main "$@"
