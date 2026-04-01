from __future__ import annotations

import json
import shlex
import subprocess
import tarfile
import tempfile
import time
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final

import typer

from den_cli.core import (
    discover_porkbun_domains_from_sesame_config,
    detect_project_markers,
    find_checkpoint_version_in_api_output,
    find_checkpoint_version_in_list_output,
    infer_den_setup,
    infer_run_command,
    make_sprite_redeploy_comment,
    normalize_den_name,
    parse_sprite_url,
    parse_sprite_url_info,
    render_den_dhall,
    resolve_sesame_command,
    short_den_name,
    split_custom_domain,
    sprite_checkpoint_create_command,
    sprite_command,
    sprite_exec_command,
    sprite_logs_command,
    sprite_restore_command,
    sprite_use_command,
)

APP_NAME: Final[str] = "den"
PROJECT_DIR: Final[Path] = Path.home() / "Projects" / "den"
DHALL_DIR: Final[Path] = PROJECT_DIR / "dhall"
SECRETS_FILE: Final[Path] = Path.home() / ".config" / "sops" / "den-secrets.yaml"

app = typer.Typer(
    name=APP_NAME,
    no_args_is_help=True,
    add_completion=False,
    help="Remote dev environments (Sprite/Fly + sesame/Porkbun)",
)


class Backend(StrEnum):
    nix = "nix"
    guix = "guix"


class CommandError(RuntimeError):
    pass


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    capture_output: bool = False,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        input=input_text,
        capture_output=capture_output,
        check=False,
    )


