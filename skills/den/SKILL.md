---
name: den
description: Work on the Rust-canonical den CLI and MCP server for provisioning, deployment, lifecycle, and custom-domain flows across Sprite, Railway, Cloudflare, and sesame/Porkbun. Use when changing `den` commands, `den-mcp` workflows, runtime or domain provider dispatch, the self-hosted runtime design, or tests and docs that describe the Rust CLI and MCP behavior.
---

# Den

Use this skill when a task touches den's Rust CLI, Rust MCP server, runtime providers, or custom-domain automation.

## Workflow

1. Inspect [crates/den-cli/src/main.rs](../../crates/den-cli/src/main.rs), [crates/den-cli/src/lib.rs](../../crates/den-cli/src/lib.rs), [crates/den-core/src/lib.rs](../../crates/den-core/src/lib.rs), and [crates/den-mcp/src/tools.rs](../../crates/den-mcp/src/tools.rs) before editing.
2. Keep reusable parsing, command-building, provider selection, and Dhall helpers in `den-core` where possible.
3. Keep CLI UX, prompts, output, and asset resolution in `den-cli`.
4. Keep MCP workflows in [crates/den-mcp/src/tools.rs](../../crates/den-mcp/src/tools.rs) structured, step-oriented, and minimal-call.
5. Validate with:
   - `cargo test -p den-cli`
   - `cargo check -p den-mcp`
   - `cargo check -p den-cli`
   - `uv run pytest tests/python` when changing the legacy Python reference implementation or parity tests
   - `bash tests/test-den.sh` when shell-smoke coverage matters
6. Update docs after code and tests agree.

## Interface Rules

- CLI and MCP should expose the same underlying capability set unless an interface difference is intentional.
- If a feature exists in both CLI and MCP, prefer one shared helper in `den-core` instead of duplicating provider logic.
- MCP errors should return explicit remediation instead of vague provider failures.
- Do not invent provider capabilities. If Sprite or Railway cannot do something, return an explicit unsupported path.

## Provider Rules

- Runtime provider is either `sprite` or `railway`.
- Domain provider is selected by ownership, not by preference: Cloudflare-held zones use Cloudflare and Porkbun-held zones use sesame.
- Use `resolve_custom_domain(...)` from `den-core` to choose the owning provider.
- For Railway custom domains, use Railway's attach response as the source of truth for required DNS records.
- For Sprite URL forwarding, make the Sprite URL public before creating the Porkbun forward.
- Keep forwarding and native DNS semantics separate. A forward is a redirect, not canonical edge attachment.

## MCP Rules

- Use the Rust `den-mcp` workflow tools for create, lifecycle, and diagnostics flows.
- Prefer the fewest MCP tool calls that satisfy the task.
- Keep MCP workflow behavior aligned with the Rust CLI surface, not the legacy Python CLI.

## CLI Examples

```bash
den spawn myproject
den spawn myproject --runtime railway
den deploy . --runtime railway
den doctor --verify-auth
den domain myproject app.example.com --runtime railway --mode dns --port 3000
den domain myproject app.dev.example.com --mode forward
den list --runtime railway --json
den status myproject --runtime railway
```

## Tests To Update

- [crates/den-cli/tests/assets_and_cli.rs](../../crates/den-cli/tests/assets_and_cli.rs) for Rust CLI flags and install-health coverage
- [crates/den-core/tests/core_properties.rs](../../crates/den-core/tests/core_properties.rs) for parsing, provider selection, and command builders
- [tests/python/test_core_properties.py](../../tests/python/test_core_properties.py) for parsing, provider selection, and command builders
- [tests/python/test_cli_commands.py](../../tests/python/test_cli_commands.py) for CLI behavior and provider dispatch
- [tests/python/test_mcp_server.py](../../tests/python/test_mcp_server.py) for MCP workflows and error payloads

## Files To Check

- [crates/den-cli/src/main.rs](../../crates/den-cli/src/main.rs)
- [crates/den-cli/src/lib.rs](../../crates/den-cli/src/lib.rs)
- [crates/den-core/src/lib.rs](../../crates/den-core/src/lib.rs)
- [crates/den-mcp/src/tools.rs](../../crates/den-mcp/src/tools.rs)
- [crates/den-core/tests/core_properties.rs](../../crates/den-core/tests/core_properties.rs)
- [README.md](../../README.md)
- [docs/mcp-server.md](../../docs/mcp-server.md)
- [docs/workflows.md](../../docs/workflows.md)
- [docs/selfhosted-runtime.md](../../docs/selfhosted-runtime.md)
