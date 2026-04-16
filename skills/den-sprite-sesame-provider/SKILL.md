---
name: den-sprite-sesame-provider
description: Maintain den when provisioning and lifecycle flows use the Sprite CLI on Fly and custom domains are managed through sesame on Porkbun. Use when changing Sprite-backed `den` workflows, custom-domain forwarding, provider-specific docs, or tests that depend on Sprite URLs and Porkbun forwarding behavior.
---

# Den Sprite Sesame Provider

Use this skill when den should behave as a Sprite-backed environment manager instead of a Railway-backed deploy tool.

## Workflow

1. Inspect [crates/den-cli/src/main.rs](../../crates/den-cli/src/main.rs), [crates/den-core/src/sprite.rs](../../crates/den-core/src/sprite.rs), [crates/den-core/src/porkbun.rs](../../crates/den-core/src/porkbun.rs), and [crates/den-mcp/src/tools.rs](../../crates/den-mcp/src/tools.rs) before editing.
2. Keep shared provider logic in `den-core` when it is reused by both CLI and MCP code.
3. Prefer the actual installed CLIs for behavior discovery:
   - `sprite --help`
   - `sprite url --help`
   - `sprite create --help`
   - `sesame --help`
4. Validate with:
   - `cargo test -p den-cli`
   - `cargo check -p den-mcp`
   - `uv run pytest tests/python` when parity coverage needs updating
5. Update docs only after the runtime code and tests are coherent.
6. For non-interactive deploy automation, prefer `den deploy --no-run` plus a detached remote process launcher such as `tmux`; the interactive `den deploy` run path is for live sessions, not CI.

## Provider Rules

- Treat Sprite as the source of truth for environment lifecycle.
- Use shared Sprite helpers from `den-core` instead of rebuilding org or sprite flags ad hoc.
- Do not assume Sprite supports Railway-style `redeploy`, `logs`, env var mutation, or volume management unless the installed CLI confirms it.
- If a Railway capability has no Sprite equivalent, return or raise an explicit unsupported-action message instead of inventing behavior.
- If repository sync is involved, verify it against the real Sprite CLI. `sprite exec --file` is not a safe assumption for production sync behavior.

## Domain Rules

- Resolve the sesame binary through the shared Rust helper path or the real installed CLI.
- Use the shared Sprite URL parser to extract the public URL from CLI output.
- Use `split_custom_domain(...)` before building Porkbun commands so owned zones like `dev.example.com` are preferred over naive last-two-label splitting.
- Current domain behavior is URL forwarding through sesame, not native Fly certificate/domain attachment.
- If the domain action requires public access, set Sprite URL auth to `public` first and only then add the Porkbun forward.
- Do not claim a custom domain is canonical HTTPS unless the DNS points at the Sprite/Fly edge and the edge certificate for that hostname is provisioned. A Porkbun URL forward is still a redirect.
- For apex-domain cutovers, separate the concerns explicitly:
  - edge certificate/domain attachment
  - DNS ALIAS/CNAME move away from Porkbun forward hosts
  - app-level host allowance

## Test Guidance

- Keep property tests provider-agnostic unless a provider-specific helper is under test.
- For Sprite URL tests, restrict generated names to hostname-safe characters.
- When changing domain parsing, add tests for:
  - apex domains
  - nested owned zones
  - fallback to the registrable-looking suffix

## Files To Check

- [crates/den-cli/src/main.rs](../../crates/den-cli/src/main.rs)
- [crates/den-core/src/sprite.rs](../../crates/den-core/src/sprite.rs)
- [crates/den-core/src/porkbun.rs](../../crates/den-core/src/porkbun.rs)
- [crates/den-mcp/src/tools.rs](../../crates/den-mcp/src/tools.rs)
- [tests/python/test_core_properties.py](../../tests/python/test_core_properties.py)
- [README.md](../../README.md)
- [docs/mcp-server.md](../../docs/mcp-server.md)
- [docs/workflows.md](../../docs/workflows.md)
