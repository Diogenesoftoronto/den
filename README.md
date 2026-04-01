# den

Personal cloud dev environments on Sprite/Fly with sesame-managed Porkbun domains.

Open a fully configured remote machine with fish, helix, zellij, and your dotfiles from the Sprite CLI.

Two backends: **Nix** (Determinate) or **Guix** (fully declarative Scheme).

## Quick Start

```fish
# One-time setup
den setup

# Spin up an environment (Nix backend, default)
den spawn myproject

# Or use Guix backend — everything declared in Scheme
den spawn --guix myproject

# Connect with the Sprite console
den connect myproject

# Or run a one-off command without opening a shell
den exec myproject -- pwd

# Bind the current directory to a Sprite den
den sprite-use myproject

# Inspect running Sprite exec sessions
den logs myproject --list

# Restart a den by checkpointing and restoring its current state
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

**Change packages → recreate or checkpoint:**
```fish
# Edit the manifest
hx guix/manifest.scm    # add/remove packages

# Sprite does not expose a Railway-style redeploy.
# Recreate the sprite or use checkpoints after changing image/runtime assumptions.
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

## Deploy a Repository

`den deploy` is a one-shot command that infers config, creates or reuses a
sprite, syncs the repository, and starts an inferred dev command:

```fish
# Infer everything and start the project on a sprite
den deploy /path/to/my-app

# Prepare without starting a dev command
den deploy /path/to/my-app --no-run

# Override the start command
den deploy /path/to/my-app -- cargo run -- --tui
```

## Architecture

```
Local Machine (mist)
  └── den (Typer Python CLI via uv)
        ├── Sprite CLI → creates and connects to remote environments
        └── sesame CLI → configures Porkbun URL forwarding

Sprite / Fly
  └── Dev Environment
        ├── fish + helix + zellij
        ├── Nix or Guix workflow conventions from this repo
        ├── Your dotfiles and dev tooling
        └── Optional public URL forwarded from Porkbun via sesame
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

`den domain` now makes the Sprite URL public and configures a Porkbun URL forward through `sesame`:

1. `den domain myproject dev.example.com`
2. `den` resolves the owned Porkbun zone with `sesame`
3. `den` creates a forward from your host to the Sprite URL

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Sprite CLI authenticated against Fly
- sesame CLI configured with Porkbun credentials
- For local Guix builds: `guix-daemon` running (`sudo systemctl start guix-daemon`)
- Optional: `DEN_SPRITE_ORG` to pin a Fly org for Sprite commands

## Sprite Workflow Shortcuts

- `den connect myproject` opens an interactive Sprite console
- `den exec myproject -- <cmd...>` runs a single command through `sprite exec`
- `den sprite-use myproject` binds the current directory with `sprite use`
- `den logs myproject --list` lists running Sprite exec sessions, and `den logs myproject <session>` attaches to one
- `den redeploy myproject` checkpoints the current writable state and restores it to trigger a Sprite restart

## Intelligent Setup

`den setup` now treats the current repository as the source material:

- detects common project signals such as `package.json`, `bun.lock*`, `pyproject.toml`, `Dockerfile`/`Containerfile`, `mise.toml`, `flox.toml`, and Helm charts
- infers a typed `DenConfig`
- writes `den.dhall`
- generates reproducible backend artifacts from that Dhall source of truth

Typical flow:

```bash
cd ~/code/some-project
den setup
```

Useful options:

- `den setup /path/to/repo --print` prints the inferred `den.dhall` without writing it
- `den setup /path/to/repo --force` overwrites an existing `den.dhall`

## Hello World Verification

Use this as a quick end-to-end sanity check:

```bash
bash tests/test-den.sh --no-build
bash tests/test-den.sh
```

## Python CLI + Property Tests

`den` now lives as a standalone Python project in this repo:

- Package: `src/den_cli/`
- CLI entrypoint: `den-py`
- Runtime: `uv`
- Type checking: strict `mypy`
- Property-based tests: `pytest` + `hypothesis`

Run the Python quality gates:

```bash
uv run mypy src
uv run pytest tests/python
```

There is also an Antithesis SDK workload for the pure `core.py` invariants:

```bash
uv run python tests/antithesis/test_core_properties.py
```

That workload is separate from `pytest` and is intended for Antithesis-style exploratory/property execution.

### Test coverage

| Suite | What it covers | Count |
|-------|---------------|-------|
| `test_core_properties.py` | Hypothesis property tests for name normalization, command building, project detection, Dhall rendering, domain splitting, peer extraction | 31 |
| `test_cli_commands.py` | Monkeypatched CLI integration tests for exec, sprite-use, logs, redeploy, setup, deploy | 18 |
| `test-den.sh --no-build` | Secrets safety, script syntax, fish function syntax, Python quality, Dockerfile lint, stale references | 20 |
| `test-den.sh` | Above + Docker build, tool verification, container setup, SSH config | ~30 |
| `antithesis/` | Antithesis SDK workload: 256 iterations of name/exec/domain/setup invariants + state transitions | — |

## Documentation

- Workflows: [docs/workflows.md](docs/workflows.md)
- Extending den: [docs/extending-den.md](docs/extending-den.md)
- Property-test troubleshooting: [docs/property-tests-troubleshooting.md](docs/property-tests-troubleshooting.md)
- MCP server: [docs/mcp-server.md](docs/mcp-server.md)

## Hooks + CI

Install local git hooks:

```bash
bash scripts/install-hooks.sh
```

This repo also includes GitHub Actions smoke checks in:
`/.github/workflows/smoke.yml`
