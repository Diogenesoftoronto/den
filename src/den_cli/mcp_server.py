from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Literal, TypedDict

from fastmcp import FastMCP

from den_cli.core import (
    DomainMode,
    DomainProvider,
    DnsRecord,
    RuntimeProvider,
    build_sesame_dns_create_command,
    build_sesame_dns_edit_command,
    build_sesame_dns_list_command,
    build_sesame_url_forward_command,
    discover_cloudflare_domains,
    discover_porkbun_domains_from_sesame_config,
    extract_railway_linked_project_name,
    find_checkpoint_version_in_api_output,
    find_checkpoint_version_in_list_output,
    make_sprite_redeploy_comment,
    parse_railway_service_statuses,
    fly_certs_add_command,
    normalize_den_name,
    parse_fly_dns_records,
    parse_railway_projects,
    parse_railway_dns_records,
    parse_sprite_url,
    railway_delete_command,
    railway_domain_attach_command,
    railway_list_command,
    railway_status_command,
    resolve_custom_domain,
    resolve_sesame_command,
    sesame_dns_records_exist,
    sprite_checkpoint_create_command,
    sprite_command,
    sprite_restore_command,
    upsert_cloudflare_dns_records,
)

PROJECT_DIR = Path.home() / "Projects" / "den"

mcp = FastMCP(
    name="den-mcp",
    instructions=(
        "Deep workflow MCP server for den. Use the smallest number of tool calls possible: "
        "provision_den for create/setup flows, operate_den for lifecycle actions, and "
        "diagnose_den for test and health checks."
    ),
)


class StepResult(TypedDict):
    step: str
    command: list[str]
    cwd: str
    ok: bool
    exit_code: int | None
    timed_out: bool
    duration_ms: int
    stdout: str
    stderr: str


class WorkflowError(TypedDict):
    kind: str
    message: str
    failing_step: str
    command: list[str]
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    remediation: list[str]


