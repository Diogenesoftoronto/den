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
    DomainMode,
    DomainProvider,
    RailwayProjectSummary,
    RuntimeProvider,
    DnsRecord,
    build_sesame_dns_create_command,
    build_sesame_dns_edit_command,
    build_sesame_dns_list_command,
    build_sesame_url_forward_command,
    extract_railway_linked_project_name,
    parse_railway_service_statuses,
    fly_certs_add_command,
    railway_delete_command,
    railway_list_command,
    parse_fly_dns_records,
    parse_railway_projects,
    parse_railway_dns_records,
    railway_domain_attach_command,
    resolve_railway_command,
    railway_status_command,
    discover_cloudflare_domains,
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
    resolve_custom_domain,
    resolve_sesame_command,
    sesame_dns_records_exist,
    short_den_name,
    sprite_checkpoint_create_command,
    sprite_command,
    sprite_exec_command,
    sprite_logs_command,
    sprite_restore_command,
    sprite_use_command,
    porkbun_add_url_forward,
    porkbun_upsert_dns_records,
    upsert_cloudflare_dns_records,
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


def _run_checked_binary(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    capture_output: bool = False,
    error_hint: str | None = None,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        input=input_bytes,
        capture_output=capture_output,
        check=False,
    )
    if proc.returncode != 0:
        if error_hint:
            typer.secho(error_hint, fg=typer.colors.RED)
        stderr = proc.stderr.decode(errors="replace").strip() if proc.stderr else ""
        stdout = proc.stdout.decode(errors="replace").strip() if proc.stdout else ""
        if stderr:
            typer.echo(stderr)
        if stdout and not stderr:
            typer.echo(stdout)
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


def _railway_status_command() -> list[str]:
    return railway_status_command()


def _railway_up_command(path: Path, *, detach: bool = False) -> list[str]:
    command = resolve_railway_command() + ["up", str(path)]
    if detach:
        command.append("--detach")
    return command


def _ensure_railway_ready() -> None:
    _run_checked(
        _railway_status_command(),
        cwd=PROJECT_DIR,
        capture_output=True,
        error_hint="Railway status failed. Login or link this directory to a Railway project first.",
    )


