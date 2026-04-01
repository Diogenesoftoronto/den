#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

git -C "$PROJECT_DIR" config core.hooksPath .githooks
echo "Installed git hooks from $PROJECT_DIR/.githooks"
