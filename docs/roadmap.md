# den Roadmap

Den is a self-deployable alternative to exe.dev, sprites, and shellbox. You own the stack — the Dockerfiles, the package manifests, the networking. The current model separates runtime providers (`sprite` and `railway`) from domain providers selected by ownership (`cloudflare` or `sesame`/Porkbun).

## Current State (v0.2)

**CLI commands:** `setup`, `spawn`, `deploy`, `connect`, `exec`, `sprite-use`, `list`, `status`, `logs`, `redeploy`, `destroy`, `domain`, `funnel`, `build-guix`

**Backends:** Nix (Determinate) and Guix (declarative Scheme)

**Runtime access:** Sprite console, `sprite exec`, Railway-backed runtimes, and custom hostnames attached by DNS or fallback forwarding

**Config:** Dhall type-safe config → Guix Scheme + generated deploy artifacts; Python `infer_den_setup` for zero-config repo detection

**Quality:** strict mypy, 106 pytest tests (property, CLI, and MCP coverage), Antithesis SDK workload, shell smoke suite, GitHub Actions CI

**MCP server:** `provision_den`, `operate_den`, `diagnose_den` workflows, with runtime-aware provisioning/operations

---

## Phase 1: Polish the CLI (near-term)

### Done
- [x] `den status` — Sprite presence + URL status
- [x] `den funnel` — toggle Sprite URL auth mode
- [x] `den list` — list dens in Sprite
- [x] `den exec` — run a command in a den without an interactive console (`sprite exec`)
- [x] `den sprite-use` — bind the current directory to a den via `sprite use`
- [x] `den deploy` — one-shot: infer config, create/reuse sprite, sync repo, start inferred dev command
- [x] `den logs` — list/attach to Sprite exec sessions
- [x] `den redeploy` — checkpoint + restore for restart without losing writable state
- [x] `infer_run_command` — deterministic start command inference from package.json, Cargo.toml, pyproject.toml
- [x] Python CLI with strict mypy, Hypothesis property tests, CLI integration tests, Antithesis SDK workload
- [x] GitHub Actions CI (`smoke.yml`)

### To Do
- [ ] **Richer `den list`** — show backend (nix/guix), URL, and org metadata
- [ ] **Agent pre-configuration** — ship a default agent config with den's MCP server wired in, LSP configs for common languages, and sensible defaults; copy it during bootstrap

---

## Phase 2: Public Access & Reverse Proxy

### Custom Domains
`den funnel <name> [--off]` still controls Sprite URL auth mode. `den domain <name> host.example.com` now defaults to DNS attachment and selects the domain provider by ownership:

- Cloudflare-held zones use Cloudflare for DNS management
- Porkbun-held zones use sesame for Porkbun-managed domains
- `--mode forward` keeps the redirect-style fallback available

### Caddy for HTTP Routing
For dens that serve multiple web services or need to be accessed from other machines on the tailnet (or publicly), add Caddy as a lightweight reverse proxy inside the container.

**Why Caddy:** auto-TLS, simple config, single binary, good for both tailnet-internal and public-facing use.

- [ ] **Add Caddy to both Dockerfiles** — install the binary during build
- [ ] **Default Caddyfile** — reverse proxy common dev ports (3000, 4000, 5173, 8000, 8080) on path-based or port-based routing
- [ ] **`den proxy`** — CLI command to configure Caddy routes on a running den (SSH in and update Caddyfile)
- [ ] **Sprite URL + Caddy** — expose one service cleanly behind the Sprite URL and optional forwarding or DNS attachment

### Use Cases
- You're on your phone and want to check a running web app on your den → Sprite URL + Caddy
- You want a friendly host name on a Cloudflare zone → native DNS attachment
- You want a friendly host name on a Porkbun zone → sesame-managed DNS or forwarding, depending on the chosen mode
- You want to share a prototype publicly → make the runtime public, then attach the hostname or fall back to forwarding

---

