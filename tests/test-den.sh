#!/usr/bin/env bash
# Automated tests for den — personal cloud dev environments
# Usage: ./tests/test-den.sh [--no-build]
#   --no-build   Skip Docker build (syntax/lint only)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
IMAGE_NAME="den:test"
PASS=0
FAIL=0
SKIP=0

NO_BUILD=false
for arg in "$@"; do
    case "$arg" in
        --no-build) NO_BUILD=true ;;
    esac
done

pass() { PASS=$((PASS + 1)); echo "  ✓ $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  ✗ $1"; }
skip() { SKIP=$((SKIP + 1)); echo "  ⊘ $1 (skipped)"; }

cleanup() {
    if [ "$NO_BUILD" = false ]; then
        docker rm -f den-test-container 2>/dev/null || true
        docker rmi -f "$IMAGE_NAME" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "==> Testing den"
echo ""

# ── 1. Secrets safety ──────────────────────────────────────────
echo "── Secrets safety"

if grep -q "^\.env$" "$PROJECT_DIR/.gitignore" && \
   grep -q "^\.env\.\*$" "$PROJECT_DIR/.gitignore"; then
    pass ".gitignore blocks .env and .env.*"
else
    fail ".gitignore missing .env patterns"
fi

if grep -q "^!\.env\.example$" "$PROJECT_DIR/.gitignore"; then
    pass ".gitignore allows .env.example"
else
    fail ".gitignore doesn't allow .env.example"
fi

if grep -q "^\.env$" "$PROJECT_DIR/.dockerignore"; then
    pass ".dockerignore blocks .env"
else
    fail ".dockerignore missing .env"
fi

# Check no actual secrets exist
if [ -f "$PROJECT_DIR/.env" ]; then
    fail ".env file exists — should not be committed"
else
    pass "No .env file present"
fi

if git -C "$PROJECT_DIR" ls-files --cached | grep -q "^\.env$"; then
    fail ".env is tracked by git"
else
    pass ".env is not tracked by git"
fi

echo ""

# ── 2. Script syntax ──────────────────────────────────────────
echo "── Script syntax (bash -n)"

for script in "$PROJECT_DIR"/scripts/*.sh; do
    name=$(basename "$script")
    if bash -n "$script" 2>/dev/null; then
        pass "$name"
    else
        fail "$name"
    fi
done

echo ""

# ── 3. Fish function syntax ──────────────────────────────────
echo "── Fish function syntax"

DEN_FISH="$HOME/.dotfiles/fish/.config/fish/functions/den.fish"
if [ -f "$DEN_FISH" ]; then
    if fish -n "$DEN_FISH" 2>/dev/null; then
        pass "den.fish parses"
    else
        fail "den.fish syntax error"
    fi

    if fish -c "source $DEN_FISH; den" >/dev/null 2>&1; then
        pass "den.fish loads and runs help"
    else
        fail "den.fish fails to load"
    fi

    # Verify no leftover "devbox" references
    if grep -qi "devbox" "$DEN_FISH"; then
        fail "den.fish still contains 'devbox' references"
    else
        pass "den.fish has no 'devbox' references"
    fi
else
    skip "den.fish not found at $DEN_FISH"
fi

echo ""

# ── 4. Dockerfile lint ──────────────────────────────────────
echo "── Dockerfile lint (docker build --check)"

for df in Dockerfile Dockerfile.guix; do
    if docker build --check -f "$PROJECT_DIR/$df" "$PROJECT_DIR" >/dev/null 2>&1; then
        pass "$df passes lint"
    else
        fail "$df lint errors"
    fi
done

echo ""

# ── 5. No stale references ──────────────────────────────────
echo "── Stale reference check"

# Check all tracked files for leftover "devbox" references
stale=$(grep -rli "devbox" "$PROJECT_DIR" \
    --include='*.sh' --include='*.scm' --include='*.md' \
    --include='*.toml' --include='*.example' \
    --include='Dockerfile*' --include='.gitignore' \
    --include='.dockerignore' \
    --exclude='test-den.sh' 2>/dev/null || true)

if [ -z "$stale" ]; then
    pass "No 'devbox' references in project files"
else
    fail "Stale 'devbox' references in: $stale"
fi

echo ""

# ── 6. Docker build + image validation ──────────────────────
if [ "$NO_BUILD" = true ]; then
    echo "── Docker build (skipped with --no-build)"
    skip "Dockerfile build"
    skip "Tool verification"
    skip "User setup"
    skip "Workspace setup"
    skip "SSH config"
    echo ""
else
    echo "── Docker build (Nix variant)"

    if docker build -f "$PROJECT_DIR/Dockerfile" -t "$IMAGE_NAME" "$PROJECT_DIR" >/dev/null 2>&1; then
        pass "Dockerfile builds successfully"
    else
        fail "Dockerfile build failed"
        echo ""
        echo "==> Results: $PASS passed, $FAIL failed, $SKIP skipped"
        exit 1
    fi

    echo ""
    echo "── Tool verification"

    TOOLS="fish hx zellij jj gh tailscale coder mise"
    for tool in $TOOLS; do
        if docker run --rm --entrypoint sh "$IMAGE_NAME" -c "which $tool" >/dev/null 2>&1; then
            pass "$tool found"
        else
            fail "$tool not found"
        fi
    done

    echo ""
    echo "── Container setup"

    # User exists with correct shell
    user_shell=$(docker run --rm --entrypoint sh "$IMAGE_NAME" -c "getent passwd den | cut -d: -f7")
    if [ "$user_shell" = "/usr/bin/fish" ]; then
        pass "den user has fish shell"
    else
        fail "den user shell is '$user_shell', expected /usr/bin/fish"
    fi

    # User is in wheel group
    if docker run --rm --entrypoint sh "$IMAGE_NAME" -c "id den" 2>&1 | grep -q "wheel"; then
        pass "den user is in wheel group"
    else
        fail "den user not in wheel group"
    fi

    # Workspace exists and is owned by den
    ws_owner=$(docker run --rm --entrypoint sh "$IMAGE_NAME" -c "stat -c '%U' /workspace")
    if [ "$ws_owner" = "den" ]; then
        pass "/workspace owned by den"
    else
        fail "/workspace owned by '$ws_owner', expected den"
    fi

    # SSH config
    if docker run --rm --entrypoint sh "$IMAGE_NAME" -c "grep -q 'PermitRootLogin no' /etc/ssh/sshd_config"; then
        pass "SSH root login disabled"
    else
        fail "SSH root login not disabled"
    fi

    if docker run --rm --entrypoint sh "$IMAGE_NAME" -c "grep -q 'PasswordAuthentication no' /etc/ssh/sshd_config"; then
        pass "SSH password auth disabled"
    else
        fail "SSH password auth not disabled"
    fi

    if docker run --rm --entrypoint sh "$IMAGE_NAME" -c "grep -q 'AllowAgentForwarding yes' /etc/ssh/sshd_config"; then
        pass "SSH agent forwarding enabled"
    else
        fail "SSH agent forwarding not enabled"
    fi

    # Sudoers
    if docker run --rm --entrypoint sh "$IMAGE_NAME" -c "cat /etc/sudoers.d/den" 2>&1 | grep -q "NOPASSWD"; then
        pass "Passwordless sudo configured"
    else
        fail "Passwordless sudo not configured"
    fi

    # Entrypoint exists and is executable
    if docker run --rm --entrypoint sh "$IMAGE_NAME" -c "test -x /usr/local/bin/entrypoint.sh"; then
        pass "entrypoint.sh is executable"
    else
        fail "entrypoint.sh not executable"
    fi

    if docker run --rm --entrypoint sh "$IMAGE_NAME" -c "test -x /usr/local/bin/bootstrap.sh"; then
        pass "bootstrap.sh is executable"
    else
        fail "bootstrap.sh not executable"
    fi

    echo ""
fi

# ── Summary ──────────────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  $PASS passed, $FAIL failed, $SKIP skipped"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ "$FAIL" -eq 0 ]
