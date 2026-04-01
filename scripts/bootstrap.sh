#!/usr/bin/env bash
set -euo pipefail

echo "==> Bootstrapping den user environment..."

# Clone dotfiles if not present
if [ ! -d "$HOME/.dotfiles" ]; then
    echo "==> Cloning dotfiles..."
    git clone https://github.com/Diogenesoftoronto/.dotfiles.git "$HOME/.dotfiles" 2>/dev/null || \
        echo "==> Dotfiles repo not found, skipping"
fi

# Stow dotfiles packages
if [ -d "$HOME/.dotfiles" ]; then
    echo "==> Stowing dotfiles..."
    cd "$HOME/.dotfiles"
    for pkg in fish helix zellij git jj mise ghci shell; do
        if [ -d "$pkg" ]; then
            stow -v --no-folding -t "$HOME" "$pkg" 2>/dev/null || \
                echo "==> Warning: stow $pkg had conflicts, skipping"
        fi
    done
fi

# Set up mise tools
if command -v mise &>/dev/null; then
    echo "==> Installing mise tools..."
    mise install 2>/dev/null || echo "==> Some mise tools failed, continuing"
fi

# Install crush (charmbracelet coding agent)
if command -v crush &>/dev/null; then
    echo "==> Crush already installed"
elif command -v go &>/dev/null; then
    echo "==> Installing crush agent via go install..."
    go install github.com/charmbracelet/crush@latest 2>/dev/null || \
        echo "==> Warning: crush install failed, install manually with: go install github.com/charmbracelet/crush@latest"
else
    echo "==> Go not found, skipping crush install (install go via mise, then: go install github.com/charmbracelet/crush@latest)"
fi

# Link workspace to home
if [ -d /workspace ] && [ ! -L "$HOME/workspace" ]; then
    ln -sf /workspace "$HOME/workspace"
fi

# Set up fish as login shell (already set in useradd)
echo "==> Setting fish shell..."
mkdir -p "$HOME/.config/fish"

# gh auth if token provided
if [ -n "${GH_TOKEN:-}" ]; then
    echo "==> Authenticating GitHub CLI..."
    echo "$GH_TOKEN" | gh auth login --with-token 2>/dev/null || true
fi

echo "==> Bootstrap complete!"
