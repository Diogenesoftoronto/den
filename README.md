# den

Personal cloud dev environments with runtime providers for Sprite/Fly and Railway, plus domain providers selected by ownership.

Open a fully configured remote machine with fish, helix, zellij, and your dotfiles from the `den` CLI.

Two backends: **Nix** (Determinate) or **Guix** (fully declarative Scheme).

## Installation

The main CLI in this repo is the Rust `den` binary. Install it from this checkout:

```bash
git clone https://github.com/diogenesoftoronto/den
cd den
cargo install --path crates/den-cli
```

That installs `den` into `~/.cargo/bin`. Make sure that directory is on your `PATH`.

Verify the install:

```bash
den doctor
```

Optional companion binaries:

```bash
# MCP server binary
cargo install --path crates/den-mcp

# Python implementation and tests
uv sync --dev
uv run den-py --help
uv run den-mcp --help
```

If you do not already have the toolchains:

- Install Rust with `rustup`
- Install Python 3.12+
- Install `uv`: https://docs.astral.sh/uv/

## Documentation

- [Workflow reference](docs/workflows.md)
- [MCP server](docs/mcp-server.md)
- [Telemetry posture](docs/telemetry.md)
- [Self-hosted runtime](docs/selfhosted-runtime.md)

## Quick Start

```fish
# One-time setup
den setup

# Spin up an environment (Nix backend, default runtime provider)
den spawn myproject

# Or use Guix backend — everything declared in Scheme
den spawn --guix myproject

# Or target Railway instead of Sprite
den spawn --runtime railway myproject

# Connect with the Sprite console
den connect myproject

# Or run a one-off command without opening a shell
den exec myproject -- pwd

# Bind the current directory to a den
den sprite-use myproject

# Inspect running Sprite exec sessions
den logs myproject --list

# Restart a den by checkpointing and restoring its current state
den redeploy myproject

# Add a custom domain for web services; dns is the default mode
den domain myproject dev.example.com

# Explicit forwarding fallback
den domain myproject dev.example.com --mode forward

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

`den deploy` is a one-shot command that infers config, creates or reuses the
selected runtime provider, syncs the repository, and starts an inferred dev command:

```fish
# Infer everything and start the project on the default runtime provider
den deploy /path/to/my-app

# Prepare without starting a dev command
den deploy /path/to/my-app --no-run

# Route the same flow through Railway
den deploy /path/to/my-app --runtime railway

# Override the start command
den deploy /path/to/my-app -- cargo run -- --tui
```

## Architecture

```
Local Machine (mist)
  └── den (Rust CLI)
        ├── Runtime providers → Sprite/Fly or Railway
        └── Domain providers → Cloudflare or sesame/Porkbun, selected by ownership

Sprite / Fly or Railway
  └── Dev Environment
        ├── fish + helix + zellij
        ├── Nix or Guix workflow conventions from this repo
        ├── Your dotfiles and dev tooling
        └── Optional custom hostname attached via DNS, or forwarded as a fallback
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

`den domain` now chooses the domain provider by ownership and defaults to native DNS attachment:

1. `den domain myproject dev.example.com`
2. `den` resolves the owned zone from Cloudflare or sesame/Porkbun
3. `den` attaches the hostname to the selected runtime provider and publishes the matching DNS records

If you need the legacy redirect-style behavior, use:

```fish
den domain myproject dev.example.com --mode forward
```

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Sprite CLI authenticated against Fly
- Railway CLI authenticated against your Railway account if you plan to use `--runtime railway`
- sesame CLI configured with Porkbun credentials if you plan to manage Porkbun-held domains
- Cloudflare API access if you plan to manage Cloudflare-held domains
- For local Guix builds: `guix-daemon` running (`sudo systemctl start guix-daemon`)
- Optional: `DEN_SPRITE_ORG` to pin a Fly org for Sprite commands

## Runtime Workflow Shortcuts

- `den connect myproject` opens an interactive Sprite console
- `den exec myproject -- <cmd...>` runs a single command through `sprite exec`
- `den spawn --runtime railway myproject` creates a Railway-backed runtime instead of a Sprite-backed one
- `den deploy /path/to/my-app --runtime railway` routes the one-shot deploy through Railway instead of Sprite
- `den domain myproject dev.example.com` uses ownership-based domain selection and defaults to DNS attachment
- `den domain myproject dev.example.com --mode forward` keeps the redirect-style fallback available
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

## Python Reference + Property Tests

The repo still includes the earlier Python implementation as a reference surface and test target:

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
| `test_core_properties.py` | Hypothesis property tests for name normalization, command building, project detection, Dhall rendering, domain resolution, Railway helpers, peer extraction | 47 |
| `test_cli_commands.py` | Monkeypatched CLI integration tests for exec, sprite-use, logs, redeploy, setup, deploy, runtime-aware list/status/destroy flows | 36 |
| `test_mcp_server.py` | MCP workflow tests for provision/operate flows, including runtime-aware Railway lifecycle and DNS attach branches | 23 |
| `test-den.sh --no-build` | Secrets safety, script syntax, fish function syntax, Python quality, Dockerfile lint, stale references | 20 |
| `test-den.sh` | Above + Docker build, tool verification, container setup, SSH config | ~30 |
| `antithesis/` | Antithesis SDK workload: 256 iterations of name/exec/domain/setup invariants + state transitions | — |

## Documentation

- Workflows: [docs/workflows.md](docs/workflows.md)
- Extending den: [docs/extending-den.md](docs/extending-den.md)
- Property-test troubleshooting: [docs/property-tests-troubleshooting.md](docs/property-tests-troubleshooting.md)
- MCP server: [docs/mcp-server.md](docs/mcp-server.md)
- Telemetry posture: [docs/telemetry.md](docs/telemetry.md)

## Hooks + CI

Install local git hooks:

```bash
bash scripts/install-hooks.sh
```

This repo also includes GitHub Actions smoke checks in:
`/.github/workflows/smoke.yml`