def _run_step(
    step: str,
    command: list[str],
    *,
    cwd: Path | None = PROJECT_DIR,
    timeout_s: int = 120,
    input_text: str | None = None,
) -> StepResult:
    started = time.monotonic()
    run_cwd = str(cwd) if cwd else str(Path.home())
    try:
        proc = subprocess.run(
            command,
            cwd=run_cwd,
            text=True,
            input=input_text,
            capture_output=True,
            check=False,
            timeout=timeout_s,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        return {
            "step": step,
            "command": command,
            "cwd": run_cwd,
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "timed_out": False,
            "duration_ms": duration_ms,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        timeout_stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        timeout_stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return {
            "step": step,
            "command": command,
            "cwd": run_cwd,
            "ok": False,
            "exit_code": None,
            "timed_out": True,
            "duration_ms": duration_ms,
            "stdout": timeout_stdout,
            "stderr": timeout_stderr or f"Timed out after {timeout_s}s",
        }


def _command_exists(cmd: str) -> bool:
    result = _run_step("check_command", ["bash", "-lc", f"command -v {cmd}"], cwd=None, timeout_s=15)
    return result["ok"]


def _sesame_command() -> list[str]:
    return resolve_sesame_command()


def _build_error(step: StepResult, message: str, remediation: list[str]) -> WorkflowError:
    return {
        "kind": "command_failure",
        "message": message,
        "failing_step": step["step"],
        "command": step["command"],
        "exit_code": step["exit_code"],
        "timed_out": step["timed_out"],
        "stdout": step["stdout"],
        "stderr": step["stderr"],
        "remediation": remediation,
    }


def _result(
    workflow: str,
    ok: bool,
    *,
    steps: list[StepResult],
    data: dict[str, Any] | None = None,
    error: WorkflowError | None = None,
    next_steps: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "workflow": workflow,
        "ok": ok,
        "data": data or {},
        "error": error,
        "next_steps": next_steps or [],
        "steps": steps,
    }


def _sesame_owned_domains() -> list[str]:
    try:
        command = _sesame_command() + ["domain", "list", "--all", "--json"]
    except FileNotFoundError:
        return discover_porkbun_domains_from_sesame_config()
    step = _run_step("sesame_domain_list", command, cwd=None, timeout_s=30)
    if not step["ok"] or not step["stdout"].strip():
        return discover_porkbun_domains_from_sesame_config()
    try:
        payload = json.loads(step["stdout"])
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
        DomainProvider.sesame: _sesame_owned_domains(),
    }


def _railway_list_step() -> StepResult:
    return _run_step("railway_list_projects", railway_list_command(), cwd=PROJECT_DIR, timeout_s=30)


def _railway_status_step() -> StepResult:
    return _run_step("railway_status", railway_status_command(), cwd=PROJECT_DIR, timeout_s=30)


def _sesame_url_forward_command(custom_domain: str, target_url: str) -> list[str]:
    provider_domains = _configured_domain_zones()
    match = resolve_custom_domain(custom_domain, provider_domains)
    if match.provider is DomainProvider.cloudflare:
        raise ValueError(
            f"{custom_domain} is held by Cloudflare. Use domain_mode='dns' for Cloudflare-managed zones; forward mode is reserved for sesame/Porkbun-hosted zones."
        )
    if match.provider is not DomainProvider.sesame:
        raise ValueError(f"Unsupported domain provider for {custom_domain}: {match.provider.value}")
    owned_domains = provider_domains[DomainProvider.sesame]
    return _sesame_command() + build_sesame_url_forward_command(custom_domain, target_url, owned_domains)


def _cloudflare_dns_attach_step(den_name: str, custom_domain: str, zone: str, *, proxied: bool) -> StepResult:
    add_step = _run_step(
        "fly_certs_add",
        fly_certs_add_command(den_name, custom_domain),
        cwd=PROJECT_DIR,
        timeout_s=60,
    )
    if not add_step["ok"]:
        return add_step

    try:
        payload = json.loads(add_step["stdout"])
        records = parse_fly_dns_records(custom_domain, zone, payload, proxied=proxied)
        applied = upsert_cloudflare_dns_records(zone, records)
    except (json.JSONDecodeError, ValueError) as exc:
        return {
            "step": "cloudflare_dns_upsert",
            "command": ["cloudflare-api", "dns-records", zone],
            "cwd": str(Path.home()),
            "ok": False,
            "exit_code": 1,
            "timed_out": False,
            "duration_ms": 0,
            "stdout": add_step["stdout"],
            "stderr": str(exc),
        }

    return {
        "step": "cloudflare_dns_upsert",
        "command": ["cloudflare-api", "dns-records", zone],
        "cwd": str(Path.home()),
        "ok": True,
        "exit_code": 0,
        "timed_out": False,
        "duration_ms": 0,
        "stdout": json.dumps(applied),
        "stderr": "",
    }


def _cloudflare_dns_attach_step_for_railway(service: str, custom_domain: str, zone: str, *, proxied: bool, port: int | None) -> StepResult:
    add_step = _run_step(
        "railway_domain_attach",
        railway_domain_attach_command(service, custom_domain, port=port),
        cwd=PROJECT_DIR,
        timeout_s=60,
    )
    if not add_step["ok"]:
        return add_step

    try:
        payload = json.loads(add_step["stdout"])
        records = parse_railway_dns_records(custom_domain, zone, payload, proxied=proxied)
        applied = upsert_cloudflare_dns_records(zone, records)
    except (json.JSONDecodeError, ValueError) as exc:
        return {
            "step": "cloudflare_dns_upsert",
            "command": ["cloudflare-api", "dns-records", zone],
            "cwd": str(Path.home()),
            "ok": False,
            "exit_code": 1,
            "timed_out": False,
            "duration_ms": 0,
            "stdout": add_step["stdout"],
            "stderr": str(exc),
        }

    return {
        "step": "cloudflare_dns_upsert",
        "command": ["cloudflare-api", "dns-records", zone],
        "cwd": str(Path.home()),
        "ok": True,
        "exit_code": 0,
        "timed_out": False,
        "duration_ms": 0,
        "stdout": json.dumps(applied),
        "stderr": "",
    }


def _sesame_dns_upsert_step(zone: str, records: list[DnsRecord]) -> StepResult:
    try:
        sesame_cmd = _sesame_command()
    except FileNotFoundError:
        return {
            "step": "sesame_dns_upsert",
            "command": ["sesame", "dns"],
            "cwd": str(Path.home()),
            "ok": False,
            "exit_code": None,
            "timed_out": False,
            "duration_ms": 0,
            "stdout": "",
            "stderr": "sesame is not on PATH and no local build was found",
        }

    applied: list[dict[str, object]] = []
    for record in records:
        lookup_step = _run_step(
            "sesame_dns_lookup",
            sesame_cmd + build_sesame_dns_list_command(zone, record),
            cwd=None,
            timeout_s=30,
        )
        if not lookup_step["ok"]:
            return lookup_step
        try:
            lookup_payload = json.loads(lookup_step["stdout"] or "[]")
        except json.JSONDecodeError as exc:
            return {
                "step": "sesame_dns_upsert",
                "command": sesame_cmd + build_sesame_dns_list_command(zone, record),
                "cwd": str(Path.home()),
                "ok": False,
                "exit_code": 1,
                "timed_out": False,
                "duration_ms": 0,
                "stdout": lookup_step["stdout"],
                "stderr": f"sesame returned malformed JSON while listing DNS records: {exc}",
            }

        if sesame_dns_records_exist(lookup_payload):
            command = sesame_cmd + build_sesame_dns_edit_command(zone, record)
            action = "updated"
        else:
            command = sesame_cmd + build_sesame_dns_create_command(zone, record)
            action = "created"

        write_step = _run_step("sesame_dns_upsert", command, cwd=None, timeout_s=30)
        if not write_step["ok"]:
            return write_step
        applied.append({"action": action, "record": {"type": record.type, "name": record.name, "content": record.content}})

    return {
        "step": "sesame_dns_upsert",
        "command": ["sesame", "dns", "upsert", zone],
        "cwd": str(Path.home()),
        "ok": True,
        "exit_code": 0,
        "timed_out": False,
        "duration_ms": 0,
        "stdout": json.dumps(applied),
        "stderr": "",
    }


def _sesame_dns_attach_step_for_railway(service: str, custom_domain: str, zone: str, *, port: int | None) -> StepResult:
    add_step = _run_step(
        "railway_domain_attach",
        railway_domain_attach_command(service, custom_domain, port=port),
        cwd=PROJECT_DIR,
        timeout_s=60,
    )
    if not add_step["ok"]:
        return add_step

    try:
        payload = json.loads(add_step["stdout"])
        records = parse_railway_dns_records(custom_domain, zone, payload, proxied=False)
    except (json.JSONDecodeError, ValueError) as exc:
        return {
            "step": "sesame_dns_upsert",
            "command": ["sesame", "dns", zone],
            "cwd": str(Path.home()),
            "ok": False,
            "exit_code": 1,
            "timed_out": False,
            "duration_ms": 0,
            "stdout": add_step["stdout"],
            "stderr": str(exc),
        }

    return _sesame_dns_upsert_step(zone, records)


@mcp.tool
def provision_den(
    name: str,
    backend: Literal["nix", "guix"] = "nix",
    tailscale_authkey: str | None = None,
    custom_domain: str | None = None,
    domain_mode: Literal["dns", "forward"] = "dns",
    proxied: bool = False,
    runtime: Literal["sprite", "railway"] = "sprite",
    port: int | None = None,
) -> dict[str, Any]:
    """Provision workflow: prerequisites + spawn + optional domain in one call."""
    del tailscale_authkey
    steps: list[StepResult] = []
    den_name = normalize_den_name(name)

    runtime_provider = RuntimeProvider(runtime)
    required_commands = ("sprite",) if runtime_provider is RuntimeProvider.sprite else ("railway",)
    for cmd in required_commands:
        exists = _command_exists(cmd)
        if not exists:
            return _result(
                "provision_den",
                False,
                steps=steps,
                error={
                    "kind": "missing_dependency",
                    "message": f"Required command not found: {cmd}",
                    "failing_step": "preflight",
                    "command": ["command", "-v", cmd],
                    "exit_code": None,
                    "timed_out": False,
                    "stdout": "",
                    "stderr": f"{cmd} is not on PATH",
                    "remediation": [
                        "Install the Sprite CLI and authenticate with Fly.",
                        "Retry provision_den after sprite list succeeds.",
                    ],
                },
            )

    if not PROJECT_DIR.is_dir():
        return _result(
            "provision_den",
            False,
            steps=steps,
            error={
                "kind": "missing_project",
                "message": f"den project directory not found: {PROJECT_DIR}",
                "failing_step": "preflight",
                "command": ["test", "-d", str(PROJECT_DIR)],
                "exit_code": None,
                "timed_out": False,
                "stdout": "",
                "stderr": "Project directory missing",
                "remediation": [
                    "Clone or restore ~/Projects/den.",
                    "Run the command again after restoring project files.",
                ],
            },
        )

    if runtime_provider is RuntimeProvider.sprite:
        sprite_auth = _run_step("sprite_list", sprite_command("list"), cwd=PROJECT_DIR, timeout_s=20)
        steps.append(sprite_auth)
        if not sprite_auth["ok"]:
            return _result(
                "provision_den",
                False,
                steps=steps,
                error=_build_error(
                    sprite_auth,
                    "Sprite authentication check failed.",
                    [
                        "Run: sprite login",
                        "Verify you can run: sprite list",
                        "Retry provision_den after successful login",
                    ],
                ),
            )
        command_plan: list[tuple[str, list[str], Path | None, int, str | None]] = [
            ("sprite_create", sprite_command("create", "-skip-console"), PROJECT_DIR, 180, f"{den_name}\n"),
        ]
    else:
        railway_status = _run_step("railway_status", ["railway", "status", "--json"], cwd=PROJECT_DIR, timeout_s=20)
        steps.append(railway_status)
        if not railway_status["ok"]:
            return _result(
                "provision_den",
                False,
                steps=steps,
                error=_build_error(
                    railway_status,
                    "Railway authentication or project check failed.",
                    [
                        "Run: railway login",
                        "Link the project directory with Railway if needed.",
                        "Retry provision_den after railway status succeeds.",
                    ],
                ),
            )
        command_plan = []

    for step_name, command, cwd, timeout_s, input_text in command_plan:
        step = _run_step(step_name, command, cwd=cwd, timeout_s=timeout_s, input_text=input_text)
        steps.append(step)
        if not step["ok"]:
            return _result(
                "provision_den",
                False,
                steps=steps,
                error=_build_error(
                    step,
                    f"Provisioning failed at {step_name}",
                    [
                        "Inspect stderr/stdout in this error payload.",
                        "Fix auth or provider state, then retry.",
                        f"Backend selection ({backend}) is informational in the current Sprite flow.",
                    ],
                ),
            )

    if custom_domain:
        if runtime_provider is RuntimeProvider.sprite:
            url_step = _run_step("sprite_url", sprite_command("url", sprite_name=den_name), cwd=PROJECT_DIR, timeout_s=20)
            steps.append(url_step)
            target_url = parse_sprite_url(url_step["stdout"]) if url_step["ok"] else None
            if not url_step["ok"] or not target_url:
                return _result(
                    "provision_den",
                    False,
                    steps=steps,
                    error=_build_error(
                        url_step,
                        "Provision succeeded but reading the Sprite URL failed.",
                        [
                            "Run sprite url manually for the target den.",
                            "Retry the domain operation after confirming the URL.",
                        ],
                    ),
                )

        mode = DomainMode(domain_mode)
        if mode is DomainMode.dns:
            provider_domains = _configured_domain_zones()
            match = resolve_custom_domain(custom_domain, provider_domains)
            if match.provider is DomainProvider.cloudflare:
                dns_step = (
                    _cloudflare_dns_attach_step(den_name, custom_domain, match.zone, proxied=proxied)
                    if runtime_provider is RuntimeProvider.sprite
                    else _cloudflare_dns_attach_step_for_railway(den_name, custom_domain, match.zone, proxied=proxied, port=port)
                )
                failure_message = "Provision succeeded but Cloudflare DNS attachment failed."
                remediation = [
                    "Verify Cloudflare API token access and Fly certificate attach state.",
                    "Retry the domain operation after fixing DNS or certificate requirements.",
                ]
            elif match.provider is DomainProvider.sesame and runtime_provider is RuntimeProvider.railway:
                dns_step = _sesame_dns_attach_step_for_railway(den_name, custom_domain, match.zone, port=port)
                failure_message = "Provision succeeded but Porkbun DNS attachment via sesame failed."
                remediation = [
                    "Verify sesame credentials and owned domain resolution.",
                    "Retry the domain operation after fixing Porkbun DNS access.",
                ]
            else:
                return _result(
                    "provision_den",
                    False,
                    steps=steps,
                    error={
                        "kind": "unsupported_action",
                        "message": f"DNS mode is not implemented yet for {match.provider.value}-held zones",
                        "failing_step": "domain_provider_dispatch",
                        "command": [],
                        "exit_code": None,
                        "timed_out": False,
                        "stdout": "",
                        "stderr": f"{custom_domain} is held by {match.provider.value}",
                        "remediation": [
                            "Use runtime='railway' to manage sesame/Porkbun DNS in dns mode.",
                            "Or move the zone to Cloudflare for managed DNS attachment.",
                        ],
                    },
                )
            steps.append(dns_step)
            failed_step = dns_step
        else:
            if runtime_provider is not RuntimeProvider.sprite:
                return _result(
                    "provision_den",
                    False,
                    steps=steps,
                    error={
                        "kind": "unsupported_action",
                        "message": "Forward mode is currently implemented for Sprite-backed runtimes only",
                        "failing_step": "runtime_provider_dispatch",
                        "command": [],
                        "exit_code": None,
                        "timed_out": False,
                        "stdout": "",
                        "stderr": f"runtime={runtime_provider.value}",
                        "remediation": [
                            "Use runtime='sprite' for forward mode.",
                            "Use domain_mode='dns' with Cloudflare-managed zones for Railway.",
                        ],
                    },
                )
            public_step = _run_step(
                "sprite_url_public",
                sprite_command("url", "update", "--auth", "public", sprite_name=den_name),
                cwd=PROJECT_DIR,
                timeout_s=30,
            )
            steps.append(public_step)
            if not public_step["ok"]:
                return _result(
                    "provision_den",
                    False,
                    steps=steps,
                    error=_build_error(
                        public_step,
                        "Provision succeeded but making the Sprite URL public failed.",
                        [
                            "Run sprite url update --auth public manually.",
                            "Retry the domain operation after the URL is public.",
                        ],
                    ),
                )

            sesame_step = _run_step(
                "sesame_add_url_forward",
                _sesame_url_forward_command(custom_domain, target_url or ""),
                cwd=None,
                timeout_s=60,
            )
            steps.append(sesame_step)
            failed_step = sesame_step
            failure_message = "Provision succeeded but adding the Porkbun URL forward failed."
            remediation = [
                "Verify sesame credentials and owned domain resolution.",
                "Retry operate_den(action='domain', ...).",
            ]
        if not failed_step["ok"]:
            return _result(
                "provision_den",
                False,
                steps=steps,
                error=_build_error(
                    failed_step,
                    failure_message,
                    remediation,
                ),
                data={"den_name": den_name, "backend": backend, "partial_success": True},
            )

    return _result(
        "provision_den",
        True,
        steps=steps,
        data={"den_name": den_name, "backend": backend, "custom_domain": custom_domain},
        next_steps=[
            f"den connect {den_name.removeprefix('den-')}",
            f"den status {den_name.removeprefix('den-')}",
        ],
    )


@mcp.tool
def operate_den(
    action: Literal["list", "redeploy", "destroy", "domain", "logs", "status"],
    name: str | None = None,
    custom_domain: str | None = None,
    service: str | None = None,
    confirm_destroy: bool = False,
    log_timeout_s: int = 20,
    domain_mode: Literal["dns", "forward"] = "dns",
    proxied: bool = False,
    runtime: Literal["sprite", "railway"] = "sprite",
    port: int | None = None,
) -> dict[str, Any]:
    """Operations workflow: Sprite lifecycle actions plus sesame-backed domains."""
    del log_timeout_s
    steps: list[StepResult] = []
    runtime_provider = RuntimeProvider(runtime)

    if action == "list":
        if runtime_provider is RuntimeProvider.sprite:
            list_step = _run_step("sprite_list_dens", sprite_command("list", "-prefix", "den-"), cwd=PROJECT_DIR, timeout_s=20)
            steps.append(list_step)
            if not list_step["ok"]:
                return _result(
                    "operate_den",
                    False,
                    steps=steps,
                    error=_build_error(
                        list_step,
                        "Failed to list dens from Sprite.",
                        [
                            "Ensure sprite is installed and authenticated.",
                            "Run sprite list manually.",
                            "Retry operate_den(action='list').",
                        ],
                    ),
                )
            dens = [line.strip() for line in list_step["stdout"].splitlines() if line.strip().startswith("den-")]
            return _result("operate_den", True, steps=steps, data={"runtime": runtime_provider.value, "dens": dens, "count": len(dens)})

        list_step = _railway_list_step()
        steps.append(list_step)
        if not list_step["ok"]:
            return _result(
                "operate_den",
                False,
                steps=steps,
                error=_build_error(
                    list_step,
                    "Failed to list Railway projects.",
                    [
                        "Ensure railway is installed and authenticated.",
                        "Run railway list --json manually.",
                        "Retry operate_den(action='list', runtime='railway').",
                    ],
                ),
            )
        try:
            payload = json.loads(list_step["stdout"])
            projects = parse_railway_projects(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            return _result(
                "operate_den",
                False,
                steps=steps,
                error={
                    "kind": "command_failure",
                    "message": "Railway project list returned malformed JSON.",
                    "failing_step": list_step["step"],
                    "command": list_step["command"],
                    "exit_code": list_step["exit_code"],
                    "timed_out": list_step["timed_out"],
                    "stdout": list_step["stdout"],
                    "stderr": str(exc),
                    "remediation": [
                        "Run railway list --json manually to inspect the payload.",
                        "Retry operate_den(action='list', runtime='railway') after fixing Railway auth or CLI state.",
                    ],
                },
            )
        dens = [project.name for project in projects if project.name.startswith("den-")]
        return _result("operate_den", True, steps=steps, data={"runtime": runtime_provider.value, "dens": dens, "count": len(dens)})

    # Note: redeploy is handled in the main action match below (line ~856)

    if not name:
        return _result(
            "operate_den",
            False,
            steps=steps,
            error={
                "kind": "invalid_input",
                "message": f"name is required for action={action}",
                "failing_step": "input_validation",
                "command": [],
                "exit_code": None,
                "timed_out": False,
                "stdout": "",
                "stderr": "Missing name",
                "remediation": [
                    f"Provide name, e.g. operate_den(action='{action}', name='myproject').",
                ],
            },
        )

    den_name = normalize_den_name(name)

    if action == "destroy":
        if not confirm_destroy:
            return _result(
                "operate_den",
                False,
                steps=steps,
                error={
                    "kind": "safety_check",
                    "message": "Destroy requested without confirm_destroy=true",
                    "failing_step": "safety_guard",
                    "command": sprite_command("destroy", "-force", sprite_name=den_name),
                    "exit_code": None,
                    "timed_out": False,
                    "stdout": "",
                    "stderr": "Operation blocked by safety guard",
                    "remediation": [
                        "Set confirm_destroy=true if deletion is intended.",
                        "Use action='list' first to verify target den.",
                    ],
                },
            )
        if runtime_provider is RuntimeProvider.sprite:
            step = _run_step("sprite_destroy", sprite_command("destroy", "-force", sprite_name=den_name), cwd=PROJECT_DIR, timeout_s=60)
        else:
            status_step = _railway_status_step()
            steps.append(status_step)
            if not status_step["ok"]:
                return _result(
                    "operate_den",
                    False,
                    steps=steps,
                    error=_build_error(
                        status_step,
                        "Railway destroy requires a linked project, but Railway status failed.",
                        [
                            "Run railway login and railway link in the den project directory.",
                            "Retry operate_den(action='destroy', runtime='railway', confirm_destroy=True).",
                        ],
                    ),
                )
            try:
                linked_payload = json.loads(status_step["stdout"])
            except json.JSONDecodeError:
                linked_payload = None
            linked_project = extract_railway_linked_project_name(linked_payload)
            if linked_project != den_name:
                return _result(
                    "operate_den",
                    False,
                    steps=steps,
                    error={
                        "kind": "safety_check",
                        "message": "Refusing Railway project deletion because the linked project does not match the requested den name.",
                        "failing_step": status_step["step"],
                        "command": status_step["command"],
                        "exit_code": status_step["exit_code"],
                        "timed_out": status_step["timed_out"],
                        "stdout": status_step["stdout"],
                        "stderr": status_step["stderr"] or f"linked_project={linked_project or 'unknown'} requested={den_name}",
                        "remediation": [
                            f"Link {PROJECT_DIR} to the intended Railway project ({den_name}) before retrying.",
                            "Or delete the Railway project manually if you intend to target a different linked project.",
                        ],
                    },
                )
            step = _run_step("railway_delete_project", railway_delete_command(den_name), cwd=PROJECT_DIR, timeout_s=60)
        steps.append(step)
    elif action == "redeploy":
        if runtime_provider is RuntimeProvider.sprite:
            comment = make_sprite_redeploy_comment(den_name, str(time.time_ns()))
            cp_step = _run_step("sprite_checkpoint_create", sprite_checkpoint_create_command(den_name, comment), cwd=PROJECT_DIR, timeout_s=60)
            steps.append(cp_step)
            if not cp_step["ok"]:
                return _result("operate_den", False, steps=steps, error=_build_error(cp_step, f"Checkpoint creation failed for {den_name}", ["Run sprite checkpoint list manually to verify.", "Ensure sprite CLI is authenticated."]))

            # Try API first, fall back to CLI list
            api_step = _run_step("sprite_api_list_checkpoints", sprite_command("api", "/checkpoints", sprite_name=den_name), cwd=PROJECT_DIR, timeout_s=30)
            steps.append(api_step)

            if api_step["ok"] and api_step["stdout"].strip():
                checkpoint_id = find_checkpoint_version_in_api_output(api_step["stdout"], comment)
            else:
                list_step = _run_step("sprite_checkpoint_list", sprite_command("checkpoint", "list", sprite_name=den_name), cwd=PROJECT_DIR, timeout_s=30)
                steps.append(list_step)
                checkpoint_id = find_checkpoint_version_in_list_output(list_step["stdout"], comment) if list_step["ok"] and list_step["stdout"].strip() else None

            if not checkpoint_id:
                return _result("operate_den", False, steps=steps, error={"kind": "checkpoint_not_found", "message": f"Checkpoint created for {den_name} but ID could not be determined. Run 'sprite checkpoint list' and 'sprite restore <id>' manually.", "failing_step": "checkpoint_lookup", "command": [], "exit_code": None, "timed_out": False, "stdout": "", "stderr": "", "remediation": ["Run sprite checkpoint list -s den_name manually.", "Then sprite restore <checkpoint_id> to complete redeploy."]})

            restore_step = _run_step("sprite_restore", sprite_restore_command(den_name, checkpoint_id), cwd=PROJECT_DIR, timeout_s=60)
            steps.append(restore_step)
            if not restore_step["ok"]:
                return _result("operate_den", False, steps=steps, error=_build_error(restore_step, f"Restore failed for {den_name}", ["Checkpoint was created. Run 'sprite restore <checkpoint_id>' manually."]))

            return _result("operate_den", True, steps=steps, data={"action": "redeploy", "den_name": den_name, "checkpoint_id": checkpoint_id})
        else:
            step = _run_step("railway_redeploy", ["railway", "redeploy", "-y", "--json"], cwd=PROJECT_DIR, timeout_s=60)
            steps.append(step)
            if not step["ok"]:
                return _result("operate_den", False, steps=steps, error=_build_error(step, "Railway redeploy failed", ["Ensure railway CLI is authenticated and linked to a project.", "Use railway login and railway link first."]))
            return _result("operate_den", True, steps=steps, data={"action": "redeploy", "den_name": den_name})
    elif action == "status":
        if runtime_provider is RuntimeProvider.sprite:
            step = _run_step("sprite_status", sprite_command("url", sprite_name=den_name), cwd=PROJECT_DIR, timeout_s=30)
        else:
            step = _railway_status_step()
        steps.append(step)
    else:
        if not custom_domain:
            return _result(
                "operate_den",
                False,
                steps=steps,
                error={
                    "kind": "invalid_input",
                    "message": "custom_domain is required for action=domain",
                    "failing_step": "input_validation",
                    "command": [],
                    "exit_code": None,
                    "timed_out": False,
                    "stdout": "",
                    "stderr": "Missing custom_domain",
                    "remediation": ["Provide custom_domain like dev.example.com"],
                },
            )

        target_url: str | None = None
        if runtime_provider is RuntimeProvider.sprite:
            url_step = _run_step("sprite_url", sprite_command("url", sprite_name=den_name), cwd=PROJECT_DIR, timeout_s=20)
            steps.append(url_step)
            target_url = parse_sprite_url(url_step["stdout"]) if url_step["ok"] else None
            if not url_step["ok"] or not target_url:
                return _result(
                    "operate_den",
                    False,
                    steps=steps,
                    error=_build_error(
                        url_step,
                        f"Action {action} failed for {den_name}",
                        [
                            "Use command, stdout, and stderr in this payload to debug.",
                            "Fix auth/state issues, then retry the same action.",
                        ],
                    ),
                )

        mode = DomainMode(domain_mode)
        if mode is DomainMode.dns:
            provider_domains = _configured_domain_zones()
            match = resolve_custom_domain(custom_domain, provider_domains)
            if match.provider is DomainProvider.cloudflare:
                domain_step = (
                    _cloudflare_dns_attach_step(den_name, custom_domain, match.zone, proxied=proxied)
                    if runtime_provider is RuntimeProvider.sprite
                    else _cloudflare_dns_attach_step_for_railway(den_name, custom_domain, match.zone, proxied=proxied, port=port)
                )
            elif match.provider is DomainProvider.sesame and runtime_provider is RuntimeProvider.sprite and target_url:
                from .core import porkbun_upsert_dns_records
                records = [DnsRecord(
                    name=match.subdomain or "",
                    type="ALIAS",
                    content=target_url,
                    proxied=False,
                )]
                applied = porkbun_upsert_dns_records(
                    zone=match.zone,
                    records=records,
                )
                domain_step = {
                    "step": "porkbun_dns_upsert",
                    "command": ["porkbun-api", "dns-records", match.zone],
                    "cwd": str(Path.home()),
                    "ok": True,
                    "exit_code": 0,
                    "timed_out": False,
                    "duration_ms": 0,
                    "stdout": json.dumps(applied),
                    "stderr": "",
                }
            elif match.provider is DomainProvider.sesame and runtime_provider is RuntimeProvider.railway:
                domain_step = _sesame_dns_attach_step_for_railway(den_name, custom_domain, match.zone, port=port)
            else:
                return _result(
                    "operate_den",
                    False,
                    steps=steps,
                    error={
                        "kind": "unsupported_action",
                        "message": f"DNS mode is not implemented yet for {match.provider.value}-held zones",
                        "failing_step": "domain_provider_dispatch",
                        "command": [],
                        "exit_code": None,
                        "timed_out": False,
                        "stdout": "",
                        "stderr": f"{custom_domain} is held by {match.provider.value}",
                        "remediation": [
                            "Use runtime='railway' to manage sesame/Porkbun DNS in dns mode.",
                            "Or move the zone to Cloudflare for managed DNS attachment.",
                        ],
                    },
                )
        else:
            if runtime_provider is not RuntimeProvider.sprite:
                return _result(
                    "operate_den",
                    False,
                    steps=steps,
                    error={
                        "kind": "unsupported_action",
                        "message": "Forward mode is currently implemented for Sprite-backed runtimes only",
                        "failing_step": "runtime_provider_dispatch",
                        "command": [],
                        "exit_code": None,
                        "timed_out": False,
                        "stdout": "",
                        "stderr": f"runtime={runtime_provider.value}",
                        "remediation": [
                            "Use runtime='sprite' for forward mode.",
                            "Use domain_mode='dns' with Cloudflare-managed zones for Railway.",
                        ],
                    },
                )
            public_step = _run_step(
                "sprite_url_public",
                sprite_command("url", "update", "--auth", "public", sprite_name=den_name),
                cwd=PROJECT_DIR,
                timeout_s=30,
            )
            steps.append(public_step)
            if not public_step["ok"]:
                return _result(
                    "operate_den",
                    False,
                    steps=steps,
                    error=_build_error(
                        public_step,
                        f"Action {action} failed for {den_name}",
                        [
                            "Use command, stdout, and stderr in this payload to debug.",
                            "Fix auth/state issues, then retry the same action.",
                        ],
                    ),
                )
            domain_step = _run_step(
                "sesame_add_url_forward",
                _sesame_url_forward_command(custom_domain, target_url or ""),
                cwd=None,
                timeout_s=60,
            )
        steps.append(domain_step)
        if not domain_step["ok"]:
            return _result(
                "operate_den",
                False,
                steps=steps,
                error=_build_error(
                    domain_step,
                    f"Action {action} failed for {den_name}",
                    [
                        "Use command, stdout, and stderr in this payload to debug.",
                        "Fix auth/state issues, then retry the same action.",
                    ],
                ),
            )
        return _result(
            "operate_den",
            True,
            steps=steps,
            data={"action": action, "den_name": den_name, "custom_domain": custom_domain},
        )

    if not step["ok"]:
        return _result(
            "operate_den",
            False,
            steps=steps,
            error=_build_error(
                step,
                f"Action {action} failed for {den_name}",
                [
                    "Use command, stdout, and stderr in this payload to debug.",
                    "Fix auth/state issues, then retry the same action.",
                ],
            ),
        )

    data: dict[str, Any] = {"action": action, "den_name": den_name, "custom_domain": custom_domain}
    if action == "status":
        if runtime_provider is RuntimeProvider.sprite:
            data["url"] = parse_sprite_url(step["stdout"])
        else:
            data["runtime"] = runtime_provider.value
            try:
                payload = json.loads(step["stdout"])
            except json.JSONDecodeError:
                payload = None
            data["linked_project"] = extract_railway_linked_project_name(payload)
            services = parse_railway_service_statuses(payload)
            data["services"] = [
                {
                    "name": entry.name,
                    "service_id": entry.service_id,
                    "instance_id": entry.instance_id,
                    "latest_deployment_id": entry.latest_deployment_id,
                    "latest_deployment_status": entry.latest_deployment_status,
                    "deployment_stopped": entry.deployment_stopped,
                }
                for entry in services
            ]
            if service is not None:
                matched = next((entry for entry in services if entry.name == service), None)
                if matched is None:
                    return _result(
                        "operate_den",
                        False,
                        steps=steps,
                        error={
                            "kind": "invalid_input",
                            "message": f"Railway service not found: {service}",
                            "failing_step": step["step"],
                            "command": step["command"],
                            "exit_code": step["exit_code"],
                            "timed_out": step["timed_out"],
                            "stdout": step["stdout"],
                            "stderr": step["stderr"] or "Requested service is not present in linked project status.",
                            "remediation": [
                                "Call operate_den(action='status', runtime='railway') without service to inspect available services.",
                                "Retry with a service name from the returned services list.",
                            ],
                        },
                    )
                data["service"] = {
                    "name": matched.name,
                    "service_id": matched.service_id,
                    "instance_id": matched.instance_id,
                    "latest_deployment_id": matched.latest_deployment_id,
                    "latest_deployment_status": matched.latest_deployment_status,
                    "deployment_stopped": matched.deployment_stopped,
                }
            data["status"] = payload if payload is not None else step["stdout"]
    return _result("operate_den", True, steps=steps, data=data)


@mcp.tool
def diagnose_den(include_docker_build: bool = False) -> dict[str, Any]:
    """Diagnostics workflow: strict typing, property tests, and den smoke tests in one call."""
    steps: list[StepResult] = []

    plan: list[tuple[str, list[str], int]] = [
        ("mypy", ["uv", "run", "mypy", "src"], 120),
        ("property_tests", ["uv", "run", "pytest", "tests/python"], 180),
        ("den_smoke", ["bash", "tests/test-den.sh", "--no-build"], 240),
    ]
    if include_docker_build:
        plan.append(("den_full", ["bash", "tests/test-den.sh"], 900))

    for step_name, command, timeout_s in plan:
        step = _run_step(step_name, command, cwd=PROJECT_DIR, timeout_s=timeout_s)
        steps.append(step)
        if not step["ok"]:
            return _result(
                "diagnose_den",
                False,
                steps=steps,
                error=_build_error(
                    step,
                    f"Diagnostics failed at {step_name}",
                    [
                        "Inspect stderr/stdout in this payload for the exact failing assertion/command.",
                        "Fix the root issue and rerun diagnose_den.",
                        "Use include_docker_build=true only after smoke checks pass.",
                    ],
                ),
            )

    return _result(
        "diagnose_den",
        True,
        steps=steps,
        data={"include_docker_build": include_docker_build},
        next_steps=[
            "If provisioning changed, run provision_den to validate runtime workflows.",
        ],
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
