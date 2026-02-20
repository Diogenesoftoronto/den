# devbox

Personal cloud dev environments on Railway + Tailscale.

SSH into a fully configured machine with fish, helix, zellij, nix, and your dotfiles — anywhere, instantly.

## Quick Start

```fish
# One-time setup
devbox setup

# Spin up an environment
devbox spawn myproject

# Connect (via Tailscale SSH — no keys needed)
devbox connect myproject

# Add a custom domain for web services
devbox domain myproject dev.example.com

# Done working
devbox destroy myproject
```

## Architecture

```
Local Machine (mist)
  └── devbox.fish CLI
        ├── Railway CLI → deploys container
        └── Tailscale → SSH via WireGuard mesh

Railway
  └── Dev Container (Fedora 42)
        ├── fish + helix + zellij + nix + mise
        ├── Your dotfiles (auto-stowed)
        ├── Tailscale SSH (keyless auth)
        ├── /workspace volume (persistent)
        └── Custom domains + auto-SSL
```

## What's Inside the Container

| Tool | Version |
|------|---------|
| Fish shell | Latest (Fedora 42) |
| Helix editor | Latest (COPR) |
| Zellij | Latest |
| Git + Jujutsu | Latest |
| GitHub CLI | Latest |
| Nix (Determinate) | Latest |
| mise | Latest |
| fzf, ripgrep, fd, bat | Latest |

## Custom Domains

Railway provides custom domains with automatic Let's Encrypt SSL:

1. Run `devbox domain myproject dev.example.com`
2. Add the CNAME record to your DNS
3. Railway auto-provisions SSL

Your dev servers (port 3000, 8080, etc.) are accessible at `https://dev.example.com`.

## Prerequisites

- [Railway account](https://railway.com)
- [Tailscale account](https://tailscale.com) with SSH enabled
- Tailscale auth key (reusable, ephemeral, tagged `tag:devbox`)
