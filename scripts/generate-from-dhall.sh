#!/usr/bin/env bash
# Generate all configuration files from den.dhall
# Usage: generate-from-dhall.sh <den.dhall> [output-dir]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DHALL_DIR="$PROJECT_DIR/dhall"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

if [ $# -lt 1 ]; then
    echo "Usage: $0 <den.dhall> [output-dir]"
    exit 1
fi

DHALL_FILE_INPUT="$1"
OUTPUT_DIR="${2:-$PWD}"

if [ ! -f "$DHALL_FILE_INPUT" ]; then
    log_error "Dhall file not found: $DHALL_FILE_INPUT"
    exit 1
fi

DHALL_FILE="$(cd "$(dirname "$DHALL_FILE_INPUT")" && pwd)/$(basename "$DHALL_FILE_INPUT")"

run_dhall() {
    if command -v dhall >/dev/null 2>&1; then
        dhall "$@"
    elif command -v mise >/dev/null 2>&1; then
        mise x aqua:dhall-lang/dhall-haskell@latest -- dhall "$@"
    else
        return 127
    fi
}

if ! run_dhall --version >/dev/null 2>&1; then
    log_error "dhall binary not found. Install via mise: mise use -g aqua:dhall-lang/dhall-haskell@latest"
    exit 1
fi

log_info "Validating Dhall file: $DHALL_FILE"
if ! run_dhall type --file "$DHALL_FILE" >/dev/null 2>&1; then
    log_error "Dhall type check failed for: $DHALL_FILE"
    run_dhall type --file "$DHALL_FILE" 2>&1 || true
    exit 1
fi

log_success "Dhall validation passed"
mkdir -p "$OUTPUT_DIR"

BACKEND_EXPR="merge { Nix = \"Nix\", Guix = \"Guix\" } ((${DHALL_FILE}).backend)"
BACKEND="$(run_dhall text <<< "$BACKEND_EXPR")"
log_info "Detected backend: $BACKEND"

log_info "Generating railway.toml..."
RAILWAY_EXPR="(${DHALL_DIR}/generate-railway.dhall) (${DHALL_FILE})"
run_dhall text <<< "$RAILWAY_EXPR" > "$OUTPUT_DIR/railway.toml"
log_success "Generated: $OUTPUT_DIR/railway.toml"

generate_guix_configs() {
    log_info "Generating Guix configuration files..."

    MANIFEST_EXPR="((${DHALL_DIR}/generate-guix.dhall) (${DHALL_FILE})).manifest"
    CHANNELS_EXPR="((${DHALL_DIR}/generate-guix.dhall) (${DHALL_FILE})).channels"

    run_dhall text <<< "$MANIFEST_EXPR" > "$OUTPUT_DIR/manifest.scm"
    run_dhall text <<< "$CHANNELS_EXPR" > "$OUTPUT_DIR/channels.scm"

    log_success "Generated: $OUTPUT_DIR/manifest.scm"
    log_success "Generated: $OUTPUT_DIR/channels.scm"
}

generate_nix_configs() {
    log_info "Generating Nix configuration files..."
    cat > "$OUTPUT_DIR/flake.nix" << 'FLAKE'
# Generated from den.dhall (template)

{
  description = "Den environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            fish
            git
            helix
            zellij
          ];
        };
      });
}
FLAKE
    log_success "Generated: $OUTPUT_DIR/flake.nix"
}

if [ "$BACKEND" = "Guix" ]; then
    generate_guix_configs
else
    generate_nix_configs
fi

log_success "All configuration files generated in: $OUTPUT_DIR"
ls -1 "$OUTPUT_DIR"/railway.toml "$OUTPUT_DIR"/manifest.scm "$OUTPUT_DIR"/channels.scm "$OUTPUT_DIR"/flake.nix 2>/dev/null || true
