from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from den_cli import mcp_server


def _fake_run_step(
    step: str,
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout_s: int = 120,
    input_text: str | None = None,
) -> mcp_server.StepResult:
    """Simulate a successful step."""
    return {
        "step": step,
        "command": command,
        "cwd": str(cwd or Path.home()),
        "ok": True,
        "exit_code": 0,
        "timed_out": False,
        "duration_ms": 10,
        "stdout": "",
        "stderr": "",
    }


def _fake_run_step_fail(
    step: str,
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout_s: int = 120,
    input_text: str | None = None,
) -> mcp_server.StepResult:
    """Simulate a failed step."""
    return {
        "step": step,
        "command": command,
        "cwd": str(cwd or Path.home()),
        "ok": False,
        "exit_code": 1,
        "timed_out": False,
        "duration_ms": 10,
        "stdout": "",
        "stderr": "simulated failure",
    }


def test_operate_den_list_success(monkeypatch: object) -> None:
    def fake_run_step(
        step: str,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> mcp_server.StepResult:
        return {
            "step": step,
            "command": command,
            "cwd": str(cwd or Path.home()),
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 10,
            "stdout": "den-alpha\nden-beta\nother-thing\n",
            "stderr": "",
        }

    with patch.object(mcp_server, "_run_step", fake_run_step):
        result = mcp_server.operate_den(action="list")

    assert result["ok"] is True
    assert result["data"]["dens"] == ["den-alpha", "den-beta"]
    assert result["data"]["count"] == 2


def test_operate_den_list_failure(monkeypatch: object) -> None:
    with patch.object(mcp_server, "_run_step", _fake_run_step_fail):
        result = mcp_server.operate_den(action="list")

    assert result["ok"] is False
    assert result["error"] is not None
    assert result["error"]["kind"] == "command_failure"


def test_operate_den_list_railway_success() -> None:
    def fake_list_step() -> mcp_server.StepResult:
        payload = [
            {"id": "p1", "name": "den-alpha", "workspace": {"name": "Main"}},
            {"id": "p2", "name": "other-project", "workspace": {"name": "Main"}},
        ]
        return {
            "step": "railway_list_projects",
            "command": ["railway", "list", "--json"],
            "cwd": str(Path.home()),
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 10,
            "stdout": json.dumps(payload),
            "stderr": "",
        }

    with patch.object(mcp_server, "_railway_list_step", fake_list_step):
        result = mcp_server.operate_den(action="list", runtime="railway")

    assert result["ok"] is True
    assert result["data"]["runtime"] == "railway"
    assert result["data"]["dens"] == ["den-alpha"]
    assert result["data"]["count"] == 1


def test_operate_den_destroy_requires_confirmation() -> None:
    result = mcp_server.operate_den(action="destroy", name="myproject", confirm_destroy=False)

    assert result["ok"] is False
    assert result["error"] is not None
    assert result["error"]["kind"] == "safety_check"


def test_operate_den_destroy_with_confirmation() -> None:
    with patch.object(mcp_server, "_run_step", _fake_run_step):
        result = mcp_server.operate_den(action="destroy", name="myproject", confirm_destroy=True)

    assert result["ok"] is True
    assert result["data"]["action"] == "destroy"
    assert result["data"]["den_name"] == "den-myproject"


def test_operate_den_destroy_railway_with_confirmation() -> None:
    def fake_status_step() -> mcp_server.StepResult:
        return {
            "step": "railway_status",
            "command": ["railway", "status", "--json"],
            "cwd": str(Path.home()),
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 10,
            "stdout": json.dumps({"project": {"name": "den-myproject"}}),
            "stderr": "",
        }

    def fake_run_step(
        step: str,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> mcp_server.StepResult:
        del cwd, timeout_s, input_text
        return {
            "step": step,
            "command": command,
            "cwd": str(Path.home()),
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 10,
            "stdout": "{}",
            "stderr": "",
        }

    with (
        patch.object(mcp_server, "_railway_status_step", fake_status_step),
        patch.object(mcp_server, "_run_step", fake_run_step),
    ):
        result = mcp_server.operate_den(action="destroy", name="myproject", confirm_destroy=True, runtime="railway")

    assert result["ok"] is True
    assert result["data"]["action"] == "destroy"
    assert result["steps"][-1]["command"] == mcp_server.railway_delete_command("den-myproject")


def test_operate_den_destroy_railway_rejects_mismatched_linked_project() -> None:
    def fake_status_step() -> mcp_server.StepResult:
        return {
            "step": "railway_status",
            "command": ["railway", "status", "--json"],
            "cwd": str(Path.home()),
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 10,
            "stdout": json.dumps({"project": {"name": "den-other"}}),
            "stderr": "",
        }

    with patch.object(mcp_server, "_railway_status_step", fake_status_step):
        result = mcp_server.operate_den(action="destroy", name="myproject", confirm_destroy=True, runtime="railway")

    assert result["ok"] is False
    assert result["error"] is not None
    assert result["error"]["kind"] == "safety_check"


def test_operate_den_requires_name_for_destroy() -> None:
    result = mcp_server.operate_den(action="destroy")

    assert result["ok"] is False
    assert result["error"] is not None
    assert result["error"]["kind"] == "invalid_input"


def test_operate_den_requires_name_for_status() -> None:
    result = mcp_server.operate_den(action="status")

    assert result["ok"] is False
    assert result["error"]["kind"] == "invalid_input"


def test_operate_den_status_success() -> None:
    def fake_run_step(
        step: str,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> mcp_server.StepResult:
        return {
            "step": step,
            "command": command,
            "cwd": str(cwd or Path.home()),
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 10,
            "stdout": "URL: https://den-myproject.sprites.app\nAuth: public\n",
            "stderr": "",
        }

    with patch.object(mcp_server, "_run_step", fake_run_step):
        result = mcp_server.operate_den(action="status", name="myproject")

    assert result["ok"] is True
    assert result["data"]["url"] == "https://den-myproject.sprites.app"


def test_operate_den_status_railway_success() -> None:
    def fake_run_step(
        step: str,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> mcp_server.StepResult:
        return {
            "step": step,
            "command": command,
            "cwd": str(cwd or Path.home()),
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 10,
            "stdout": json.dumps(
                {
                    "project": {"name": "den-myproject"},
                    "environments": {
                        "edges": [
                            {
                                "node": {
                                    "serviceInstances": {
                                        "edges": [
                                            {
                                                "node": {
                                                    "id": "inst-1",
                                                    "serviceId": "svc-1",
                                                    "serviceName": "dio-web",
                                                    "latestDeployment": {
                                                        "id": "dep-1",
                                                        "status": "SUCCESS",
                                                        "deploymentStopped": False,
                                                    },
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        ]
                    },
                }
            ),
            "stderr": "",
        }

    with patch.object(mcp_server, "_run_step", fake_run_step):
        result = mcp_server.operate_den(action="status", name="myproject", runtime="railway")

    assert result["ok"] is True
    assert result["data"]["runtime"] == "railway"
    assert result["data"]["linked_project"] == "den-myproject"
    assert result["data"]["services"] == [
        {
            "name": "dio-web",
            "service_id": "svc-1",
            "instance_id": "inst-1",
            "latest_deployment_id": "dep-1",
            "latest_deployment_status": "SUCCESS",
            "deployment_stopped": False,
        }
    ]


def test_operate_den_status_railway_service_success() -> None:
    def fake_run_step(
        step: str,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> mcp_server.StepResult:
        return {
            "step": step,
            "command": command,
            "cwd": str(cwd or Path.home()),
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 10,
            "stdout": json.dumps(
                {
                    "project": {"name": "den-myproject"},
                    "environments": {
                        "edges": [
                            {
                                "node": {
                                    "serviceInstances": {
                                        "edges": [
                                            {
                                                "node": {
                                                    "id": "inst-1",
                                                    "serviceId": "svc-1",
                                                    "serviceName": "dio-web",
                                                    "latestDeployment": {
                                                        "id": "dep-1",
                                                        "status": "SUCCESS",
                                                        "deploymentStopped": False,
                                                    },
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        ]
                    },
                }
            ),
            "stderr": "",
        }

    with patch.object(mcp_server, "_run_step", fake_run_step):
        result = mcp_server.operate_den(action="status", name="myproject", runtime="railway", service="dio-web")

    assert result["ok"] is True
    assert result["data"]["service"] == {
        "name": "dio-web",
        "service_id": "svc-1",
        "instance_id": "inst-1",
        "latest_deployment_id": "dep-1",
        "latest_deployment_status": "SUCCESS",
        "deployment_stopped": False,
    }


def test_operate_den_status_railway_service_rejects_unknown_service() -> None:
    def fake_run_step(
        step: str,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> mcp_server.StepResult:
        return {
            "step": step,
            "command": command,
            "cwd": str(cwd or Path.home()),
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 10,
            "stdout": json.dumps({"project": {"name": "den-myproject"}, "environments": {"edges": []}}),
            "stderr": "",
        }

    with patch.object(mcp_server, "_run_step", fake_run_step):
        result = mcp_server.operate_den(action="status", name="myproject", runtime="railway", service="missing")

    assert result["ok"] is False
    assert result["error"]["kind"] == "invalid_input"
    assert "Railway service not found" in result["error"]["message"]


def test_operate_den_domain_requires_custom_domain() -> None:
    result = mcp_server.operate_den(action="domain", name="myproject")

    assert result["ok"] is False
    assert result["error"]["kind"] == "invalid_input"
    assert "custom_domain" in result["error"]["message"]


def test_operate_den_redeploy_unsupported() -> None:
    result = mcp_server.operate_den(action="redeploy", name="myproject")

    assert result["ok"] is False
    assert result["error"]["kind"] == "unsupported_action"


def test_sesame_url_forward_command_rejects_cloudflare_owned_zone(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "discover_cloudflare_domains", lambda: ["example.com"])
    monkeypatch.setattr(mcp_server, "_sesame_owned_domains", lambda: [])

    try:
        mcp_server._sesame_url_forward_command("app.example.com", "https://den-myproject.sprites.app")
    except ValueError as exc:
        assert "Cloudflare" in str(exc)
    else:
        raise AssertionError("expected Cloudflare-owned zone to be rejected explicitly")


def test_operate_den_domain_railway_dns_uses_cloudflare_attach(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_configured_domain_zones", lambda: {mcp_server.DomainProvider.cloudflare: ["example.com"], mcp_server.DomainProvider.sesame: []})

    def fake_run_step(
        step: str,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> mcp_server.StepResult:
        return {
            "step": step,
            "command": command,
            "cwd": str(cwd or Path.home()),
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 10,
            "stdout": '{"project":"demo"}',
            "stderr": "",
        }

    attached: list[tuple[str, str, str, bool, int | None]] = []

    def fake_attach(service: str, custom_domain: str, zone: str, *, proxied: bool, port: int | None) -> mcp_server.StepResult:
        attached.append((service, custom_domain, zone, proxied, port))
        return {
            "step": "cloudflare_dns_upsert",
            "command": ["cloudflare-api"],
            "cwd": str(Path.home()),
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 10,
            "stdout": "[]",
            "stderr": "",
        }

    with (
        patch.object(mcp_server, "_run_step", fake_run_step),
        patch.object(mcp_server, "_cloudflare_dns_attach_step_for_railway", fake_attach),
    ):
        result = mcp_server.operate_den(
            action="domain",
            name="myproject",
            custom_domain="app.example.com",
            runtime="railway",
            domain_mode="dns",
            port=8080,
        )

    assert result["ok"] is True
    assert attached == [("den-myproject", "app.example.com", "example.com", False, 8080)]


def test_operate_den_domain_railway_dns_uses_sesame_attach(monkeypatch) -> None:
    monkeypatch.setattr(
        mcp_server,
        "_configured_domain_zones",
        lambda: {mcp_server.DomainProvider.cloudflare: [], mcp_server.DomainProvider.sesame: ["dev.example.com"]},
    )

    attached: list[tuple[str, str, str, int | None]] = []

    def fake_attach(service: str, custom_domain: str, zone: str, *, port: int | None) -> mcp_server.StepResult:
        attached.append((service, custom_domain, zone, port))
        return {
            "step": "sesame_dns_upsert",
            "command": ["sesame", "dns"],
            "cwd": str(Path.home()),
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 10,
            "stdout": "[]",
            "stderr": "",
        }

    with patch.object(mcp_server, "_sesame_dns_attach_step_for_railway", fake_attach):
        result = mcp_server.operate_den(
            action="domain",
            name="myproject",
            custom_domain="app.dev.example.com",
            runtime="railway",
            domain_mode="dns",
            port=8080,
        )

    assert result["ok"] is True
    assert attached == [("den-myproject", "app.dev.example.com", "dev.example.com", 8080)]


def test_provision_den_railway_dns_uses_sesame_attach(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_command_exists", lambda cmd: True)
    monkeypatch.setattr(mcp_server, "_configured_domain_zones", lambda: {mcp_server.DomainProvider.cloudflare: [], mcp_server.DomainProvider.sesame: ["dev.example.com"]})
    monkeypatch.setattr(mcp_server, "PROJECT_DIR", Path.home())

    def fake_run_step(
        step: str,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> mcp_server.StepResult:
        return {
            "step": step,
            "command": command,
            "cwd": str(cwd or Path.home()),
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 10,
            "stdout": '{"project":{"name":"den-myproject"}}',
            "stderr": "",
        }

    attached: list[tuple[str, str, str, int | None]] = []

    def fake_attach(service: str, custom_domain: str, zone: str, *, port: int | None) -> mcp_server.StepResult:
        attached.append((service, custom_domain, zone, port))
        return {
            "step": "sesame_dns_upsert",
            "command": ["sesame", "dns"],
            "cwd": str(Path.home()),
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 10,
            "stdout": "[]",
            "stderr": "",
        }

    with (
        patch.object(mcp_server, "_run_step", fake_run_step),
        patch.object(mcp_server, "_sesame_dns_attach_step_for_railway", fake_attach),
    ):
        result = mcp_server.provision_den(
            name="myproject",
            runtime="railway",
            custom_domain="app.dev.example.com",
            domain_mode="dns",
            port=8080,
        )

    assert result["ok"] is True
    assert attached == [("den-myproject", "app.dev.example.com", "dev.example.com", 8080)]


def test_operate_den_logs_unsupported() -> None:
    result = mcp_server.operate_den(action="logs", name="myproject")

    assert result["ok"] is False
    assert result["error"]["kind"] == "unsupported_action"


def test_diagnose_den_stops_on_first_failure() -> None:
    call_count = 0

    def counting_fail(
        step: str,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> mcp_server.StepResult:
        nonlocal call_count
        call_count += 1
        return _fake_run_step_fail(step, command, cwd=cwd, timeout_s=timeout_s, input_text=input_text)

    with patch.object(mcp_server, "_run_step", counting_fail):
        result = mcp_server.diagnose_den()

    assert result["ok"] is False
    assert call_count == 1
    assert result["error"]["failing_step"] == "mypy"


def test_diagnose_den_runs_all_steps_on_success() -> None:
    steps_seen: list[str] = []

    def tracking_success(
        step: str,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> mcp_server.StepResult:
        steps_seen.append(step)
        return _fake_run_step(step, command, cwd=cwd, timeout_s=timeout_s, input_text=input_text)

    with patch.object(mcp_server, "_run_step", tracking_success):
        result = mcp_server.diagnose_den()

    assert result["ok"] is True
    assert steps_seen == ["mypy", "property_tests", "den_smoke"]


def test_diagnose_den_includes_docker_build_when_requested() -> None:
    steps_seen: list[str] = []

    def tracking_success(
        step: str,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> mcp_server.StepResult:
        steps_seen.append(step)
        return _fake_run_step(step, command, cwd=cwd, timeout_s=timeout_s, input_text=input_text)

    with patch.object(mcp_server, "_run_step", tracking_success):
        result = mcp_server.diagnose_den(include_docker_build=True)

    assert result["ok"] is True
    assert steps_seen == ["mypy", "property_tests", "den_smoke", "den_full"]


def test_provision_den_fails_without_sprite() -> None:
    with patch.object(mcp_server, "_command_exists", return_value=False):
        result = mcp_server.provision_den(name="myproject")

    assert result["ok"] is False
    assert result["error"]["kind"] == "missing_dependency"


def test_provision_den_fails_without_project_dir() -> None:
    with (
        patch.object(mcp_server, "_command_exists", return_value=True),
        patch.object(mcp_server, "PROJECT_DIR", Path("/nonexistent/path")),
    ):
        result = mcp_server.provision_den(name="myproject")

    assert result["ok"] is False
    assert result["error"]["kind"] == "missing_project"


def test_build_error_structure() -> None:
    step: mcp_server.StepResult = {
        "step": "test_step",
        "command": ["echo", "hello"],
        "cwd": "/tmp",
        "ok": False,
        "exit_code": 1,
        "timed_out": False,
        "duration_ms": 42,
        "stdout": "some output",
        "stderr": "some error",
    }
    error = mcp_server._build_error(step, "Test failed", ["Fix it"])

    assert error["kind"] == "command_failure"
    assert error["message"] == "Test failed"
    assert error["failing_step"] == "test_step"
    assert error["command"] == ["echo", "hello"]
    assert error["exit_code"] == 1
    assert error["timed_out"] is False
    assert error["remediation"] == ["Fix it"]


def test_result_structure() -> None:
    result = mcp_server._result(
        "test_workflow",
        True,
        steps=[],
        data={"key": "value"},
        next_steps=["do something"],
    )

    assert result["workflow"] == "test_workflow"
    assert result["ok"] is True
    assert result["data"] == {"key": "value"}
    assert result["error"] is None
    assert result["next_steps"] == ["do something"]
    assert result["steps"] == []
