# den

Personal cloud dev environments on Railway + Tailscale.

SSH into a fully configured machine with fish, helix, zellij, and your dotfiles — anywhere, instantly.

Two backends: **Nix** (Determinate) or **Guix** (fully declarative Scheme).

## Quick Start

```fish
# One-time setup
den setup

# Spin up an environment (Nix backend, default)
den spawn myproject

# Or use Guix backend — everything declared in Scheme
den spawn --guix myproject

# Connect (via Tailscale SSH — no keys needed, agent forwarding enabled)
den connect myproject

# Redeploy after editing configs
den redeploy myproject

# Add a custom domain for web services
den domain myproject dev.example.com

# Done working
den destroy myproject
```

## Backends

### Nix (default)

Uses `Dockerfile` with Fedora 42 + Determinate Nix + mise.

### Guix (declarative)

Uses `Dockerfile.guix` with Fedora 42 + GNU Guix. The entire package set is
defined in Scheme:

```
guix/
├── channels.scm     # Package sources (guix + nonguix + tailscale)
├── manifest.scm     # Package list — edit this to change what's installed
├── home.scm         # User environment (shell, env vars, dotfiles)
└── system.scm       # Full OS config (for local guix system image builds)
```

**Change packages → redeploy:**
```fish
# Edit the manifest
hx guix/manifest.scm    # add/remove packages

# Redeploy
den redeploy myproject
```

**Runtime Guix inside the container:**
```bash
# guix-daemon runs in the container, so you can:
guix shell python node       # ephemeral dev shell
guix install duckdb          # persistent install
guix home reconfigure /etc/guix/home.scm  # apply home config
guix pack -f docker -m manifest.scm       # build images inside images
```

**Pin channels for reproducibility:**
```bash
guix time-machine -C channels.scm -- describe -f channels > channels-lock.scm
```

**Local build (most reproducible):**
```fish
# Build Docker image using your local Guix (bit-for-bit reproducible)
den build-guix                          # from manifest
den build-guix --system                 # full Guix System image
den build-guix --push ghcr.io/you/den   # build and push to registry
```

## Architecture

```
Local Machine (mist)
  └── den.fish CLI
        ├── Railway CLI → deploys container
        └── Tailscale → SSH via WireGuard mesh

Railway
  └── Dev Container (Fedora 42)
        ├── fish + helix + zellij
        ├── Nix or Guix (with daemon running)
        ├── Your dotfiles (auto-stowed)
        ├── Tailscale SSH (keyless auth)
        ├── /workspace volume (persistent)
        └── Custom domains + auto-SSL
```

## What's Inside

| Tool | Nix | Guix |
|------|-----|------|
| Fish shell | ✓ (dnf) | ✓ (guix) |
| Helix editor | ✓ (COPR) | ✓ (guix) |
| Zellij | ✓ (binary) | ✓ (guix) |
| Git + Jujutsu | ✓ | ✓ |
| GitHub CLI | ✓ | ✓ |
| Package manager daemon | nix-daemon | guix-daemon |
| fzf, ripgrep, fd, bat | ✓ | ✓ |
| mise | ✓ | ✓ |
| Runtime packages | `nix shell` | `guix shell` |

## Custom Domains

Railway provides custom domains with automatic Let's Encrypt SSL:

1. `den domain myproject dev.example.com`
2. Add the CNAME record to your DNS
3. Railway auto-provisions SSL

## Prerequisites

- [Railway account](https://railway.com) + CLI (`mise install railway`)
- [Tailscale account](https://tailscale.com) with SSH enabled
- Tailscale auth key (reusable, ephemeral, tagged `tag:den`)
- For local Guix builds: `guix-daemon` running (`sudo systemctl start guix-daemon`)
- Optional: `sops` + `age` for encrypted Tailscale auth key at `~/.config/sops/den-secrets.yaml`
