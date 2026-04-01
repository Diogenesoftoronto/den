from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Literal, TypedDict

from fastmcp import FastMCP

from den_cli.core import discover_porkbun_domains_from_sesame_config, normalize_den_name, parse_sprite_url, resolve_sesame_command, split_custom_domain, sprite_command

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
    step = _run_step("sesame_domain_list", _sesame_command() + ["domain", "list", "--all", "--json"], cwd=None, timeout_s=30)
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


def _sesame_url_forward_command(custom_domain: str, target_url: str) -> list[str]:
    zone, subdomain = split_custom_domain(custom_domain, owned_domains=_sesame_owned_domains())
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
    return command


@mcp.tool
def provision_den(
    name: str,
    backend: Literal["nix", "guix"] = "nix",
    tailscale_authkey: str | None = None,
    custom_domain: str | None = None,
) -> dict[str, Any]:
    """Provision workflow: prerequisites + spawn + optional domain in one call."""
    del tailscale_authkey
    steps: list[StepResult] = []
    den_name = normalize_den_name(name)

    for cmd in ("sprite",):
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

    try:
        sesame_cmd = _sesame_command()
    except FileNotFoundError:
        sesame_cmd = []
    if custom_domain and not sesame_cmd:
        return _result(
            "provision_den",
            False,
            steps=steps,
            error={
                "kind": "missing_dependency",
                "message": "sesame is required when custom_domain is provided",
                "failing_step": "preflight",
                "command": ["sesame", "--help"],
                "exit_code": None,
                "timed_out": False,
                "stdout": "",
                "stderr": "sesame is not on PATH and no local build was found",
                "remediation": [
                    "Build or install sesame.",
                    "Or omit custom_domain and configure the domain later.",
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

        sesame_step = _run_step(
            "sesame_add_url_forward",
            _sesame_url_forward_command(custom_domain, target_url),
            cwd=None,
            timeout_s=60,
        )
        steps.append(sesame_step)
        if not sesame_step["ok"]:
            return _result(
                "provision_den",
                False,
                steps=steps,
                error=_build_error(
                    sesame_step,
                    "Provision succeeded but adding the Porkbun URL forward failed.",
                    [
                        "Verify sesame credentials and owned domain resolution.",
                        "Retry operate_den(action='domain', ...).",
                    ],
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
    confirm_destroy: bool = False,
    log_timeout_s: int = 20,
) -> dict[str, Any]:
    """Operations workflow: Sprite lifecycle actions plus sesame-backed domains."""
    del log_timeout_s
    steps: list[StepResult] = []

    if action == "list":
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
        return _result("operate_den", True, steps=steps, data={"dens": dens, "count": len(dens)})

    if action in {"redeploy", "logs"}:
        return _result(
            "operate_den",
            False,
            steps=steps,
            error={
                "kind": "unsupported_action",
                "message": f"Sprite backend does not implement action={action}",
                "failing_step": "provider_capability_check",
                "command": [],
                "exit_code": None,
                "timed_out": False,
                "stdout": "",
                "stderr": f"{action} is not exposed by the current Sprite CLI integration",
                "remediation": [
                    "Use Sprite checkpoints or recreate the sprite.",
                    "Connect to the sprite for in-environment inspection.",
                ],
            },
        )

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
        step = _run_step("sprite_destroy", sprite_command("destroy", "-force", sprite_name=den_name), cwd=PROJECT_DIR, timeout_s=60)
        steps.append(step)
    elif action == "status":
        step = _run_step("sprite_status", sprite_command("url", sprite_name=den_name), cwd=PROJECT_DIR, timeout_s=30)
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

        sesame_step = _run_step(
            "sesame_add_url_forward",
            _sesame_url_forward_command(custom_domain, target_url),
            cwd=None,
            timeout_s=60,
        )
        steps.append(sesame_step)
        if not sesame_step["ok"]:
            return _result(
                "operate_den",
                False,
                steps=steps,
                error=_build_error(
                    sesame_step,
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
        data["url"] = parse_sprite_url(step["stdout"])
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
