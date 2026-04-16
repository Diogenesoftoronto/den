from __future__ import annotations

import json
import os
import shutil
import tomllib
import urllib.request
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Collection, Literal, Mapping
from urllib.parse import urlparse


@dataclass(frozen=True)
class DenPeer:
    """Minimal den peer view extracted from a Tailscale status payload."""

    host_name: str
    ip: str
    online: bool


@dataclass(frozen=True)
class ProjectMarkers:
    """Filesystem-level signals used to infer a reproducible den setup."""

    has_package_json: bool
    has_bun_lock: bool
    has_pyproject: bool
    has_cargo_toml: bool
    has_dockerfile: bool
    has_containerfile: bool
    has_mise_toml: bool
    has_flox_toml: bool
    has_helm_chart: bool
    has_nix_flake: bool
    has_shell_nix: bool
    has_guix_manifest: bool
    has_guix_channels: bool


@dataclass(frozen=True)
class InferredDenSetup:
    """Normalized setup plan produced from repository markers before Dhall rendering."""

    name: str
    backend: Literal["nix", "guix"]
    dockerfile: str | None
    nix_packages: tuple[str, ...]
    guix_packages: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class InferredRunCommand:
    """Best-effort command den can launch for live development on a sprite."""

    command: tuple[str, ...]
    reasons: tuple[str, ...]


class DomainProvider(StrEnum):
    """Supported custom-domain authorities."""

    cloudflare = "cloudflare"
    sesame = "sesame"


class DomainMode(StrEnum):
    """Supported custom-domain attachment modes."""

    dns = "dns"
    forward = "forward"


class RuntimeProvider(StrEnum):
    """Supported runtime/deployment targets."""

    sprite = "sprite"
    railway = "railway"


@dataclass(frozen=True)
class DomainMatch:
    """Resolved custom-domain ownership and host split."""

    provider: DomainProvider
    zone: str
    subdomain: str | None


@dataclass(frozen=True)
class DnsRecord:
    """Normalized DNS record desired by den."""

    type: str
    name: str
    content: str
    proxied: bool = False


@dataclass(frozen=True)
class RailwayProjectSummary:
    """Minimal Railway project view used by den list/status flows."""

    name: str
    project_id: str | None = None
    workspace_name: str | None = None


@dataclass(frozen=True)
class RailwayServiceStatusSummary:
    """Service-oriented view extracted from Railway status JSON."""

    name: str
    service_id: str | None = None
    instance_id: str | None = None
    latest_deployment_id: str | None = None
    latest_deployment_status: str | None = None
    deployment_stopped: bool | None = None


def normalize_den_name(name: str) -> str:
    """Ensure human-facing den names are normalized to the Sprite naming convention."""

    return name if name.startswith("den-") else f"den-{name}"


def short_den_name(name: str) -> str:
    """Drop the canonical den prefix for display-oriented output."""

    return name[4:] if name.startswith("den-") else name


