#!/usr/bin/env bash
set -euo pipefail

echo "==> Bootstrapping den user environment (Guix)..."

# ── Guix profile setup ──────────────────────────────────────────
# Ensure the den user can use the system-wide Guix profile
# and has guix on PATH for runtime package management
mkdir -p "$HOME/.config/guix"

cat > "$HOME/.profile" << 'PROFILE'
# Guix profile
export GUIX_PROFILE="/var/guix/profiles/per-user/root/den-profile"
if [ -f "$GUIX_PROFILE/etc/profile" ]; then
    . "$GUIX_PROFILE/etc/profile"
fi
export GUIX_LOCPATH="$GUIX_PROFILE/lib/locale"
export PATH="/var/guix/profiles/per-user/root/current-guix/bin:$GUIX_PROFILE/bin:$HOME/.local/bin:$PATH"
PROFILE

# Source it now for this session
export GUIX_PROFILE="/var/guix/profiles/per-user/root/den-profile"
export PATH="/var/guix/profiles/per-user/root/current-guix/bin:$GUIX_PROFILE/bin:$HOME/.local/bin:$PATH"
export GUIX_LOCPATH="$GUIX_PROFILE/lib/locale"

# ── Clone dotfiles ───────────────────────────────────────────────
if [ ! -d "$HOME/.dotfiles" ]; then
    echo "==> Cloning dotfiles..."
    git clone https://github.com/Diogenesoftoronto/.dotfiles.git "$HOME/.dotfiles" 2>/dev/null || \
        echo "==> Dotfiles repo not found, skipping"
fi

# ── Stow dotfiles ────────────────────────────────────────────────
if [ -d "$HOME/.dotfiles" ]; then
    echo "==> Stowing dotfiles..."
    cd "$HOME/.dotfiles"
    for pkg in fish helix zellij git jj guix ghci shell; do
        if [ -d "$pkg" ]; then
            stow -v --no-folding -t "$HOME" "$pkg" 2>/dev/null || \
                echo "==> Warning: stow $pkg had conflicts, skipping"
        fi
    done
fi

# ── Guix Home (optional, if home.scm is available) ───────────────
# Uncomment to apply full declarative home config on first boot:
# if [ -f /etc/guix/home.scm ]; then
#     echo "==> Applying guix home configuration..."
#     guix home reconfigure /etc/guix/home.scm || \
#         echo "==> Warning: guix home reconfigure failed, using stowed dotfiles"
# fi

# ── Fish shell config for Guix paths ────────────────────────────
mkdir -p "$HOME/.config/fish/conf.d"
cat > "$HOME/.config/fish/conf.d/guix.fish" << 'FISHGUIX'
# Guix paths
set -gx GUIX_PROFILE /var/guix/profiles/per-user/root/den-profile
set -gx GUIX_LOCPATH $GUIX_PROFILE/lib/locale
fish_add_path /var/guix/profiles/per-user/root/current-guix/bin
fish_add_path $GUIX_PROFILE/bin
fish_add_path $HOME/.local/bin

# Guix profile search paths (replaces `bass source $GUIX_PROFILE/etc/profile`)
if test -d $GUIX_PROFILE/lib
    set -gx LIBRARY_PATH $GUIX_PROFILE/lib $LIBRARY_PATH
    set -gx LD_LIBRARY_PATH $GUIX_PROFILE/lib $LD_LIBRARY_PATH
end
if test -d $GUIX_PROFILE/include
    set -gx C_INCLUDE_PATH $GUIX_PROFILE/include $C_INCLUDE_PATH
    set -gx CPLUS_INCLUDE_PATH $GUIX_PROFILE/include $CPLUS_INCLUDE_PATH
end
if test -d $GUIX_PROFILE/lib/pkgconfig
    set -gx PKG_CONFIG_PATH $GUIX_PROFILE/lib/pkgconfig $PKG_CONFIG_PATH
end
if test -d $GUIX_PROFILE/share/info
    set -gx INFOPATH $GUIX_PROFILE/share/info $INFOPATH
end
FISHGUIX

# ── Install crush (charmbracelet coding agent) ──────────────────
if command -v crush &>/dev/null; then
    echo "==> Crush already installed"
elif command -v go &>/dev/null; then
    echo "==> Installing crush agent via go install..."
    go install github.com/charmbracelet/crush@latest 2>/dev/null || \
        echo "==> Warning: crush install failed, install manually with: go install github.com/charmbracelet/crush@latest"
else
    echo "==> Go not found, skipping crush install (install go via guix, then: go install github.com/charmbracelet/crush@latest)"
fi

# ── Link workspace ───────────────────────────────────────────────
if [ -d /workspace ] && [ ! -L "$HOME/workspace" ]; then
    ln -sf /workspace "$HOME/workspace"
fi

# ── GitHub CLI auth ──────────────────────────────────────────────
if [ -n "${GH_TOKEN:-}" ] && command -v gh &>/dev/null; then
    echo "==> Authenticating GitHub CLI..."
    echo "$GH_TOKEN" | gh auth login --with-token 2>/dev/null || true
fi

echo "==> Bootstrap complete (Guix)!"
echo "==> guix-daemon is running — you can use guix shell, guix install, etc."
echo "==> To apply home config: guix home reconfigure /etc/guix/home.scm"
