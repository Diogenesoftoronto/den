# den MCP Server

`den` ships a deep-workflow MCP server with a minimal tool surface.

Entry point:

```bash
uv run den-mcp
```

## Tool philosophy

The server intentionally exposes only three tools so a model can complete full workflows in one call:

1. `provision_den`
2. `operate_den`
3. `diagnose_den`

This favors depth over width and avoids brittle multi-call orchestration.

## Tools

## 1. `provision_den`

Purpose: one-call provisioning workflow.

Does all of this:
- preflight checks for the selected runtime and any needed domain provider
- creates a Sprite or Railway environment, depending on `runtime`
- optionally publishes a hostname using DNS attachment, which is the default
- optionally falls back to redirect-style forwarding when `domain_mode="forward"`

Important:
- domain ownership decides the domain provider: Cloudflare-held zones use Cloudflare, and Porkbun-held zones use sesame
- DNS attachment is the canonical path when the selected runtime and domain provider support it
- forwarding remains available as an explicit compatibility fallback

## 2. `operate_den`

Purpose: lifecycle operations workflow.

Supported actions:
- `list`
- `destroy`
- `domain`
- `redeploy`
- `status`

Notes:
- `destroy` requires `confirm_destroy=true`.
- `domain` requires `custom_domain`.
- `runtime` is accepted on both `provision_den` and `operate_den` so the caller can target Sprite or Railway explicitly.
- `domain_mode` defaults to DNS attachment and can be set to `forward` for the redirect-style fallback.
- `redeploy` is supported for Sprite and Railway.
- `logs` remains a CLI-oriented Sprite workflow; `operate_den` does not currently expose the interactive session behavior used by `den logs`.

## 3. `diagnose_den`

Purpose: quality and health workflow.

Runs in one call:
- `uv run mypy src`
- `uv run pytest tests/python`
- `bash tests/test-den.sh --no-build`
- optional full `bash tests/test-den.sh` when `include_docker_build=true`

## Error model

Errors are intentionally detailed and structured to maximize model debuggability.

Every workflow response includes:
- per-step command trace (`steps[]`)
- cwd, command, exit code, timeout flag, duration
- full `stdout` and `stderr`
- structured error object with remediation hints

Typical failure payload fields:
- `kind`
- `message`
- `failing_step`
- `command`
- `exit_code`
- `timed_out`
- `stdout`
- `stderr`
- `remediation[]`

## Claude Code integration

Add `den-mcp` as an MCP server in your Claude Code settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "den": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--project", "/home/diogenes/Projects/den", "den-mcp"]
    }
  }
}
```

This lets Claude Code call `provision_den`, `operate_den`, and `diagnose_den` directly.