def _railway_projects() -> list[RailwayProjectSummary]:
    proc = _run_checked(
        railway_list_command(),
        capture_output=True,
        error_hint="Railway project listing failed. Login first with railway login.",
    )
    try:
        payload = json.loads(proc.stdout)
        return parse_railway_projects(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise CommandError(f"Could not parse Railway project list: {exc}") from exc


def _railway_linked_status_payload() -> object:
    proc = _run_checked(
        railway_status_command(),
        cwd=PROJECT_DIR,
        capture_output=True,
        error_hint="Railway status failed. Login or link this directory to a Railway project first.",
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CommandError("Railway returned malformed JSON for status.") from exc


def _linked_railway_project_name() -> str | None:
    return extract_railway_linked_project_name(_railway_linked_status_payload())


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

        remote_archive = f"/home/sprite/{repo_dir.name}-{nonce}.tar"
        unpack_command = (
            f"mkdir -p {shlex.quote(remote_dir)} "
            f"&& cat > {shlex.quote(remote_archive)} "
            f"&& tar -xf {shlex.quote(remote_archive)} -C {shlex.quote(remote_dir)} --strip-components=1 "
            f"&& rm -f {shlex.quote(remote_archive)}"
        )
        _run_checked_binary(
            sprite_command(
                "exec", "--", "sh", "-lc", unpack_command, sprite_name=den_name
            ),
            input_bytes=archive_path.read_bytes(),
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


def _configured_domain_zones() -> dict[DomainProvider, list[str]]:
    return {
        DomainProvider.cloudflare: discover_cloudflare_domains(),
        DomainProvider.sesame: _owned_porkbun_domains(),
    }


def _attach_cloudflare_dns_to_sprite(den_name: str, host: str, zone: str, *, proxied: bool) -> None:
    add_proc = _run_checked(
        fly_certs_add_command(den_name, host),
        capture_output=True,
        error_hint="Failed to attach the hostname to Fly.",
    )
    try:
        payload = json.loads(add_proc.stdout)
    except json.JSONDecodeError as exc:
        raise CommandError("Fly returned malformed JSON while attaching the hostname.") from exc

    try:
        records = parse_fly_dns_records(host, zone, payload, proxied=proxied)
        applied = upsert_cloudflare_dns_records(zone, records)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc

    typer.echo("  Cloudflare DNS:")
    for entry in applied:
        record = entry.get("record")
        if not isinstance(record, dict):
            continue
        typer.echo(f"    - {entry.get('action')}: {record['type']} {record['name']} -> {record['content']}")


def _attach_cloudflare_dns_to_railway(service: str, host: str, zone: str, *, proxied: bool, port: int | None) -> None:
    add_proc = _run_checked(
        railway_domain_attach_command(service, host, port=port),
        capture_output=True,
        error_hint="Failed to attach the hostname to Railway.",
    )
    try:
        payload = json.loads(add_proc.stdout)
    except json.JSONDecodeError as exc:
        raise CommandError("Railway returned malformed JSON while attaching the hostname.") from exc

    try:
        records = parse_railway_dns_records(host, zone, payload, proxied=proxied)
        applied = upsert_cloudflare_dns_records(zone, records)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc

    typer.echo("  Cloudflare DNS:")
    for entry in applied:
        record = entry.get("record")
        if not isinstance(record, dict):
            continue
        typer.echo(f"    - {entry.get('action')}: {record['type']} {record['name']} -> {record['content']}")


def _upsert_sesame_dns_records(zone: str, records: list[DnsRecord]) -> None:
    typer.echo("  Porkbun DNS:")
    try:
        sesame_cmd = _sesame_command()
    except CommandError:
        # sesame not installed — fall back to direct Porkbun API
        try:
            applied = porkbun_upsert_dns_records(zone, records)
        except Exception as exc:
            raise CommandError(f"Failed to upsert Porkbun DNS records: {exc}") from exc
        for action, record in applied:
            fqdn = zone if record.name == "@" else f"{record.name}.{zone}"
            typer.echo(f"    - {action}: {record.type} {fqdn} -> {record.content}")
        return

    for record in records:
        lookup_proc = _run_checked(
            sesame_cmd + build_sesame_dns_list_command(zone, record),
            capture_output=True,
            error_hint="Failed to inspect existing Porkbun DNS records via sesame.",
        )
        try:
            lookup_payload = json.loads(lookup_proc.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise CommandError("sesame returned malformed JSON while listing DNS records.") from exc

        if sesame_dns_records_exist(lookup_payload):
            command = sesame_cmd + build_sesame_dns_edit_command(zone, record)
            action = "updated"
        else:
            command = sesame_cmd + build_sesame_dns_create_command(zone, record)
            action = "created"

        _run_checked(command, capture_output=True, error_hint="Failed to upsert Porkbun DNS record via sesame.")
        fqdn = zone if record.name == "@" else f"{record.name}.{zone}"
        typer.echo(f"    - {action}: {record.type} {fqdn} -> {record.content}")


def _attach_sesame_dns_to_railway(service: str, host: str, zone: str, *, port: int | None) -> None:
    add_proc = _run_checked(
        railway_domain_attach_command(service, host, port=port),
        capture_output=True,
        error_hint="Failed to attach the hostname to Railway.",
    )
    try:
        payload = json.loads(add_proc.stdout)
    except json.JSONDecodeError as exc:
        raise CommandError("Railway returned malformed JSON while attaching the hostname.") from exc

    try:
        records = parse_railway_dns_records(host, zone, payload, proxied=False)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc

    _upsert_sesame_dns_records(zone, records)


def _attach_sesame_dns_to_sprite(den_name: str, host: str, zone: str) -> str:
    target_url = _sprite_url(den_name)
    # For CNAME/ALIAS records, use the host-only part (strip https://)
    content = target_url.replace("https://", "").replace("http://", "")
    records = [DnsRecord(
        name=host.split(".")[0] if host.split(".").__len__() > 2 else "@",
        type="CNAME",
        content=content,
        proxied=False,
    )]
    _upsert_sesame_dns_records(zone, records)
    return target_url


def _sprite_url(den_name: str) -> str:
    proc = _run_checked(sprite_command("url", sprite_name=den_name), capture_output=True)
    url = parse_sprite_url(proc.stdout)
    if not url:
        raise CommandError(f"Could not parse sprite URL for {den_name}")
    return url


def _attach_custom_domain(
    name: str,
    host: str,
    *,
    runtime: RuntimeProvider,
    mode: DomainMode,
    proxied: bool,
    port: int | None,
) -> str:
    provider_domains = _configured_domain_zones()
    match = resolve_custom_domain(host, provider_domains)
    target_url = _sprite_url(name) if runtime is RuntimeProvider.sprite else f"railway://{name}"

    if mode is DomainMode.dns:
        if match.provider is DomainProvider.cloudflare:
            if runtime is RuntimeProvider.sprite:
                _attach_cloudflare_dns_to_sprite(name, host, match.zone, proxied=proxied)
            else:
                _attach_cloudflare_dns_to_railway(name, host, match.zone, proxied=proxied, port=port)
            return target_url
        if match.provider is DomainProvider.sesame:
            if runtime is RuntimeProvider.sprite:
                return _attach_sesame_dns_to_sprite(name, host, match.zone)
            else:
                _attach_sesame_dns_to_railway(name, host, match.zone, port=port)
                return target_url
        raise CommandError(
            f"{host} is held by {match.provider.value}. Native DNS attachment is implemented for Cloudflare and sesame/Porkbun zones."
        )

    if runtime is not RuntimeProvider.sprite:
        raise CommandError("Forward mode is currently implemented for Sprite-backed runtimes only.")
    _run_checked(
        sprite_command("url", "update", "--auth", "public", sprite_name=name),
        capture_output=True,
        error_hint="Failed to make the sprite URL public.",
    )
    if match.provider is not DomainProvider.sesame:
        raise CommandError(
            f"{host} is held by {match.provider.value}. Forward mode is currently implemented for sesame/Porkbun-hosted zones."
        )
    owned_domains = provider_domains[DomainProvider.sesame]
    try:
        sesame_cmd = _sesame_command()
        command = sesame_cmd + build_sesame_url_forward_command(host, target_url, owned_domains)
        _run_checked(command, error_hint="Failed to create Porkbun URL forward via sesame.")
    except CommandError:
        # sesame not installed — fall back to direct Porkbun API
        try:
            porkbun_add_url_forward(host, target_url, owned_domains)
        except Exception as exc:
            raise CommandError(f"Failed to create Porkbun URL forward: {exc}") from exc
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
    runtime: Annotated[RuntimeProvider, typer.Option("--runtime", help="Runtime provider to create or prepare")] = RuntimeProvider.sprite,
) -> None:
    """Create a new den environment."""
    _ensure_project_dir()

    den_input = name or typer.prompt("Den name")
    den_input = den_input.strip()
    if not den_input:
        raise CommandError("Cancelled")

    den_name = normalize_den_name(den_input)
    backend = Backend.guix if guix else Backend.nix
    typer.secho(f"==> Spawning {den_name} ({backend.value}, runtime={runtime.value})", fg=typer.colors.CYAN)
    if runtime is RuntimeProvider.sprite:
        _create_sprite(den_name)
    else:
        _ensure_railway_ready()

    short_name = short_den_name(den_name)
    typer.echo()
    if runtime is RuntimeProvider.sprite:
        typer.secho(f"OK {den_name} created in Sprite", fg=typer.colors.GREEN)
        typer.echo("  Backend selection is recorded locally; Sprite owns the runtime image.")
        typer.echo(f"  Connect:    den connect {short_name}")
        typer.echo(f"  Status:     den status {short_name}")
        typer.echo(f"  Domain:     den domain {short_name} dev.example.com")
    else:
        typer.secho("OK Railway project/service is reachable for deployment", fg=typer.colors.GREEN)
        typer.echo("  Spawn on Railway is a readiness check rather than a separate environment creation step.")
        typer.echo(f"  Deploy:     den deploy . --name {short_name} --runtime railway")
        typer.echo(f"  Domain:     den domain {short_name} dev.example.com --runtime railway")


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def deploy(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Repository path to deploy")] = Path("."),
    name: Annotated[str | None, typer.Option("--name", help="Explicit runtime name or service name to use")] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing den.dhall")] = False,
    no_run: Annotated[bool, typer.Option("--no-run", help="Only prepare the sprite; do not start an inferred command")] = False,
    runtime: Annotated[RuntimeProvider, typer.Option("--runtime", help="Runtime provider to deploy to")] = RuntimeProvider.sprite,
) -> None:
    """Prepare a repository for deployment and start it on the selected runtime when possible."""
    repo_dir = path.resolve()
    if not repo_dir.is_dir():
        raise CommandError(f"Repository path not found: {repo_dir}")
    den_file = repo_dir / "den.dhall"

    typer.secho(f"==> den deploy {repo_dir} (runtime={runtime.value})", fg=typer.colors.CYAN)
    if den_file.exists() and not force:
        typer.echo(f"  Reusing existing config: {den_file}")
    else:
        setup(repo_dir, force=force, print_only=False)

    inferred = infer_den_setup(repo_dir)
    den_name = normalize_den_name(name or inferred.name)

    if runtime is RuntimeProvider.sprite:
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
    else:
        _ensure_railway_ready()
        if no_run:
            typer.secho("OK Railway runtime verified and repo prepared locally", fg=typer.colors.GREEN)
            typer.echo("  Run deploy manually: den deploy . --runtime railway")
            return
        typer.echo(f"  Deploying to Railway:  {repo_dir}")
        _run_checked(
            _railway_up_command(repo_dir, detach=True),
            cwd=repo_dir,
            error_hint="Railway deploy failed.",
        )
        typer.secho(f"OK {den_name} deployed to Railway", fg=typer.colors.GREEN)
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
    runtime: Annotated[RuntimeProvider, typer.Option("--runtime", help="Runtime provider inventory to show")] = RuntimeProvider.sprite,
) -> None:
    """List dens managed by the selected runtime provider."""
    if runtime is RuntimeProvider.railway:
        projects = [project for project in _railway_projects() if project.name.startswith("den-")]
        if output_json:
            typer.echo(
                json.dumps(
                    [
                        {"name": project.name, "project_id": project.project_id, "workspace": project.workspace_name}
                        for project in projects
                    ],
                    indent=2,
                )
            )
            return

        typer.secho("==> Dens in Railway", fg=typer.colors.CYAN)
        typer.echo()
        if not projects:
            typer.echo("  No den-prefixed Railway projects found")
            return

        name_w = max(len(project.name) for project in projects)
        workspace_w = max(len(project.workspace_name or "-") for project in projects)
        typer.echo(f"  {'NAME'.ljust(name_w)}  {'WORKSPACE'.ljust(workspace_w)}  PROJECT ID")
        for project in projects:
            workspace = (project.workspace_name or "-").ljust(workspace_w)
            project_id = project.project_id or "-"
            typer.echo(f"  {project.name.ljust(name_w)}  {workspace}  {project_id}")
        return

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
    runtime: Annotated[RuntimeProvider, typer.Option("--runtime", help="Runtime provider to inspect")] = RuntimeProvider.sprite,
    service: Annotated[str | None, typer.Option("--service", help="Specific Railway service to inspect")] = None,
) -> None:
    """Show status for a den or linked runtime project."""
    den_name = normalize_den_name(name) if name else _choose_den_name("Show status for")
    short_name = short_den_name(den_name)
    _ensure_project_dir()

    if runtime is RuntimeProvider.railway:
        payload = _railway_linked_status_payload()
        linked_project = extract_railway_linked_project_name(payload)
        services = parse_railway_service_statuses(payload)
        typer.secho(f"==> Railway status: {den_name}", fg=typer.colors.CYAN)
        typer.echo()
        typer.echo("  Railway:")
        typer.echo(f"    Requested name: {den_name}")
        typer.echo(f"    Linked project: {linked_project or 'unknown'}")
        typer.echo(f"    Match:          {'yes' if linked_project == den_name else 'no'}")
        typer.echo(f"    Services:       {len(services)}")
        if service:
            matched = next((entry for entry in services if entry.name == service), None)
            if matched is None:
                available = ", ".join(sorted(entry.name for entry in services)) or "none"
                raise CommandError(f"Railway service {service!r} not found in the linked project. Available services: {available}")
            typer.echo()
            typer.echo("  Service:")
            typer.echo(f"    Name:           {matched.name}")
            typer.echo(f"    Service ID:     {matched.service_id or 'unknown'}")
            typer.echo(f"    Instance ID:    {matched.instance_id or 'unknown'}")
            typer.echo(f"    Deployment ID:  {matched.latest_deployment_id or 'unknown'}")
            typer.echo(f"    Deployment:     {matched.latest_deployment_status or 'unknown'}")
            typer.echo(f"    Stopped:        {matched.deployment_stopped if matched.deployment_stopped is not None else 'unknown'}")
        elif services:
            typer.echo()
            typer.echo("  Services:")
            for entry in services:
                typer.echo(
                    f"    {entry.name}: deployment={entry.latest_deployment_status or 'unknown'}"
                    f" stopped={entry.deployment_stopped if entry.deployment_stopped is not None else 'unknown'}"
                )
        typer.echo()
        typer.echo("  Raw status:")
        for line in json.dumps(payload, indent=2, sort_keys=True).splitlines():
            typer.echo(f"    {line}")
        typer.echo()
        typer.echo("  Hints:")
        typer.echo("    Deploy:      den deploy . --runtime railway")
        typer.echo(f"    Domain:      den domain {short_name} dev.example.com --runtime railway")
        return

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
    runtime: Annotated[RuntimeProvider, typer.Option("--runtime", help="Runtime provider that serves the hostname")] = RuntimeProvider.sprite,
    mode: Annotated[DomainMode, typer.Option("--mode", help="Attach as native DNS or a redirect/forward")] = DomainMode.dns,
    proxied: Annotated[bool, typer.Option("--proxied/--no-proxied", help="Whether Cloudflare should proxy supported DNS records")] = False,
    port: Annotated[int | None, typer.Option("--port", help="Runtime port for providers that require it")] = None,
) -> None:
    """Attach a custom domain to a den."""
    den_name = normalize_den_name(name)
    _ensure_project_dir()

    typer.secho(
        f"==> Attaching domain {host} to {den_name} using runtime={runtime.value} mode={mode.value}",
        fg=typer.colors.CYAN,
    )
    target_url = _attach_custom_domain(den_name, host, runtime=runtime, mode=mode, proxied=proxied, port=port)

    typer.echo()
    if mode is DomainMode.forward:
        typer.secho(f"OK Domain {host} now forwards to {target_url}", fg=typer.colors.GREEN)
    else:
        typer.secho(f"OK Domain {host} is attached to {target_url}", fg=typer.colors.GREEN)


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
    runtime: Annotated[RuntimeProvider, typer.Option("--runtime", help="Runtime provider to destroy from")] = RuntimeProvider.sprite,
) -> None:
    """Destroy a den in the selected runtime provider."""
    den_name = normalize_den_name(name) if name else _choose_den_name("Destroy which den")
    noun = "sprite" if runtime is RuntimeProvider.sprite else "linked Railway project"
    confirmed = typer.confirm(f"Destroy {den_name}? This deletes the {noun}.", default=False)
    if not confirmed:
        raise CommandError("Cancelled")

    typer.secho(f"==> Destroying {den_name} from runtime={runtime.value}...", fg=typer.colors.CYAN)
    if runtime is RuntimeProvider.sprite:
        _run_checked(
            sprite_command("destroy", "-force", sprite_name=den_name),
            cwd=PROJECT_DIR,
            error_hint="Sprite destroy failed.",
        )
        typer.secho(f"OK {den_name} destroyed", fg=typer.colors.GREEN)
        return

    linked_project = _linked_railway_project_name()
    if linked_project != den_name:
        raise CommandError(
            f"Refusing Railway project deletion because the linked project is {linked_project or 'unknown'}, not {den_name}. Link the intended Railway project in {PROJECT_DIR} before retrying."
        )
    _run_checked(
        railway_delete_command(den_name),
        cwd=PROJECT_DIR,
        error_hint="Railway project deletion failed.",
    )
    typer.secho(f"OK {den_name} deleted from Railway", fg=typer.colors.GREEN)


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