def _run_checked(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    capture_output: bool = False,
    error_hint: str | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = _run(cmd, cwd=cwd, capture_output=capture_output, input_text=input_text)
    if proc.returncode != 0:
        if error_hint:
            typer.secho(error_hint, fg=typer.colors.RED)
        if proc.stderr:
            typer.echo(proc.stderr.strip())
        if proc.stdout and not proc.stderr:
            typer.echo(proc.stdout.strip())
        raise CommandError(f"command failed: {' '.join(cmd)}")
    return proc


def _command_exists(name: str) -> bool:
    return _run(["bash", "-lc", f"command -v {name}"], capture_output=True).returncode == 0


def _ensure_project_dir() -> None:
    if not PROJECT_DIR.is_dir():
        raise CommandError(f"den project not found at {PROJECT_DIR}")


def _list_den_names() -> list[str]:
    proc = _run_checked(sprite_command("list", "-prefix", "den-"), capture_output=True)
    names = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return [name for name in names if name.startswith("den-")]


def _choose_den_name(prompt: str) -> str:
    names = _list_den_names()
    if not names:
        raise CommandError("No Sprite-backed dens found")

    typer.echo("Available dens:")
    for name in names:
        typer.echo(f"  {name}")

    selected = typer.prompt(prompt, default=names[0])
    if not selected.strip():
        raise CommandError("Cancelled")
    return normalize_den_name(selected.strip())


def _sprite_exists(name: str) -> bool:
    """Return whether the target sprite already exists in the current org."""

    den_name = normalize_den_name(name)
    return den_name in _list_den_names()


def _create_sprite(name: str) -> None:
    """Create a sprite without opening an interactive console session."""

    den_name = normalize_den_name(name)
    _run_checked(
        sprite_command("create", den_name, "--skip-console"),
        cwd=PROJECT_DIR,
        error_hint="Sprite create failed.",
    )


def _should_bundle_path(path: Path) -> bool:
    """Return whether a repository path should be copied into the sprite bundle."""

    ignored_names = {".git", ".jj", ".direnv", ".venv", "node_modules", "target", "__pycache__"}
    ignored_suffixes = {".pyc", ".pyo"}
    if path.name in ignored_names:
        return False
    if path.suffix in ignored_suffixes:
        return False
    return True


def _sync_repo_to_sprite(name: str, repo_dir: Path) -> str:
    """Upload the local repository snapshot into the sprite and return its remote path."""

    den_name = normalize_den_name(name)
    nonce = str(time.time_ns())
    remote_dir = f"/home/sprite/{repo_dir.name}-{nonce}"
    with tempfile.TemporaryDirectory(prefix="den-sync-") as tmp_dir:
        archive_path = Path(tmp_dir) / f"{repo_dir.name}.tar"
        with tarfile.open(archive_path, "w") as archive:
            for candidate in sorted(repo_dir.rglob("*")):
                if not candidate.exists() or not _should_bundle_path(candidate):
                    continue
                relative = candidate.relative_to(repo_dir)
                if any(not _should_bundle_path(Path(part)) for part in relative.parts):
                    continue
                archive.add(candidate, arcname=Path(repo_dir.name) / relative, recursive=False)

        remote_archive = f"/tmp/{repo_dir.name}-{nonce}.tar"
        unpack_command = (
            f"mkdir -p {shlex.quote(remote_dir)} "
            f"&& tar -xf {shlex.quote(remote_archive)} -C {shlex.quote(remote_dir)} --strip-components=1"
        )
        _run_checked(
            sprite_command(
                "exec",
                "--file",
                f"{archive_path}:{remote_archive}",
                "--",
                "sh",
                "-lc",
                unpack_command,
                sprite_name=den_name,
            ),
            error_hint="Sprite source sync failed.",
        )
    return remote_dir


def _sesame_command() -> list[str]:
    try:
        return resolve_sesame_command()
    except FileNotFoundError as exc:
        raise CommandError(str(exc)) from exc


def _owned_porkbun_domains() -> list[str]:
    proc = _run(_sesame_command() + ["domain", "list", "--all", "--json"], capture_output=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        return discover_porkbun_domains_from_sesame_config()
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return discover_porkbun_domains_from_sesame_config()
    if not isinstance(payload, list):
        return discover_porkbun_domains_from_sesame_config()

    domains: list[str] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        domain = row.get("domain")
        if isinstance(domain, str) and domain:
            domains.append(domain)
    return domains or discover_porkbun_domains_from_sesame_config()


def _sprite_url(den_name: str) -> str:
    proc = _run_checked(sprite_command("url", sprite_name=den_name), capture_output=True)
    url = parse_sprite_url(proc.stdout)
    if not url:
        raise CommandError(f"Could not parse sprite URL for {den_name}")
    return url


def _attach_custom_domain(den_name: str, host: str) -> str:
    _run_checked(
        sprite_command("url", "update", "--auth", "public", sprite_name=den_name),
        capture_output=True,
        error_hint="Failed to make the sprite URL public.",
    )
    target_url = _sprite_url(den_name)
    zone, subdomain = split_custom_domain(host, owned_domains=_owned_porkbun_domains())
    command = _sesame_command() + [
        "domain",
        "add-url-forward",
        zone,
        "--location",
        target_url,
        "--type",
        "permanent",
        "--include-path",
        "yes",
    ]
    if subdomain:
        command.extend(["--subdomain", subdomain])
    _run_checked(command, error_hint="Failed to create Porkbun URL forward via sesame.")
    return target_url


@app.command()
def setup(
    path: Annotated[Path, typer.Argument(help="Repository path to inspect")] = Path("."),
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing den.dhall")] = False,
    print_only: Annotated[bool, typer.Option("--print", help="Print inferred den.dhall instead of writing files")] = False,
) -> None:
    """Infer `den.dhall` from a repository and generate reproducible artifacts.

    The command inspects common project markers, chooses a backend heuristic,
    writes the inferred Dhall config, and then runs the Dhall generator script
    to materialize backend-specific files in the target repository.
    """
    repo_dir = path.resolve()
    if not repo_dir.is_dir():
        raise CommandError(f"Repository path not found: {repo_dir}")
    if not DHALL_DIR.is_dir():
        raise CommandError(f"Dhall templates not found at {DHALL_DIR}")

    typer.secho(f"==> den setup {repo_dir}", fg=typer.colors.CYAN)

    inferred = infer_den_setup(repo_dir)
    markers = detect_project_markers(repo_dir)
    rendered = render_den_dhall(inferred, DHALL_DIR)

    typer.echo(f"  Name:       {inferred.name}")
    typer.echo(f"  Backend:    {inferred.backend}")
    typer.echo(f"  Dockerfile: {inferred.dockerfile or 'default'}")
    typer.echo("  Signals:")
    if inferred.reasons:
        for reason in inferred.reasons:
            typer.echo(f"    - {reason}")
    else:
        typer.echo("    - no strong signals detected")

    detected_markers = {
        "package.json": markers.has_package_json,
        "bun.lock": markers.has_bun_lock,
        "pyproject.toml": markers.has_pyproject,
        "Cargo.toml": markers.has_cargo_toml,
        "Dockerfile/Containerfile": markers.has_dockerfile or markers.has_containerfile,
        "mise.toml": markers.has_mise_toml,
        "flox.toml": markers.has_flox_toml,
        "Helm chart": markers.has_helm_chart,
        "Guix manifest": markers.has_guix_manifest or markers.has_guix_channels,
        "Nix metadata": markers.has_nix_flake or markers.has_shell_nix,
    }
    for label, present in detected_markers.items():
        if present:
            typer.echo(f"    - detected {label}")

    if print_only:
        typer.echo()
        typer.echo(rendered)
        return

    den_file = repo_dir / "den.dhall"
    if den_file.exists() and not force:
        raise CommandError(f"{den_file} already exists. Re-run with --force to overwrite it.")

    den_file.write_text(rendered)
    typer.secho(f"OK Wrote {den_file}", fg=typer.colors.GREEN)

    if _command_exists("sprite"):
        version_proc = _run(["sprite", "--help"], capture_output=True)
        first_line = version_proc.stdout.splitlines()[0] if version_proc.stdout else "sprite available"
        typer.secho(f"OK {first_line}", fg=typer.colors.GREEN)
    else:
        typer.echo("NOTE Sprite CLI not found; setup still generated Dhall config.")

    try:
        sesame_cmd = _sesame_command()
    except CommandError:
        typer.echo("NOTE sesame not found; continuing without domain automation checks.")
    else:
        _run_checked(sesame_cmd + ["--help"], capture_output=True)
        typer.secho("OK sesame available", fg=typer.colors.GREEN)

    _run_checked(
        ["bash", str(PROJECT_DIR / "scripts" / "generate-from-dhall.sh"), str(den_file), str(repo_dir)],
        error_hint="Dhall generation failed.",
    )
    typer.secho("OK Generated reproducible artifacts from den.dhall", fg=typer.colors.GREEN)


@app.command()
def spawn(
    name: Annotated[str | None, typer.Argument(help="Den name, e.g. myproject")] = None,
    guix: Annotated[bool, typer.Option("--guix", help="Use Guix backend")] = False,
) -> None:
    """Create a new den environment."""
    _ensure_project_dir()

    den_input = name or typer.prompt("Den name")
    den_input = den_input.strip()
    if not den_input:
        raise CommandError("Cancelled")

    den_name = normalize_den_name(den_input)
    backend = Backend.guix if guix else Backend.nix
    typer.secho(f"==> Spawning {den_name} ({backend.value})", fg=typer.colors.CYAN)
    _create_sprite(den_name)

    short_name = short_den_name(den_name)
    typer.echo()
    typer.secho(f"OK {den_name} created in Sprite", fg=typer.colors.GREEN)
    typer.echo("  Backend selection is recorded locally; Sprite owns the runtime image.")
    typer.echo(f"  Connect:    den connect {short_name}")
    typer.echo(f"  Status:     den status {short_name}")
    typer.echo(f"  Domain:     den domain {short_name} dev.example.com")


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def deploy(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Repository path to deploy")] = Path("."),
    name: Annotated[str | None, typer.Option("--name", help="Explicit Sprite name to use")] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing den.dhall")] = False,
    no_run: Annotated[bool, typer.Option("--no-run", help="Only prepare the sprite; do not start an inferred command")] = False,
) -> None:
    """Prepare a repository for deployment and start it on Sprite when possible."""
    repo_dir = path.resolve()
    if not repo_dir.is_dir():
        raise CommandError(f"Repository path not found: {repo_dir}")
    den_file = repo_dir / "den.dhall"

    typer.secho(f"==> den deploy {repo_dir}", fg=typer.colors.CYAN)
    if den_file.exists() and not force:
        typer.echo(f"  Reusing existing config: {den_file}")
    else:
        setup(repo_dir, force=force, print_only=False)

    inferred = infer_den_setup(repo_dir)
    den_name = normalize_den_name(name or inferred.name)

    if _sprite_exists(den_name):
        typer.echo(f"  Reusing existing sprite: {den_name}")
    else:
        typer.echo(f"  Creating sprite:        {den_name}")
        _create_sprite(den_name)

    typer.echo(f"  Binding repository:     {repo_dir}")
    _run_checked(
        sprite_use_command(den_name),
        cwd=repo_dir,
        error_hint="Sprite use failed.",
    )
    remote_dir = _sync_repo_to_sprite(den_name, repo_dir)

    if no_run:
        typer.secho(f"OK {den_name} prepared for deployment", fg=typer.colors.GREEN)
        typer.echo(f"  Remote dir:      {remote_dir}")
        typer.echo(f"  Start manually: den exec {short_den_name(den_name)} -- <cmd...>")
        typer.echo(f"  Console:        den connect {short_den_name(den_name)}")
        return

    override_command = tuple(ctx.args)
    if override_command:
        run_command: tuple[str, ...] = override_command
        run_reasons: tuple[str, ...] = ("explicit deploy command provided",)
    else:
        inferred_run_command = infer_run_command(repo_dir)
        if inferred_run_command is None:
            typer.secho(f"OK {den_name} prepared, but no start command was inferred", fg=typer.colors.YELLOW)
            typer.echo(f"  Remote dir:      {remote_dir}")
            typer.echo("  den deploy prefers deterministic generation over guessing.")
            typer.echo(f"  Run manually: den exec {short_den_name(den_name)} -- <cmd...>")
            typer.echo(f"  Console:      den connect {short_den_name(den_name)}")
            return
        run_command = inferred_run_command.command
        run_reasons = inferred_run_command.reasons

    typer.echo(f"  Starting:               {' '.join(run_command)}")
    for reason in run_reasons:
        typer.echo(f"    - {reason}")
    _run_checked(
        sprite_command("exec", "--tty", "--dir", remote_dir, "--", *run_command, sprite_name=den_name),
        error_hint="Sprite exec failed.",
    )
    typer.secho(f"OK {den_name} deployed and running on Sprite", fg=typer.colors.GREEN)


@app.command()
def connect(
    name: Annotated[str | None, typer.Argument(help="Den name, with or without den- prefix")] = None,
) -> None:
    """Open a console in a den via Sprite."""
    target = normalize_den_name(name) if name else _choose_den_name("Connect to")
    typer.secho(f"==> Connecting to {target} via Sprite console...", fg=typer.colors.CYAN)
    _run_checked(sprite_command("console", sprite_name=target))


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def exec(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Den name, with or without den- prefix")],
) -> None:
    """Run a command in a den without opening an interactive console."""
    command = list(ctx.args)
    target = normalize_den_name(name)
    if not command:
        raise CommandError("Provide a command to run inside the den.")

    typer.secho(f"==> Running in {target} via Sprite exec...", fg=typer.colors.CYAN)
    _run_checked(sprite_exec_command(target, command))


@app.command(name="sprite-use")
def sprite_use(
    name: Annotated[str | None, typer.Argument(help="Den name, with or without den- prefix")] = None,
) -> None:
    """Bind the current directory to a den via sprite use."""
    target = normalize_den_name(name) if name else _choose_den_name("Bind current directory to")
    typer.secho(f"==> Binding current directory to {target} via Sprite...", fg=typer.colors.CYAN)
    _run_checked(sprite_use_command(target))


@app.command(name="list")
def list_dens(
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List dens managed by Sprite."""
    names = _list_den_names()

    if not names:
        if output_json:
            typer.echo("[]")
        else:
            typer.secho("==> Dens in Sprite", fg=typer.colors.CYAN)
            typer.echo()
            typer.echo("  No dens found")
        return

    entries: list[dict[str, str | None]] = []
    for name in names:
        url_proc = _run(sprite_command("url", sprite_name=name), capture_output=True)
        if url_proc.returncode == 0:
            info = parse_sprite_url_info(url_proc.stdout)
            entries.append({"name": name, "url": info.url, "auth": info.auth})
        else:
            entries.append({"name": name, "url": None, "auth": None})

    if output_json:
        typer.echo(json.dumps(entries, indent=2))
        return

    typer.secho("==> Dens in Sprite", fg=typer.colors.CYAN)
    typer.echo()

    name_w = max(len(e["name"] or "") for e in entries)
    url_w = max(len(e["url"] or "(unavailable)") for e in entries)
    header_name = "NAME".ljust(name_w)
    header_url = "URL".ljust(url_w)
    typer.echo(f"  {header_name}  {header_url}  AUTH")
    for entry in entries:
        n = (entry["name"] or "").ljust(name_w)
        u = (entry["url"] or "(unavailable)").ljust(url_w)
        a = entry["auth"] or "-"
        typer.echo(f"  {n}  {u}  {a}")


@app.command()
def status(
    name: Annotated[str | None, typer.Argument(help="Den name, with or without den- prefix")] = None,
) -> None:
    """Show status for a den."""
    den_name = normalize_den_name(name) if name else _choose_den_name("Show status for")
    short_name = short_den_name(den_name)
    _ensure_project_dir()

    typer.secho(f"==> Status: {den_name}", fg=typer.colors.CYAN)
    typer.echo()
    typer.echo("  Sprite:")

    list_proc = _run_checked(sprite_command("list", "-prefix", den_name), capture_output=True)
    if den_name in {line.strip() for line in list_proc.stdout.splitlines()}:
        typer.echo(f"    Name:        {den_name}")
        typer.echo("    Presence:    found")
    else:
        typer.echo(f"    Name:        {den_name}")
        typer.echo("    Presence:    not found")

    url_proc = _run(sprite_command("url", sprite_name=den_name), capture_output=True)
    if url_proc.returncode == 0 and url_proc.stdout.strip():
        for line in url_proc.stdout.splitlines():
            typer.echo(f"    {line}")
    else:
        typer.echo("    URL:         unavailable")

    typer.echo()
    typer.echo("  Hints:")
    typer.echo(f"    Connect:     den connect {short_name}")
    typer.echo(f"    Domain:      den domain {short_name} dev.example.com")


@app.command()
def domain(
    name: Annotated[str, typer.Argument(help="Den name")],
    host: Annotated[str, typer.Argument(help="Custom domain")],
) -> None:
    """Add a custom domain to a den via sesame URL forwarding."""
    den_name = normalize_den_name(name)
    _ensure_project_dir()

    typer.secho(f"==> Adding domain {host} to {den_name}", fg=typer.colors.CYAN)
    target_url = _attach_custom_domain(den_name, host)

    typer.echo()
    typer.secho(f"OK Domain {host} now forwards to {target_url}", fg=typer.colors.GREEN)


@app.command()
def funnel(
    name: Annotated[str, typer.Argument(help="Den name")],
    off: Annotated[bool, typer.Option("--off", help="Disable public URL")] = False,
) -> None:
    """Toggle the Sprite URL between public and org-authenticated."""
    den_name = normalize_den_name(name)
    auth_mode = "sprite" if off else "public"
    typer.secho(f"==> Setting Sprite URL auth for {den_name} to {auth_mode}...", fg=typer.colors.CYAN)
    _run_checked(
        sprite_command("url", "update", "--auth", auth_mode, sprite_name=den_name),
        error_hint="Failed to update Sprite URL auth mode.",
    )
    typer.secho(f"OK Sprite URL auth set to {auth_mode}", fg=typer.colors.GREEN)


@app.command()
def destroy(
    name: Annotated[str | None, typer.Argument(help="Den name")] = None,
) -> None:
    """Destroy a den in Sprite."""
    den_name = normalize_den_name(name) if name else _choose_den_name("Destroy which den")
    confirmed = typer.confirm(f"Destroy {den_name}? This deletes the sprite.", default=False)
    if not confirmed:
        raise CommandError("Cancelled")

    typer.secho(f"==> Destroying {den_name}...", fg=typer.colors.CYAN)
    _run_checked(
        sprite_command("destroy", "-force", sprite_name=den_name),
        cwd=PROJECT_DIR,
        error_hint="Sprite destroy failed.",
    )
    typer.secho(f"OK {den_name} destroyed", fg=typer.colors.GREEN)


@app.command()
def logs(
    name: Annotated[str | None, typer.Argument(help="Den name")] = None,
    session: Annotated[str | None, typer.Argument(help="Session ID or command name to attach to")] = None,
    list_only: Annotated[bool, typer.Option("--list", help="List running Sprite sessions instead of attaching")] = False,
) -> None:
    """Inspect running Sprite exec sessions or attach to one."""
    den_name = normalize_den_name(name) if name else _choose_den_name("Show logs for")
    if list_only and session:
        raise CommandError("Use either --list or a session selector, not both.")

    if list_only:
        typer.secho(f"==> Listing running sessions for {den_name}...", fg=typer.colors.CYAN)
    elif session:
        typer.secho(f"==> Attaching to session {session} in {den_name}...", fg=typer.colors.CYAN)
    else:
        typer.secho(f"==> Opening Sprite session selector for {den_name}...", fg=typer.colors.CYAN)

    _run_checked(sprite_logs_command(den_name, session, list_only=list_only))


@app.command()
def redeploy(
    name: Annotated[str | None, typer.Argument(help="Den name")] = None,
) -> None:
    """Restart a sprite by checkpointing current state and restoring it."""
    den_name = normalize_den_name(name) if name else _choose_den_name("Redeploy which den")
    comment = make_sprite_redeploy_comment(den_name, str(time.time_ns()))

    typer.secho(f"==> Redeploying {den_name} via Sprite checkpoint restore...", fg=typer.colors.CYAN)
    _run_checked(
        sprite_checkpoint_create_command(den_name, comment),
        capture_output=True,
        error_hint="Sprite checkpoint creation failed.",
    )

    checkpoint_id: str | None = None
    api_proc = _run(sprite_command("api", "/checkpoints", sprite_name=den_name), capture_output=True)
    if api_proc.returncode == 0 and api_proc.stdout.strip():
        checkpoint_id = find_checkpoint_version_in_api_output(api_proc.stdout, comment)

    if checkpoint_id is None:
        list_proc = _run(sprite_command("checkpoint", "list", sprite_name=den_name), capture_output=True)
        if list_proc.returncode == 0 and list_proc.stdout.strip():
            checkpoint_id = find_checkpoint_version_in_list_output(list_proc.stdout, comment)

    if checkpoint_id is None:
        raise CommandError(
            f"Checkpoint created for {den_name}, but den could not determine the new checkpoint ID to restore. Run sprite checkpoint list -s {den_name} and then sprite restore <id> manually."
        )

    _run_checked(
        sprite_restore_command(den_name, checkpoint_id),
        error_hint="Sprite restore failed.",
    )
    typer.secho(f"OK {den_name} restart triggered via checkpoint {checkpoint_id}", fg=typer.colors.GREEN)


@app.command(name="build-guix")
def build_guix(
    system: Annotated[bool, typer.Option("--system", help="Build Guix system image")] = False,
    push: Annotated[str | None, typer.Option("--push", help="Push target image")] = None,
) -> None:
    """Build a Guix image locally via build-guix-image.sh."""
    _ensure_project_dir()

    if not _command_exists("guix"):
        raise CommandError("guix not found. Install Guix first.")

    describe = _run(["guix", "describe"], capture_output=True)
    if describe.returncode != 0:
        typer.echo("guix-daemon not running. Starting...")
        _run_checked(["sudo", "systemctl", "start", "guix-daemon"])

    args = ["bash", str(PROJECT_DIR / "scripts" / "build-guix-image.sh")]
    if system:
        args.append("--system")
    if push:
        args.extend(["--push", push])

    _run_checked(args)


@app.callback(invoke_without_command=True)
def root_callback(ctx: typer.Context) -> None:
    """Top-level error boundary with useful exit codes."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


def main() -> int:
    try:
        app()
    except CommandError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
