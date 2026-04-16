# den Workflows

This guide shows common end-to-end usage patterns.

## 1. First-time setup

```bash
den setup
```

What this verifies:
- repository signals are detected and summarized
- `den.dhall` is inferred and written
- reproducible artifacts are generated from Dhall
- runtime/domain providers are only consulted when the workflow needs them

Print the inferred config without writing files:

```bash
den setup --print
```

## 2. Create a new den (Nix backend)

```bash
den spawn myproject
```

To use Railway instead of Sprite:

```bash
den spawn --runtime railway myproject
```

Then connect:

```bash
den connect myproject
```

Run a one-off command without opening a console:

```bash
den exec myproject -- pwd
```

Bind the current directory to the den:

```bash
den sprite-use myproject
```

Inspect or attach to running Sprite exec sessions:

```bash
den logs myproject --list
den logs myproject 12345
```

Restart the den without discarding the current writable overlay:

```bash
den redeploy myproject
```

## 3. Create a new den (Guix backend)

```bash
den spawn --guix myproject
```

After changing package config, recreate the runtime or use checkpoints where supported:

```bash
hx guix/manifest.scm
den redeploy myproject
```

Railway-backed dens can also be spawned with the same command surface:

```bash
den spawn --runtime railway myproject
```

## 4. Deploy a repository to a runtime

One-shot: infer config, create/reuse the selected runtime, sync sources, start the dev command:

```bash
den deploy /path/to/my-app
```

To route the same workflow through Railway:

```bash
den deploy /path/to/my-app --runtime railway
```

Prepare without starting:

```bash
den deploy /path/to/my-app --no-run
```

Override the inferred start command:

```bash
den deploy /path/to/my-app -- cargo run -- --tui
```

## 5. Day-to-day operations

List active dens:

```bash
den list
```

Add a custom domain:

```bash
den domain myproject dev.example.com
```

Canonical custom-domain note:

- `den domain` now defaults to DNS attachment.
- Domain ownership decides the provider: Cloudflare-held zones use Cloudflare, while Porkbun-held zones use sesame.
- If you need the redirect-style fallback, use `den domain myproject dev.example.com --mode forward`.

Toggle public/org-authenticated Sprite URL:

```bash
den funnel myproject        # make public
den funnel myproject --off  # revert to org-auth
```

## 6. Push-based CI deploys

For CI, do not use the long-running interactive `den deploy` execution path directly.

Preferred pattern:

```bash
den deploy /path/to/repo --name myproject --no-run
sprite -s den-myproject exec -- sh -lc 'tmux new-session -d -s myproject "cd /home/sprite/repo-* && bun install --frozen-lockfile && bun run dev"'
```

This keeps sync and process lifetime separate:

- `den deploy --no-run` handles repository sync into the selected runtime.
- `sprite exec` starts the app in a detached `tmux` session so CI can exit without killing the server.

## 7. Build a Guix image locally

```bash
den build-guix                          # from manifest
den build-guix --system                 # full Guix System image
den build-guix --push ghcr.io/you/den   # build and push to registry
```

## 8. Tear down

```bash
den destroy myproject
```

## 9. Local quality/verification loop

Python checks:

```bash
uv run mypy src
uv run pytest tests/python
```

Fast smoke tests:

```bash
bash tests/test-den.sh --no-build
```

Full checks (includes Docker build + container validation):

```bash
bash tests/test-den.sh
```

Antithesis property workload:

```bash
uv run python tests/antithesis/test_core_properties.py
```