## Phase 3: Cloud-Agnostic Layer

Sprite/Fly and Railway are the current runtime providers. The goal is to keep runtime concerns isolated so den can target multiple backends and multiple domain authorities.

### Abstraction
- [ ] **Provider interface** — define the minimal operations: create environment, open console, expose URL, add domain, get status, destroy
- [ ] **Sprite provider** — wrap current Sprite CLI calls behind the interface
- [ ] **Railway provider** — use Railway primitives directly for runtime lifecycle and hostname attachment
- [ ] **Fly provider** — use native Fly primitives directly where Sprite is insufficient
- [ ] **Hetzner provider** — for cheap, long-running dens on bare metal VPS
- [ ] **Local Docker provider** — for testing and offline use (`docker compose` with the same Dockerfiles)

### Config
The Dhall layer generates deploy artifacts via `generate-from-dhall.sh`. Extend to add `generate-fly.dhall`, `generate-compose.dhall`, etc. for new providers.

---

## Phase 4: Agent Integration (deep)

Den environments should work seamlessly with coding agents (Claude Code, Crush, etc.):

- [ ] **Ship agent config** — pre-configured with:
  - den MCP server (`den-mcp` over stdio)
  - LSP configs for Python, Go, TypeScript, Rust (common den languages)
  - Sensible permission defaults
- [ ] **`den agent`** — SSH into a den and launch an agent session directly
- [ ] **Agent-as-entrypoint mode** — optional `DEN_MODE=agent` env var that boots the den headless and runs an agent in a loop, accepting work via MCP. This turns a den into an autonomous coding agent.
- [ ] **Den MCP server in Claude Code** — configure `den-mcp` as an MCP server for Claude Code so provisioning/operations can be driven from the local terminal

---

## Phase 5: TUI & GUI

CLI is the foundation. TUI and GUI are additive layers on top.

### TUI (Bubble Tea)
- [ ] **`den tui`** — full-screen terminal interface built with Bubble Tea (charmbracelet/bubbletea)
  - List dens with live status updates
  - Spawn/destroy with confirmation prompts
  - Tail logs in a pane
  - Quick-connect to a den
  - Funnel toggle
- [ ] **Integrate with Crush** — TUI could embed or launch crush sessions

### GUI (later)
- [ ] **Web dashboard** — simple status page served from your local machine or a den itself
- [ ] **Desktop app** — Tauri or similar, wrapping the TUI or web dashboard

---

## Phase 6: Multi-User & Teams (future)

Den is currently single-user by design. If there's demand:

- [ ] **Shared tailnets** — multiple users on the same tailnet can see and connect to shared dens
- [ ] **ACL-based access** — Tailscale ACL tags (`tag:den-readonly`, `tag:den-admin`) for fine-grained access
- [ ] **Team configs** — shared Dhall configs in a team repo, each member spawns their own den from the same spec

---

## Architecture Diagram

```
You (any machine)
  └── den CLI (Python/Typer via uv)
        ├── spawn/deploy/connect/exec/status/funnel/...
        ├── Dhall configs → Guix Scheme + deploy config
        ├── Domain provider → Cloudflare or sesame/Porkbun, selected by ownership
        └── Runtime provider → Sprite/Fly or Railway
              └── Container (Fedora 42)
                    ├── Nix or Guix (with daemon)
                    ├── Caddy (reverse proxy) [planned]
                    ├── SSH server
                    ├── Your dotfiles (stowed)
                    └── /workspace (persistent volume)
```

## Principles

1. **You own it.** No vendor lock-in on the environment itself. The Dockerfiles, manifests, and configs are yours.
2. **Declarative when possible.** Guix manifests, Dhall types, and generated configs over imperative scripts.
3. **CLI first.** Every operation works headless from any terminal. TUI/GUI are optional layers.
4. **One command away.** `den spawn`, `den connect`, `den destroy`. No YAML sprawl.
5. **Agent-ready.** Crush is a first-class citizen, not an afterthought.