def sprite_org() -> str | None:
    """Return the preferred Sprite org from den-specific or upstream env vars."""

    for key in ("DEN_SPRITE_ORG", "SPRITE_ORG"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def sprite_command(*args: str, sprite_name: str | None = None) -> list[str]:
    """Build a Sprite CLI command with optional org and normalized sprite context."""

    command = ["sprite"]
    org = sprite_org()
    if org:
        command.extend(["-o", org])
    if sprite_name:
        command.extend(["-s", normalize_den_name(sprite_name)])
    command.extend(args)
    return command


def sprite_exec_command(name: str, command: Sequence[str]) -> list[str]:
    """Build the Sprite argv for a non-interactive command execution."""

    return sprite_command("exec", "--", *command, sprite_name=name)


def sprite_tty_exec_command(name: str, command: Sequence[str]) -> list[str]:
    """Build the Sprite argv for a long-running interactive TTY session."""

    return sprite_command("exec", "--tty", "--", *command, sprite_name=name)


def sprite_use_command(name: str) -> list[str]:
    """Build the Sprite argv for binding the current directory to a sprite."""

    command = ["sprite"]
    org = sprite_org()
    if org:
        command.extend(["-o", org])
    command.extend(["use", normalize_den_name(name)])
    return command


def sprite_logs_command(name: str, selector: str | None = None, *, list_only: bool = False) -> list[str]:
    """Build the Sprite argv for session listing or attachment."""

    if list_only:
        return sprite_command("sessions", "list", sprite_name=name)
    if selector:
        return sprite_command("attach", selector, sprite_name=name)
    return sprite_command("attach", sprite_name=name)


def sprite_checkpoint_create_command(name: str, comment: str) -> list[str]:
    """Build the Sprite argv for checkpoint creation with a stable comment tag."""

    return sprite_command("checkpoint", "create", "--comment", comment, sprite_name=name)


def sprite_restore_command(name: str, version_id: str) -> list[str]:
    """Build the Sprite argv for restoring a checkpoint version."""

    return sprite_command("restore", version_id, sprite_name=name)


def make_sprite_redeploy_comment(name: str, nonce: str) -> str:
    """Create a unique checkpoint comment that den can search for after creation."""

    return f"den-redeploy:{normalize_den_name(name)}:{nonce}"


def detect_project_markers(root: Path) -> ProjectMarkers:
    """Collect coarse repository signals used by the setup inference heuristics."""

    return ProjectMarkers(
        has_package_json=(root / "package.json").is_file(),
        has_bun_lock=(root / "bun.lock").is_file() or (root / "bun.lockb").is_file(),
        has_pyproject=(root / "pyproject.toml").is_file(),
        has_cargo_toml=(root / "Cargo.toml").is_file(),
        has_dockerfile=(root / "Dockerfile").is_file(),
        has_containerfile=(root / "Containerfile").is_file(),
        has_mise_toml=(root / "mise.toml").is_file(),
        has_flox_toml=(root / "flox.toml").is_file(),
        has_helm_chart=(root / "Chart.yaml").is_file() or (root / "charts").is_dir(),
        has_nix_flake=(root / "flake.nix").is_file(),
        has_shell_nix=(root / "shell.nix").is_file(),
        has_guix_manifest=(root / "guix" / "manifest.scm").is_file(),
        has_guix_channels=(root / "guix" / "channels.scm").is_file(),
    )


def infer_den_setup(root: Path) -> InferredDenSetup:
    """Infer a typed den setup plan from repository markers.

    This is the pure decision layer behind `den setup`: it chooses a backend,
    selects default package sets, and prepares environment metadata that will
    later be rendered into `den.dhall`.
    """

    markers = detect_project_markers(root)

    backend, reasons = _infer_backend(markers)
    name = root.name or "workspace"
    dockerfile = None
    if markers.has_dockerfile:
        dockerfile = "Dockerfile"
    elif markers.has_containerfile:
        dockerfile = "Containerfile"

    nix_packages = _infer_nix_packages(markers)
    guix_packages = _infer_guix_packages(markers)
    environment_rows: list[tuple[str, str]] = [
        ("DEN_NAME", normalize_den_name(name)),
        ("DEN_BACKEND", backend),
    ]
    if dockerfile is not None:
        environment_rows.append(("DEN_DOCKERFILE", dockerfile))

    return InferredDenSetup(
        name=name,
        backend=backend,
        dockerfile=dockerfile,
        nix_packages=nix_packages,
        guix_packages=guix_packages,
        environment=tuple(environment_rows),
        reasons=reasons,
    )


def _infer_backend(markers: ProjectMarkers) -> tuple[Literal["nix", "guix"], tuple[str, ...]]:
    """Choose a backend using simple, explainable repo-shape heuristics."""

    reasons: list[str] = []
    if markers.has_guix_manifest or markers.has_guix_channels:
        reasons.append("existing Guix manifests detected")
        return "guix", tuple(reasons)

    nix_signals = (
        markers.has_bun_lock
        or markers.has_package_json
        or markers.has_cargo_toml
        or markers.has_mise_toml
        or markers.has_flox_toml
        or markers.has_nix_flake
        or markers.has_shell_nix
        or markers.has_dockerfile
        or markers.has_containerfile
        or markers.has_helm_chart
    )
    if markers.has_pyproject and not nix_signals:
        reasons.append("standalone Python project detected")
        return "guix", tuple(reasons)

    if markers.has_bun_lock:
        reasons.append("bun lockfile detected")
    if markers.has_package_json:
        reasons.append("package.json detected")
    if markers.has_cargo_toml:
        reasons.append("Cargo.toml detected")
    if markers.has_mise_toml:
        reasons.append("mise.toml detected")
    if markers.has_flox_toml:
        reasons.append("flox.toml detected")
    if markers.has_nix_flake or markers.has_shell_nix:
        reasons.append("existing Nix metadata detected")
    if markers.has_dockerfile or markers.has_containerfile:
        reasons.append("container build file detected")
    if markers.has_helm_chart:
        reasons.append("Helm chart detected")
    if markers.has_pyproject and nix_signals:
        reasons.append("pyproject.toml detected alongside Nix/container signals")

    if not reasons:
        reasons.append("defaulting to Nix for portable podenv/container workflows")
    return "nix", tuple(reasons)


def _infer_nix_packages(markers: ProjectMarkers) -> tuple[str, ...]:
    """Infer a minimal Nix package set from detected repository signals."""

    packages = ["fish", "git", "helix"]
    if markers.has_bun_lock:
        packages.append("bun")
    elif markers.has_package_json:
        packages.append("nodejs")
    if markers.has_cargo_toml:
        packages.extend(["cargo", "rustc"])
    if markers.has_pyproject:
        packages.append("python")
    if markers.has_mise_toml:
        packages.append("mise")
    if markers.has_flox_toml:
        packages.append("flox")
    if markers.has_helm_chart:
        packages.append("helm")
    return tuple(dict.fromkeys(packages))


def _infer_guix_packages(markers: ProjectMarkers) -> tuple[str, ...]:
    """Infer a Guix package set aligned with the detected repository shape."""

    packages = ["fish", "git", "helix", "zellij", "jj", "gh", "fzf", "ripgrep", "fd", "bat"]
    if markers.has_bun_lock:
        packages.extend(["node", "bun"])
    elif markers.has_package_json:
        packages.append("node")
    if markers.has_cargo_toml:
        packages.extend(["rust", "cargo"])
    if markers.has_pyproject:
        packages.append("python")
    if markers.has_helm_chart:
        packages.append("helm")
    return tuple(dict.fromkeys(packages))


def render_den_dhall(config: InferredDenSetup, dhall_dir: Path) -> str:
    """Render an inferred setup plan into a concrete `den.dhall` expression."""

    backend_expr = "Types.Backend.Nix" if config.backend == "nix" else "Types.Backend.Guix"
    dockerfile_expr = _optional_text(config.dockerfile)
    nix_expr = _render_nix_config(config.nix_packages) if config.backend == "nix" else "None Types.NixConfig"
    guix_expr = _render_guix_config(config.guix_packages) if config.backend == "guix" else "None Types.GuixConfig"
    env_expr = _render_env_list(config.environment)
    reasons = "\n".join(f"-- - {reason}" for reason in config.reasons)

    return f"""-- Generated by den setup
-- Inference reasons:
{reasons}

let Types = {dhall_dir / "Types.dhall"}

let Defaults = {dhall_dir / "default.dhall"}

in  {{ name = "{config.name}"
    , backend = {backend_expr}
    , dockerfile = {dockerfile_expr}
    , restartPolicy = Some Types.RestartPolicy.Always
    , healthcheck = None Types.Healthcheck
    , ports = Defaults.defaultPorts
    , volumes = Defaults.defaultVolumes
    , resources = None Types.Resource
    , secrets =
        [ Types.Secret.FromEnv
            {{ name = "TAILSCALE_AUTHKEY", envVar = "TAILSCALE_AUTHKEY" }}
        ]
    , guix = {guix_expr}
    , nix = {nix_expr}
    , environment = {env_expr}
    , domains = [] : List Text
    }}
"""


def infer_run_command(root: Path) -> InferredRunCommand | None:
    """Infer a development command den can run on a sprite for this repo.

    Prefer deterministic generation over guesswork. Return `None` when den
    cannot infer a command confidently from repo metadata.
    """

    markers = detect_project_markers(root)
    if markers.has_mise_toml:
        command = _infer_mise_run_command(root)
        if command is not None:
            return command
    if markers.has_package_json:
        command = _infer_package_json_run_command(root, prefer_bun=markers.has_bun_lock)
        if command is not None:
            return command
    if markers.has_cargo_toml:
        command = _infer_cargo_run_command(root)
        if command is not None:
            return command
    if markers.has_pyproject:
        command = _infer_pyproject_run_command(root)
        if command is not None:
            return command
    return None


def _optional_text(value: str | None) -> str:
    """Render a Python optional string as a Dhall `Optional Text` expression."""

    if value is None:
        return "None Text"
    return f'Some "{value}"'


def _render_package_list(packages: Sequence[str]) -> str:
    """Render package names into a Dhall `List Types.Package` literal."""

    if not packages:
        return "[] : List Types.Package"
    rows = "\n        , ".join(f'{{ name = "{package}", version = None Text }}' for package in packages)
    return f"[ {rows} ]"


def _render_nix_config(packages: Sequence[str]) -> str:
    """Render the inferred Nix package block for `DenConfig.nix`."""

    return (
        "Some\n"
        "      { packages = "
        + _render_package_list(packages)
        + "\n      , extraConfig = None Text\n      }"
    )


def _render_guix_config(packages: Sequence[str]) -> str:
    """Render the inferred Guix package block for `DenConfig.guix`."""

    return (
        "Some\n"
        "      { channels = None (List Types.Channel)\n"
        "      , packages = "
        + _render_package_list(packages)
        + "\n      , services = None (List Text)\n      }"
    )


def _render_env_list(environment: Sequence[tuple[str, str]]) -> str:
    """Render environment key/value pairs into the Dhall record-list form."""

    if not environment:
        return "[] : List { mapKey : Text, mapValue : Text }"
    rows = "\n        , ".join(
        f'{{ mapKey = "{key}", mapValue = "{value}" }}' for key, value in environment
    )
    return f"[ {rows} ]"


def _infer_mise_run_command(root: Path) -> InferredRunCommand | None:
    """Infer a portable `mise run` command from the repository task definitions."""

    mise_toml = root / "mise.toml"
    try:
        payload = tomllib.loads(mise_toml.read_text())
    except Exception:
        return None

    tasks_obj = payload.get("tasks")
    if not isinstance(tasks_obj, dict):
        return None

    for task_name in ("start", "dev", "serve"):
        task = tasks_obj.get(task_name)
        if isinstance(task, dict):
            run_value = task.get("run")
            if isinstance(run_value, str) and run_value.strip():
                return InferredRunCommand(
                    command=("bash", "-lc", f"mise trust && mise run {task_name}"),
                    reasons=(
                        "mise.toml detected",
                        f'mise task "{task_name}" detected',
                    ),
                )
    return None


def _infer_package_json_run_command(root: Path, *, prefer_bun: bool) -> InferredRunCommand | None:
    package_json = root / "package.json"
    try:
        payload = json.loads(package_json.read_text())
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    scripts_obj = payload.get("scripts")
    if not isinstance(scripts_obj, dict):
        return None

    runner = "bun" if prefer_bun else "npm"
    reasons: list[str] = []
    if prefer_bun:
        reasons.append("bun lockfile detected")
    else:
        reasons.append("package.json detected")

    for script_name in ("dev", "start", "serve"):
        script = scripts_obj.get(script_name)
        if isinstance(script, str) and script.strip():
            reasons.append(f'package.json script "{script_name}" detected')
            return InferredRunCommand(
                command=(runner, "run", script_name),
                reasons=tuple(reasons),
            )
    return None


def _infer_pyproject_run_command(root: Path) -> InferredRunCommand | None:
    """Infer a runnable entrypoint from `pyproject.toml` metadata."""

    pyproject = root / "pyproject.toml"
    try:
        payload = tomllib.loads(pyproject.read_text())
    except Exception:
        return None

    project_obj = payload.get("project")
    if isinstance(project_obj, dict):
        scripts_obj = project_obj.get("scripts")
        if isinstance(scripts_obj, dict) and len(scripts_obj) == 1:
            script_name = next(iter(scripts_obj))
            if isinstance(script_name, str) and script_name:
                return InferredRunCommand(
                    command=("uv", "run", script_name),
                    reasons=("standalone Python project detected", f'project.scripts entry "{script_name}" detected'),
                )
        project_name = project_obj.get("name")
        if isinstance(project_name, str) and project_name:
            module_name = project_name.replace("-", "_")
            if (root / module_name).is_dir() or (root / "src" / module_name).is_dir():
                return InferredRunCommand(
                    command=("uv", "run", "python", "-m", module_name),
                    reasons=("standalone Python project detected", f'Python module "{module_name}" detected'),
                )

    tool_obj = payload.get("tool")
    if isinstance(tool_obj, dict):
        poetry_obj = tool_obj.get("poetry")
        if isinstance(poetry_obj, dict):
            scripts_obj = poetry_obj.get("scripts")
            if isinstance(scripts_obj, dict) and len(scripts_obj) == 1:
                script_name = next(iter(scripts_obj))
                if isinstance(script_name, str) and script_name:
                    return InferredRunCommand(
                        command=("poetry", "run", script_name),
                        reasons=("Poetry script entry detected",),
                    )
    return None


def _infer_cargo_run_command(root: Path) -> InferredRunCommand | None:
    """Infer a runnable cargo entrypoint from `Cargo.toml` and repo layout."""

    cargo_toml = root / "Cargo.toml"
    try:
        payload = tomllib.loads(cargo_toml.read_text())
    except Exception:
        return None

    package_name: str | None = None
    package_obj = payload.get("package")
    if isinstance(package_obj, dict):
        package_name_obj = package_obj.get("name")
        if isinstance(package_name_obj, str) and package_name_obj:
            package_name = package_name_obj

    if (root / "src" / "main.rs").is_file():
        reasons = ["Cargo.toml detected", "src/main.rs detected"]
        if package_name:
            reasons.append(f'cargo package "{package_name}" detected')
        return InferredRunCommand(command=("cargo", "run"), reasons=tuple(reasons))

    bins_obj = payload.get("bin")
    if isinstance(bins_obj, list) and len(bins_obj) == 1 and isinstance(bins_obj[0], dict):
        bin_name = bins_obj[0].get("name")
        if isinstance(bin_name, str) and bin_name:
            return InferredRunCommand(
                command=("cargo", "run", "--bin", bin_name),
                reasons=("Cargo.toml detected", f'cargo bin "{bin_name}" detected'),
            )
    return None


def resolve_sesame_command() -> list[str]:
    """Resolve the sesame CLI from env, PATH, or common local build locations."""

    env_bin = os.environ.get("DEN_SESAME_BIN", "").strip()
    candidates = [
        env_bin if env_bin else None,
        shutil.which("sesame"),
        str(Path.home() / "sesame" / "target" / "release" / "sesame"),
        str(Path.home() / "sesame" / "target" / "debug" / "sesame"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return [candidate]
    if shutil.which("sesame"):
        return ["sesame"]
    raise FileNotFoundError("sesame executable not found")


def discover_porkbun_domains_from_sesame_config(config_path: Path | None = None) -> list[str]:
    """Best-effort fallback for discovering Porkbun domains from sesame config."""

    path = config_path or Path.home() / ".config" / "sesame" / "config.toml"
    if not path.exists():
        return []

    with path.open("rb") as handle:
        config = tomllib.load(handle)

    profile_name = config.get("default_profile")
    profiles = config.get("profiles")
    if not isinstance(profile_name, str) or not isinstance(profiles, dict):
        return []
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        return []

    api_key = profile.get("api_key")
    secret_api_key = profile.get("secret_api_key")
    base_url = profile.get("base_url", "https://api.porkbun.com/api/json/v3")
    if not all(isinstance(value, str) and value for value in (api_key, secret_api_key, base_url)):
        return []

    payload = {
        "apikey": api_key,
        "secretapikey": secret_api_key,
        "start": 0,
        "includeLabels": "yes",
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/domain/listAll",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode()
    except Exception:
        return []

    try:
        payload_obj = json.loads(body)
    except Exception:
        return []
    if not isinstance(payload_obj, dict):
        return []
    domains_obj = payload_obj.get("domains")
    if not isinstance(domains_obj, list):
        return []

    domains: list[str] = []
    for row in domains_obj:
        if not isinstance(row, dict):
            continue
        domain = row.get("domain")
        if isinstance(domain, str) and domain:
            domains.append(domain)
    return domains


@dataclass(frozen=True)
class SpriteUrlInfo:
    """Structured view of `sprite url` output."""

    url: str | None
    auth: str | None


def parse_sprite_url(output: str) -> str | None:
    """Extract the canonical URL line from `sprite url` output."""

    return parse_sprite_url_info(output).url


def parse_sprite_url_info(output: str) -> SpriteUrlInfo:
    """Extract both URL and auth mode from `sprite url` output."""

    url: str | None = None
    auth: str | None = None
    for line in output.splitlines():
        if line.startswith("URL:"):
            candidate = line.removeprefix("URL:").strip()
            parsed = urlparse(candidate)
            if parsed.scheme and parsed.netloc:
                url = candidate
        elif line.startswith("Auth:"):
            auth = line.removeprefix("Auth:").strip() or None
    return SpriteUrlInfo(url=url, auth=auth)


def find_checkpoint_version_in_api_output(output: str, comment: str) -> str | None:
    """Find a checkpoint/version id in Sprite API JSON by matching the comment tag."""

    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None

    for record in _iter_checkpoint_records(payload):
        record_comment = record.get("comment")
        if record_comment != comment:
            continue

        for key in ("id", "version", "version_id", "checkpoint_id"):
            value = record.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _iter_checkpoint_records(payload: object) -> list[Mapping[str, object]]:
    """Flatten plausible checkpoint record containers returned by Sprite APIs."""

    records: list[Mapping[str, object]] = []
    if isinstance(payload, Mapping):
        records.append(payload)
        for key in ("checkpoints", "items", "data", "results"):
            nested = payload.get(key)
            if isinstance(nested, list):
                for entry in nested:
                    if isinstance(entry, Mapping):
                        records.extend(_iter_checkpoint_records(entry))
    elif isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, Mapping):
                records.extend(_iter_checkpoint_records(entry))
    return records


def find_checkpoint_version_in_list_output(output: str, comment: str) -> str | None:
    """Find a checkpoint id in `sprite checkpoint list` text output by comment match."""

    for line in output.splitlines():
        stripped = line.strip()
        if comment not in stripped:
            continue
        parts = stripped.split()
        if parts:
            return parts[0]
    return None


def split_custom_domain(host: str, owned_domains: Collection[str] | None = None) -> tuple[str, str | None]:
    """Split a host into Porkbun zone and optional subdomain.

    When owned domains are provided, the longest owned suffix wins so nested
    zones like `dev.example.com` are preferred over a naive two-label split.
    """

    normalized = host.strip().strip(".").lower()
    labels = [label for label in normalized.split(".") if label]
    if len(labels) < 2:
        raise ValueError(f"invalid host: {host}")

    zone: str | None = None
    if owned_domains:
        normalized_domains = sorted({domain.strip(".").lower() for domain in owned_domains if domain}, key=len, reverse=True)
        for candidate in normalized_domains:
            if normalized == candidate or normalized.endswith(f".{candidate}"):
                zone = candidate
                break
    if zone is None:
        zone = ".".join(labels[-2:])

    if normalized == zone:
        return zone, None
    return zone, normalized[: -(len(zone) + 1)]


def resolve_custom_domain(
    host: str,
    provider_domains: Mapping[DomainProvider, Collection[str]],
) -> DomainMatch:
    """Resolve which provider owns a host by longest matching configured zone.

    The domain authority should be selected by who actually holds the zone, not
    by a user preference. When multiple providers claim the same longest suffix,
    the result is treated as ambiguous and must be resolved explicitly.
    """

    normalized = host.strip().strip(".").lower()
    labels = [label for label in normalized.split(".") if label]
    if len(labels) < 2:
        raise ValueError(f"invalid host: {host}")

    matches: list[tuple[int, DomainProvider, str]] = []
    for provider, domains in provider_domains.items():
        for domain in domains:
            candidate = domain.strip().strip(".").lower()
            if not candidate:
                continue
            if normalized == candidate or normalized.endswith(f".{candidate}"):
                matches.append((len(candidate), provider, candidate))

    if not matches:
        raise ValueError(
            f"Could not determine who holds {normalized}. Configure the owning zone in Cloudflare or sesame/Porkbun, or override the domain provider explicitly."
        )

    matches.sort(key=lambda item: item[0], reverse=True)
    best_len = matches[0][0]
    best = [entry for entry in matches if entry[0] == best_len]
    unique = {(provider, zone) for _, provider, zone in best}
    if len(unique) != 1:
        providers = ", ".join(sorted(provider.value for provider, _ in unique))
        raise ValueError(f"Ambiguous domain ownership for {normalized}; matching zones found in: {providers}")

    _, provider, zone = best[0]
    subdomain = None if normalized == zone else normalized[: -(len(zone) + 1)]
    return DomainMatch(provider=provider, zone=zone, subdomain=subdomain)


def build_sesame_url_forward_command(custom_domain: str, target_url: str, owned_domains: Collection[str]) -> list[str]:
    """Build the sesame command for a URL forward using resolved owned zones."""

    match = resolve_custom_domain(custom_domain, {DomainProvider.sesame: owned_domains})
    command = [
        "domain",
        "add-url-forward",
        match.zone,
        "--location",
        target_url,
        "--type",
        "permanent",
        "--include-path",
        "yes",
    ]
    if match.subdomain:
        command.extend(["--subdomain", match.subdomain])
    return command


def _load_porkbun_creds(config_path: Path | None = None) -> tuple[str, str, str]:
    """Load Porkbun API credentials from the sesame config file.

    Returns (api_key, secret_api_key, base_url).
    """
    path = config_path or Path.home() / ".config" / "sesame" / "config.toml"
    if not path.exists():
        raise FileNotFoundError(f"sesame config not found at {path}; cannot call Porkbun API directly")

    with path.open("rb") as handle:
        config = tomllib.load(handle)

    profile_name = config.get("default_profile")
    profiles = config.get("profiles")
    if not isinstance(profile_name, str) or not isinstance(profiles, dict):
        raise ValueError("sesame config is missing default_profile or profiles")
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        raise ValueError(f"sesame config profile {profile_name!r} not found")

    api_key = profile.get("api_key")
    secret_api_key = profile.get("secret_api_key")
    base_url = profile.get("base_url", "https://api.porkbun.com/api/json/v3")
    if not isinstance(api_key, str) or not isinstance(secret_api_key, str):
        raise ValueError("sesame config is missing api_key or secret_api_key")
    if not isinstance(base_url, str):
        base_url = "https://api.porkbun.com/api/json/v3"
    return api_key, secret_api_key, base_url


def _porkbun_api(base_url: str, path: str, api_key: str, secret_api_key: str, extra: dict[str, object] | None = None) -> dict[str, object]:
    """Make an authenticated Porkbun API call and return the parsed response."""
    payload: dict[str, object] = {"apikey": api_key, "secretapikey": secret_api_key}
    if extra:
        payload.update(extra)
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode()
    try:
        result = json.loads(body)
    except Exception as exc:
        raise ValueError(f"Porkbun API returned non-JSON: {body}") from exc
    if not isinstance(result, dict):
        raise ValueError(f"Porkbun API returned unexpected shape: {body}")
    if result.get("status") != "SUCCESS":
        raise ValueError(f"Porkbun API error: {result.get('message', body)}")
    return result


def porkbun_add_url_forward(
    custom_domain: str,
    target_url: str,
    owned_domains: Collection[str],
    config_path: Path | None = None,
) -> None:
    """Add a Porkbun URL forward directly via the API using credentials from the sesame config.

    This is a fallback for when the sesame CLI is not installed.
    """
    match = resolve_custom_domain(custom_domain, {DomainProvider.sesame: owned_domains})
    api_key, secret_api_key, base_url = _load_porkbun_creds(config_path)
    _porkbun_api(
        base_url,
        f"domain/addUrlForward/{match.zone}",
        api_key,
        secret_api_key,
        {
            "subdomain": match.subdomain or "",
            "location": target_url,
            "type": "permanent",
            "includePath": "yes",
            "wildcard": "no",
        },
    )


def porkbun_upsert_dns_records(
    zone: str,
    records: list[DnsRecord],
    config_path: Path | None = None,
) -> list[tuple[str, DnsRecord]]:
    """Create or update Porkbun DNS records directly via the API.

    Returns a list of (action, record) pairs where action is 'created' or 'updated'.
    This is a fallback for when the sesame CLI is not installed.
    """
    api_key, secret_api_key, base_url = _load_porkbun_creds(config_path)
    applied: list[tuple[str, DnsRecord]] = []

    for record in records:
        subdomain = None if record.name in ("@", "") else record.name
        subdomain_path = subdomain or ""

        retrieve_result = _porkbun_api(
            base_url,
            f"dns/retrieveByNameType/{zone}/{record.type}/{subdomain_path}",
            api_key,
            secret_api_key,
        )
        existing = retrieve_result.get("records")
        has_records = isinstance(existing, list) and len(existing) > 0

        if has_records:
            _porkbun_api(
                base_url,
                f"dns/editByNameType/{zone}/{record.type}/{subdomain_path}",
                api_key,
                secret_api_key,
                {"content": record.content, "ttl": "300"},
            )
            applied.append(("updated", record))
        else:
            _porkbun_api(
                base_url,
                f"dns/create/{zone}",
                api_key,
                secret_api_key,
                {"name": subdomain_path, "type": record.type, "content": record.content, "ttl": "300"},
            )
            applied.append(("created", record))

    return applied


def _sesame_record_subdomain(name: str) -> str | None:
    normalized = name.strip().strip(".").lower()
    return None if normalized in {"", "@"} else normalized


def build_sesame_dns_list_command(zone: str, record: DnsRecord) -> list[str]:
    """Build the sesame command for listing matching DNS records."""

    command = ["dns", "list-by-name-type", zone, "--type", record.type, "--json"]
    subdomain = _sesame_record_subdomain(record.name)
    if subdomain:
        command.extend(["--subdomain", subdomain])
    return command


def build_sesame_dns_create_command(zone: str, record: DnsRecord) -> list[str]:
    """Build the sesame command for creating a DNS record."""

    command = ["dns", "create", zone, "--type", record.type, "--content", record.content, "--json"]
    subdomain = _sesame_record_subdomain(record.name)
    if subdomain:
        command.extend(["--name", subdomain])
    return command


def build_sesame_dns_edit_command(zone: str, record: DnsRecord) -> list[str]:
    """Build the sesame command for editing matching DNS records."""

    command = ["dns", "edit-by-name-type", zone, "--type", record.type, "--content", record.content, "--json"]
    subdomain = _sesame_record_subdomain(record.name)
    if subdomain:
        command.extend(["--subdomain", subdomain])
    return command


def sesame_dns_records_exist(payload: object) -> bool:
    """Return whether sesame list output contains any matching DNS records."""

    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return any(isinstance(entry, Mapping) for entry in payload)
    if isinstance(payload, Mapping):
        records = payload.get("records")
        if isinstance(records, Sequence) and not isinstance(records, (str, bytes, bytearray)):
            return any(isinstance(entry, Mapping) for entry in records)
    return False


def cloudflare_api_token() -> str | None:
    """Return a configured Cloudflare API token if one is available."""

    for key in ("DEN_CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def resolve_flyctl_command() -> list[str]:
    """Resolve the Fly CLI command with local fallbacks."""

    for candidate in ("flyctl", "fly"):
        path = shutil.which(candidate)
        if path:
            return [path]

    fallback = Path.home() / ".fly" / "bin" / "flyctl"
    if fallback.is_file():
        return [str(fallback)]
    raise FileNotFoundError("flyctl executable not found")


def resolve_railway_command() -> list[str]:
    """Resolve the Railway CLI command with local fallbacks."""

    path = shutil.which("railway")
    if path:
        return [path]
    fallback = Path.home() / ".local" / "share" / "mise" / "installs" / "railway" / "4.37.2" / "railway"
    if fallback.is_file():
        return [str(fallback)]
    raise FileNotFoundError("railway executable not found")


def railway_status_command() -> list[str]:
    """Build the Railway argv for linked-project status inspection."""

    return resolve_railway_command() + ["status", "--json"]


def railway_list_command() -> list[str]:
    """Build the Railway argv for project inventory."""

    return resolve_railway_command() + ["list", "--json"]


def railway_delete_command(project: str, *, yes: bool = True, json_output: bool = True) -> list[str]:
    """Build the Railway argv for deleting a project by explicit name or ID."""

    command = resolve_railway_command() + ["delete", "-p", project]
    if yes:
        command.append("-y")
    if json_output:
        command.append("--json")
    return command


def fly_certs_add_command(app_name: str, hostname: str) -> list[str]:
    return resolve_flyctl_command() + ["certs", "add", hostname, "--app", app_name, "--json"]


def fly_certs_check_command(app_name: str, hostname: str) -> list[str]:
    return resolve_flyctl_command() + ["certs", "check", hostname, "--app", app_name, "--json"]


def fly_certs_setup_command(app_name: str, hostname: str) -> list[str]:
    return resolve_flyctl_command() + ["certs", "setup", hostname, "--app", app_name, "--json"]


def railway_domain_attach_command(service: str, domain: str, *, port: int | None = None) -> list[str]:
    command = resolve_railway_command() + ["domain", domain, "--service", service, "--json"]
    if port is not None:
        command.extend(["--port", str(port)])
    return command


def parse_railway_projects(payload: object) -> list[RailwayProjectSummary]:
    """Extract Railway projects from `railway list --json` output."""

    if not isinstance(payload, list):
        raise ValueError("Railway list response was not a JSON array")

    projects: list[RailwayProjectSummary] = []
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        name = row.get("name")
        if not isinstance(name, str) or not name:
            continue
        project_id = row.get("id")
        if not isinstance(project_id, str) or not project_id:
            project_id = None

        workspace_name: str | None = None
        workspace_obj = row.get("workspace")
        if isinstance(workspace_obj, Mapping):
            workspace_value = workspace_obj.get("name")
            if isinstance(workspace_value, str) and workspace_value:
                workspace_name = workspace_value

        projects.append(
            RailwayProjectSummary(
                name=name,
                project_id=project_id,
                workspace_name=workspace_name,
            )
        )
    return projects


def extract_railway_linked_project_name(payload: object) -> str | None:
    """Best-effort extraction of the linked Railway project name from status JSON."""

    if not isinstance(payload, Mapping):
        return None

    project_obj = payload.get("project")
    if isinstance(project_obj, Mapping):
        project_name = project_obj.get("name")
        if isinstance(project_name, str) and project_name:
            return project_name

    name = payload.get("name")
    has_project_shape = any(key in payload for key in ("environments", "services", "workspace"))
    if has_project_shape and isinstance(name, str) and name:
        return name
    return None


def parse_railway_service_statuses(payload: object) -> list[RailwayServiceStatusSummary]:
    """Extract service-level status summaries from Railway status JSON."""

    if not isinstance(payload, Mapping):
        return []

    environments_obj = payload.get("environments")
    if not isinstance(environments_obj, Mapping):
        return []
    environment_edges = environments_obj.get("edges")
    if not isinstance(environment_edges, list):
        return []

    services: list[RailwayServiceStatusSummary] = []
    for environment_row in environment_edges:
        if not isinstance(environment_row, Mapping):
            continue
        environment_node = environment_row.get("node")
        if not isinstance(environment_node, Mapping):
            continue
        instances_obj = environment_node.get("serviceInstances")
        if not isinstance(instances_obj, Mapping):
            continue
        instance_edges = instances_obj.get("edges")
        if not isinstance(instance_edges, list):
            continue

        for instance_row in instance_edges:
            if not isinstance(instance_row, Mapping):
                continue
            instance_node = instance_row.get("node")
            if not isinstance(instance_node, Mapping):
                continue
            name = instance_node.get("serviceName")
            if not isinstance(name, str) or not name:
                continue

            service_id = instance_node.get("serviceId")
            if not isinstance(service_id, str) or not service_id:
                service_id = None
            instance_id = instance_node.get("id")
            if not isinstance(instance_id, str) or not instance_id:
                instance_id = None

            latest_deployment = instance_node.get("latestDeployment")
            latest_deployment_id: str | None = None
            latest_deployment_status: str | None = None
            deployment_stopped: bool | None = None
            if isinstance(latest_deployment, Mapping):
                deployment_id = latest_deployment.get("id")
                if isinstance(deployment_id, str) and deployment_id:
                    latest_deployment_id = deployment_id
                deployment_status = latest_deployment.get("status")
                if isinstance(deployment_status, str) and deployment_status:
                    latest_deployment_status = deployment_status
                stopped = latest_deployment.get("deploymentStopped")
                if isinstance(stopped, bool):
                    deployment_stopped = stopped

            services.append(
                RailwayServiceStatusSummary(
                    name=name,
                    service_id=service_id,
                    instance_id=instance_id,
                    latest_deployment_id=latest_deployment_id,
                    latest_deployment_status=latest_deployment_status,
                    deployment_stopped=deployment_stopped,
                )
            )
    return services


def parse_railway_dns_records(host: str, zone: str, payload: Mapping[str, object], *, proxied: bool = False) -> list[DnsRecord]:
    """Extract desired DNS records from Railway domain JSON payload."""

    raw_records = payload.get("dnsRecords")
    if not isinstance(raw_records, list):
        status = payload.get("status")
        if isinstance(status, Mapping):
            raw_records = status.get("dnsRecords")
    if not isinstance(raw_records, list):
        raise ValueError("Railway domain response did not include dnsRecords")

    normalized_zone = zone.strip().strip(".").lower()
    normalized_host = host.strip().strip(".").lower()
    desired_name = "@" if normalized_host == normalized_zone else normalized_host[: -(len(normalized_zone) + 1)]

    records: list[DnsRecord] = []
    for row in raw_records:
        if not isinstance(row, Mapping):
            continue
        record_type = row.get("type")
        raw_name = row.get("name")
        target = row.get("target")
        value = row.get("value")
        content = target if isinstance(target, str) and target else value
        if not isinstance(record_type, str) or not isinstance(content, str) or not content:
            continue
        name = desired_name
        if isinstance(raw_name, str) and raw_name:
            normalized_name = raw_name.strip().strip(".").lower()
            if normalized_name == normalized_zone:
                name = "@"
            elif normalized_name.endswith(f".{normalized_zone}"):
                name = normalized_name[: -(len(normalized_zone) + 1)] or "@"
            else:
                name = normalized_name
        records.append(
            DnsRecord(
                type=record_type.upper(),
                name=name,
                content=content.rstrip("."),
                proxied=proxied if record_type.upper() in {"A", "AAAA", "CNAME"} else False,
            )
        )

    if not records:
        raise ValueError("Railway domain response did not produce any DNS records")
    return records


def discover_cloudflare_domains() -> list[str]:
    """Discover Cloudflare-managed zones via the Cloudflare v4 API.

    This is intentionally read-only discovery. If no token is configured or the
    API response is unavailable, return an empty list so callers can continue
    with other domain providers.
    """

    token = cloudflare_api_token()
    if not token:
        return []

    zones: list[str] = []
    page = 1
    while page <= 10:
        query = urllib.parse.urlencode({"page": page, "per_page": 50, "order": "name", "direction": "asc"})
        request = urllib.request.Request(
            f"https://api.cloudflare.com/client/v4/zones?{query}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.load(response)
        except Exception:
            return []

        if not isinstance(payload, Mapping) or payload.get("success") is not True:
            return []
        result = payload.get("result")
        if not isinstance(result, list) or not result:
            break

        for row in result:
            if not isinstance(row, Mapping):
                continue
            zone_name = row.get("name")
            if isinstance(zone_name, str) and zone_name:
                zones.append(zone_name.strip().strip(".").lower())

        result_info = payload.get("result_info")
        if not isinstance(result_info, Mapping):
            break
        total_pages = result_info.get("total_pages")
        if not isinstance(total_pages, int) or page >= total_pages:
            break
        page += 1

    return sorted(set(zones))


def _normalize_dns_name(name: str, zone: str) -> str:
    normalized = name.strip().rstrip(".").lower()
    normalized_zone = zone.strip().rstrip(".").lower()
    if normalized == normalized_zone:
        return "@"
    suffix = f".{normalized_zone}"
    if normalized.endswith(suffix):
        prefix = normalized[: -len(suffix)]
        return prefix.rstrip(".") or "@"
    return normalized


def build_cloudflare_dns_records(host: str, zone: str, dns_requirements: Mapping[str, object], *, proxied: bool = False) -> list[DnsRecord]:
    """Build desired Cloudflare DNS records from Fly-style dns_requirements."""

    normalized_host = host.strip().strip(".").lower()
    normalized_zone = zone.strip().strip(".").lower()
    is_apex = normalized_host == normalized_zone
    records: list[DnsRecord] = []

    ownership = dns_requirements.get("ownership")
    if isinstance(ownership, Mapping):
        ownership_name = ownership.get("name")
        ownership_value = ownership.get("app_value") or ownership.get("org_value")
        if isinstance(ownership_name, str) and isinstance(ownership_value, str):
            records.append(DnsRecord(type="TXT", name=_normalize_dns_name(ownership_name, normalized_zone), content=ownership_value))

    if is_apex:
        a_values = dns_requirements.get("a")
        if isinstance(a_values, list):
            for value in a_values:
                if isinstance(value, str) and value:
                    records.append(DnsRecord(type="A", name="@",
                                             content=value, proxied=proxied))
        aaaa_values = dns_requirements.get("aaaa")
        if isinstance(aaaa_values, list):
            for value in aaaa_values:
                if isinstance(value, str) and value:
                    records.append(DnsRecord(type="AAAA", name="@",
                                             content=value, proxied=proxied))
    else:
        cname_value = dns_requirements.get("cname")
        if isinstance(cname_value, str) and cname_value:
            records.append(DnsRecord(type="CNAME", name=_normalize_dns_name(normalized_host, normalized_zone), content=cname_value.rstrip("."), proxied=proxied))
        else:
            a_values = dns_requirements.get("a")
            if isinstance(a_values, list):
                for value in a_values:
                    if isinstance(value, str) and value:
                        records.append(DnsRecord(type="A", name=_normalize_dns_name(normalized_host, normalized_zone), content=value, proxied=proxied))
            aaaa_values = dns_requirements.get("aaaa")
            if isinstance(aaaa_values, list):
                for value in aaaa_values:
                    if isinstance(value, str) and value:
                        records.append(DnsRecord(type="AAAA", name=_normalize_dns_name(normalized_host, normalized_zone), content=value, proxied=proxied))

    seen: set[tuple[str, str, str, bool]] = set()
    deduped: list[DnsRecord] = []
    for record in records:
        key = (record.type, record.name, record.content, record.proxied)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def parse_fly_dns_records(host: str, zone: str, payload: Mapping[str, object], *, proxied: bool = False) -> list[DnsRecord]:
    """Extract desired DNS records from Fly certificate JSON payload."""

    requirements = payload.get("dns_requirements")
    if not isinstance(requirements, Mapping):
        raise ValueError("Fly certificate response did not include dns_requirements")
    records = build_cloudflare_dns_records(host, zone, requirements, proxied=proxied)
    if not records:
        raise ValueError("Fly certificate response did not produce any DNS records")
    return records


def upsert_cloudflare_dns_records(zone: str, records: Sequence[DnsRecord]) -> list[dict[str, object]]:
    """Create or update Cloudflare DNS records for a zone."""

    token = cloudflare_api_token()
    if not token:
        raise ValueError("Cloudflare API token not configured")

    zone_name = zone.strip().strip(".").lower()

    def _request(path: str, *, method: str = "GET", payload: Mapping[str, object] | None = None) -> Mapping[str, object]:
        request = urllib.request.Request(
            f"https://api.cloudflare.com/client/v4{path}",
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload).encode() if payload is not None else None,
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.load(response)
        if not isinstance(body, Mapping) or body.get("success") is not True:
            raise ValueError(f"Cloudflare API request failed for {path}")
        return body

    zones = _request(f"/zones?{urllib.parse.urlencode({'name': zone_name})}")
    result = zones.get("result")
    if not isinstance(result, list) or not result:
        raise ValueError(f"Cloudflare zone not found: {zone_name}")
    zone_row = result[0]
    if not isinstance(zone_row, Mapping):
        raise ValueError(f"Cloudflare zone lookup returned malformed result for {zone_name}")
    zone_id = zone_row.get("id")
    if not isinstance(zone_id, str) or not zone_id:
        raise ValueError(f"Cloudflare zone lookup did not include an id for {zone_name}")

    applied: list[dict[str, object]] = []
    for record in records:
        fqdn = zone_name if record.name == "@" else f"{record.name}.{zone_name}"
        existing_resp = _request(
            f"/zones/{zone_id}/dns_records?{urllib.parse.urlencode({'type': record.type, 'name': fqdn})}"
        )
        existing_rows = existing_resp.get("result")
        payload: dict[str, object] = {
            "type": record.type,
            "name": fqdn,
            "content": record.content,
        }
        if record.type in {"A", "AAAA", "CNAME"}:
            payload["proxied"] = record.proxied
        if isinstance(existing_rows, list) and existing_rows:
            first = existing_rows[0]
            if not isinstance(first, Mapping):
                raise ValueError(f"Cloudflare DNS record lookup returned malformed result for {fqdn}")
            record_id = first.get("id")
            if not isinstance(record_id, str) or not record_id:
                raise ValueError(f"Cloudflare DNS record lookup did not include an id for {fqdn}")
            response = _request(f"/zones/{zone_id}/dns_records/{record_id}", method="PUT", payload=payload)
            action = "updated"
        else:
            response = _request(f"/zones/{zone_id}/dns_records", method="POST", payload=payload)
            action = "created"
        applied.append({"action": action, "record": payload, "response": response})
    return applied


def extract_den_peers(status_payload: Mapping[str, object]) -> list[DenPeer]:
    """Extract and sort den-related peers from a raw Tailscale status payload."""

    peers_obj = status_payload.get("Peer")
    if not isinstance(peers_obj, Mapping):
        return []

    peers: list[DenPeer] = []
    for raw_peer in peers_obj.values():
        if not isinstance(raw_peer, Mapping):
            continue

        host_name_obj = raw_peer.get("HostName")
        if not isinstance(host_name_obj, str):
            continue
        if not host_name_obj.startswith("den-"):
            continue

        ip = "-"
        ips_obj = raw_peer.get("TailscaleIPs")
        if isinstance(ips_obj, list) and ips_obj:
            first = ips_obj[0]
            if isinstance(first, str):
                ip = first

        online = bool(raw_peer.get("Online", False))
        peers.append(DenPeer(host_name=host_name_obj, ip=ip, online=online))

    peers.sort(key=lambda peer: peer.host_name)
    return peers
