#!/usr/bin/env bash
set -euo pipefail

DEN_REPO_URL="${DEN_REPO_URL:-https://github.com/Diogenesoftoronto/den}"
DEN_INSTALL_MCP="${DEN_INSTALL_MCP:-0}"
DEN_FORCE="${DEN_FORCE:-1}"

log() {
  printf '==> %s\n' "$*"
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

ensure_cargo_path() {
  if [ -f "$HOME/.cargo/env" ]; then
    # shellcheck disable=SC1090
    . "$HOME/.cargo/env"
  fi

  export PATH="$HOME/.cargo/bin:$PATH"
}

install_rustup() {
  need_cmd curl

  log "Rust toolchain not found; installing rustup"
  curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal
  ensure_cargo_path
}

cargo_install_args() {
  local package="$1"
  local -a args
  args=(install --git "$DEN_REPO_URL" --locked --package "$package")
  if [ "$DEN_FORCE" = "1" ]; then
    args+=(--force)
  fi
  printf '%s\n' "${args[@]}"
}

main() {
  need_cmd git

  ensure_cargo_path
  if ! command -v cargo >/dev/null 2>&1; then
    install_rustup
  fi

  need_cmd cargo

  log "Installing den from $DEN_REPO_URL"
  mapfile -t den_args < <(cargo_install_args den-cli)
  cargo "${den_args[@]}"

  if [ "$DEN_INSTALL_MCP" = "1" ]; then
    log "Installing den-mcp"
    mapfile -t mcp_args < <(cargo_install_args den-mcp)
    cargo "${mcp_args[@]}"
  fi

  ensure_cargo_path
  need_cmd den

  log "Installed den at $(command -v den)"
  log "Running den doctor"
  den doctor || fail "den doctor failed after install"

  if ! printf '%s' ":$PATH:" | grep -q ":$HOME/.cargo/bin:"; then
    log "Add ~/.cargo/bin to your PATH before using den in new shells"
  fi

  if [ "$DEN_INSTALL_MCP" = "1" ]; then
    log "Installed den-mcp at $(command -v den-mcp)"
  fi
}

main "$@"
