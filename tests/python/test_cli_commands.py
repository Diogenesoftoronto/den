from __future__ import annotations

import json
import subprocess

from typer.testing import CliRunner

from den_cli import cli

runner = CliRunner()


def test_exec_runs_sprite_exec_with_normalized_name(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del cwd, capture_output, error_hint, input_text
        calls.append(cmd)
        return object()

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)

    result = runner.invoke(cli.app, ["exec", "myproject", "echo", "hello"])

    assert result.exit_code == 0
    assert calls == [["sprite", "-s", "den-myproject", "exec", "--", "echo", "hello"]]


def test_exec_requires_command(monkeypatch) -> None:
    result = runner.invoke(cli.app, ["exec"])

    assert result.exit_code == 2
    assert isinstance(result.exception, SystemExit)


def test_exec_requires_command_payload(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_run_checked", lambda *args, **kwargs: object())

    result = runner.invoke(cli.app, ["exec", "myproject"])

    assert result.exit_code == 1
    assert isinstance(result.exception, cli.CommandError)
    assert str(result.exception) == "Provide a command to run inside the den."


def test_sprite_use_runs_sprite_use_with_normalized_name(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del cwd, capture_output, error_hint, input_text
        calls.append(cmd)
        return object()

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)

    result = runner.invoke(cli.app, ["sprite-use", "myproject"])

    assert result.exit_code == 0
    assert calls == [["sprite", "use", "den-myproject"]]


def test_sprite_use_prompts_for_den_name_when_missing(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_choose_den_name(prompt: str) -> str:
        assert prompt == "Bind current directory to"
        return "den-picked"

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del cwd, capture_output, error_hint, input_text
        calls.append(cmd)
        return object()

    monkeypatch.setattr(cli, "_choose_den_name", fake_choose_den_name)
    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)

    result = runner.invoke(cli.app, ["sprite-use"])

    assert result.exit_code == 0
    assert calls == [["sprite", "use", "den-picked"]]


def test_logs_lists_sessions(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del cwd, capture_output, error_hint, input_text
        calls.append(cmd)
        return object()

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)

    result = runner.invoke(cli.app, ["logs", "myproject", "--list"])

    assert result.exit_code == 0
    assert calls == [["sprite", "-s", "den-myproject", "sessions", "list"]]


def test_logs_attaches_to_selected_session(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del cwd, capture_output, error_hint, input_text
        calls.append(cmd)
        return object()

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)

    result = runner.invoke(cli.app, ["logs", "myproject", "12345"])

    assert result.exit_code == 0
    assert calls == [["sprite", "-s", "den-myproject", "attach", "12345"]]


def test_redeploy_creates_and_restores_checkpoint(monkeypatch) -> None:
    checked_calls: list[list[str]] = []
    run_calls: list[list[str]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del cwd, capture_output, error_hint, input_text
        checked_calls.append(cmd)
        return object()

    def fake_run(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, capture_output, input_text
        run_calls.append(cmd)
        payload = [{"id": "v42", "comment": "den-redeploy:den-myproject:123"}]
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)
    monkeypatch.setattr(cli, "_run", fake_run)
    monkeypatch.setattr(cli.time, "time_ns", lambda: 123)

    result = runner.invoke(cli.app, ["redeploy", "myproject"])

    assert result.exit_code == 0
    assert checked_calls == [
        ["sprite", "-s", "den-myproject", "checkpoint", "create", "--comment", "den-redeploy:den-myproject:123"],
        ["sprite", "-s", "den-myproject", "restore", "v42"],
    ]
    assert run_calls == [["sprite", "-s", "den-myproject", "api", "/checkpoints"]]


def test_redeploy_falls_back_to_checkpoint_list(monkeypatch) -> None:
    checked_calls: list[list[str]] = []
    run_calls: list[list[str]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del cwd, capture_output, error_hint, input_text
        checked_calls.append(cmd)
        return object()

    def fake_run(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, capture_output, input_text
        run_calls.append(cmd)
        if cmd[-1] == "/checkpoints":
            return subprocess.CompletedProcess(cmd, 0, stdout="not-json", stderr="")
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="v7  den-redeploy:den-myproject:123  just-now\n",
            stderr="",
        )

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)
    monkeypatch.setattr(cli, "_run", fake_run)
    monkeypatch.setattr(cli.time, "time_ns", lambda: 123)

    result = runner.invoke(cli.app, ["redeploy", "myproject"])

    assert result.exit_code == 0
    assert checked_calls[-1] == ["sprite", "-s", "den-myproject", "restore", "v7"]
    assert run_calls == [
        ["sprite", "-s", "den-myproject", "api", "/checkpoints"],
        ["sprite", "-s", "den-myproject", "checkpoint", "list"],
    ]


def test_attach_custom_domain_uses_sesame_when_porkbun_holds_zone(monkeypatch) -> None:
    checked_calls: list[list[str]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del cwd, capture_output, error_hint, input_text
        checked_calls.append(cmd)
        return object()

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)
    monkeypatch.setattr(cli, "_sprite_url", lambda den_name: "https://den-myproject.sprites.app")
    monkeypatch.setattr(cli, "_sesame_command", lambda: ["sesame"])
    monkeypatch.setattr(cli, "_owned_porkbun_domains", lambda: ["dev.example.com"])
    monkeypatch.setattr(cli, "discover_cloudflare_domains", lambda: [])

    target_url = cli._attach_custom_domain(
        "den-myproject",
        "app.dev.example.com",
        runtime=cli.RuntimeProvider.sprite,
        mode=cli.DomainMode.forward,
        proxied=False,
        port=None,
    )

    assert target_url == "https://den-myproject.sprites.app"
    assert checked_calls == [
        ["sprite", "-s", "den-myproject", "url", "update", "--auth", "public"],
        [
            "sesame",
            "domain",
            "add-url-forward",
            "dev.example.com",
            "--location",
            "https://den-myproject.sprites.app",
            "--type",
            "permanent",
            "--include-path",
            "yes",
            "--subdomain",
            "app",
        ],
    ]


def test_attach_custom_domain_rejects_cloudflare_owned_zone(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_run_checked", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "_sprite_url", lambda den_name: "https://den-myproject.sprites.app")
    monkeypatch.setattr(cli, "_owned_porkbun_domains", lambda: [])
    monkeypatch.setattr(cli, "discover_cloudflare_domains", lambda: ["example.com"])

    try:
        cli._attach_custom_domain(
            "den-myproject",
            "app.example.com",
            runtime=cli.RuntimeProvider.sprite,
            mode=cli.DomainMode.forward,
            proxied=False,
            port=None,
        )
    except cli.CommandError as exc:
        assert "cloudflare" in str(exc).lower()
    else:
        raise AssertionError("expected Cloudflare-owned zone to be rejected explicitly")


def test_attach_custom_domain_uses_cloudflare_dns_when_requested(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_sprite_url", lambda den_name: "https://den-myproject.sprites.app")
    monkeypatch.setattr(cli, "_owned_porkbun_domains", lambda: [])
    monkeypatch.setattr(cli, "discover_cloudflare_domains", lambda: ["example.com"])

    captured: list[tuple[str, str, str, bool]] = []

    def fake_attach(den_name: str, host: str, zone: str, *, proxied: bool) -> None:
        captured.append((den_name, host, zone, proxied))

    monkeypatch.setattr(cli, "_attach_cloudflare_dns_to_sprite", fake_attach)

    target_url = cli._attach_custom_domain(
        "den-myproject",
        "app.example.com",
        runtime=cli.RuntimeProvider.sprite,
        mode=cli.DomainMode.dns,
        proxied=True,
        port=None,
    )

    assert target_url == "https://den-myproject.sprites.app"
    assert captured == [("den-myproject", "app.example.com", "example.com", True)]


def test_attach_custom_domain_uses_cloudflare_dns_for_railway(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_owned_porkbun_domains", lambda: [])
    monkeypatch.setattr(cli, "discover_cloudflare_domains", lambda: ["example.com"])

    captured: list[tuple[str, str, str, bool, int | None]] = []

    def fake_attach(service: str, host: str, zone: str, *, proxied: bool, port: int | None) -> None:
        captured.append((service, host, zone, proxied, port))

    monkeypatch.setattr(cli, "_attach_cloudflare_dns_to_railway", fake_attach)

    target_url = cli._attach_custom_domain(
        "den-myproject",
        "app.example.com",
        runtime=cli.RuntimeProvider.railway,
        mode=cli.DomainMode.dns,
        proxied=False,
        port=8080,
    )

    assert target_url == "railway://den-myproject"
    assert captured == [("den-myproject", "app.example.com", "example.com", False, 8080)]


def test_attach_custom_domain_uses_sesame_dns_for_railway(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_owned_porkbun_domains", lambda: ["dev.example.com"])
    monkeypatch.setattr(cli, "discover_cloudflare_domains", lambda: [])

    captured: list[tuple[str, str, str, int | None]] = []

    def fake_attach(service: str, host: str, zone: str, *, port: int | None) -> None:
        captured.append((service, host, zone, port))

    monkeypatch.setattr(cli, "_attach_sesame_dns_to_railway", fake_attach)

    target_url = cli._attach_custom_domain(
        "den-myproject",
        "app.dev.example.com",
        runtime=cli.RuntimeProvider.railway,
        mode=cli.DomainMode.dns,
        proxied=False,
        port=8080,
    )

    assert target_url == "railway://den-myproject"
    assert captured == [("den-myproject", "app.dev.example.com", "dev.example.com", 8080)]


def test_setup_writes_den_dhall_and_runs_generator(monkeypatch, tmp_path) -> None:
    checked_calls: list[list[str]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del cwd, capture_output, error_hint, input_text
        checked_calls.append(cmd)
        return object()

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)
    monkeypatch.setattr(cli, "_command_exists", lambda name: False)
    monkeypatch.setattr(cli, "_sesame_command", lambda: (_ for _ in ()).throw(cli.CommandError("sesame executable not found")))
    monkeypatch.setattr(cli, "DHALL_DIR", tmp_path / "dhall")
    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path / "den-project")

    (tmp_path / "dhall").mkdir()
    (tmp_path / "den-project" / "scripts").mkdir(parents=True)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "package.json").write_text("{}")

    result = runner.invoke(cli.app, ["setup", str(repo_dir)])

    assert result.exit_code == 0
    assert (repo_dir / "den.dhall").exists()
    assert checked_calls == [
        ["bash", str(tmp_path / "den-project" / "scripts" / "generate-from-dhall.sh"), str(repo_dir / "den.dhall"), str(repo_dir)]
    ]


def test_setup_print_only_does_not_write_files_or_run_generator(monkeypatch, tmp_path) -> None:
    checked_calls: list[list[str]] = []

    monkeypatch.setattr(cli, "_run_checked", lambda cmd, **kwargs: checked_calls.append(cmd) or object())
    monkeypatch.setattr(cli, "_command_exists", lambda name: False)
    monkeypatch.setattr(cli, "DHALL_DIR", tmp_path / "dhall")
    (tmp_path / "dhall").mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "pyproject.toml").write_text("[project]\nname='x'\n")

    result = runner.invoke(cli.app, ["setup", str(repo_dir), "--print"])

    assert result.exit_code == 0
    assert not (repo_dir / "den.dhall").exists()
    assert checked_calls == []


def test_setup_refuses_to_overwrite_without_force(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli, "_command_exists", lambda name: False)
    monkeypatch.setattr(cli, "_sesame_command", lambda: (_ for _ in ()).throw(cli.CommandError("sesame executable not found")))
    monkeypatch.setattr(cli, "DHALL_DIR", tmp_path / "dhall")
    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path / "den-project")
    (tmp_path / "dhall").mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "package.json").write_text("{}")
    (repo_dir / "den.dhall").write_text("existing")

    result = runner.invoke(cli.app, ["setup", str(repo_dir)])

    assert result.exit_code == 1
    assert isinstance(result.exception, cli.CommandError)
    assert "already exists" in str(result.exception)


def test_setup_force_overwrites_existing_den_dhall(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli, "_run_checked", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "_command_exists", lambda name: False)
    monkeypatch.setattr(cli, "_sesame_command", lambda: (_ for _ in ()).throw(cli.CommandError("sesame executable not found")))
    monkeypatch.setattr(cli, "DHALL_DIR", tmp_path / "dhall")
    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path / "den-project")

    (tmp_path / "dhall").mkdir()
    (tmp_path / "den-project" / "scripts").mkdir(parents=True)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "package.json").write_text("{}")
    den_file = repo_dir / "den.dhall"
    den_file.write_text("existing")

    result = runner.invoke(cli.app, ["setup", str(repo_dir), "--force"])

    assert result.exit_code == 0
    assert den_file.read_text() != "existing"


def test_spawn_railway_checks_runtime_readiness(monkeypatch) -> None:
    checked_calls: list[tuple[list[str], object | None]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del capture_output, error_hint, input_text
        checked_calls.append((cmd, cwd))
        return object()

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)

    result = runner.invoke(cli.app, ["spawn", "myproject", "--runtime", "railway"])

    assert result.exit_code == 0
    assert checked_calls == [([*cli.resolve_railway_command(), "status", "--json"], cli.PROJECT_DIR)]


def test_deploy_creates_sprite_binds_repo_and_runs_inferred_command(monkeypatch, tmp_path) -> None:
    checked_calls: list[tuple[list[str], object | None, str | None]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del capture_output, error_hint
        checked_calls.append((cmd, cwd, input_text))
        return object()

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)
    monkeypatch.setattr(cli, "_command_exists", lambda name: False)
    monkeypatch.setattr(cli, "_sesame_command", lambda: (_ for _ in ()).throw(cli.CommandError("sesame executable not found")))
    monkeypatch.setattr(cli, "_list_den_names", lambda: [])
    monkeypatch.setattr(cli, "_sync_repo_to_sprite", lambda name, repo_dir: f"/home/sprite/{repo_dir.name}")
    monkeypatch.setattr(cli, "DHALL_DIR", tmp_path / "dhall")
    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path / "den-project")

    (tmp_path / "dhall").mkdir()
    (tmp_path / "den-project" / "scripts").mkdir(parents=True)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}))
    (repo_dir / "bun.lock").write_text("")

    result = runner.invoke(cli.app, ["deploy", str(repo_dir)])

    assert result.exit_code == 0
    assert checked_calls == [
        (
            ["bash", str(tmp_path / "den-project" / "scripts" / "generate-from-dhall.sh"), str(repo_dir / "den.dhall"), str(repo_dir)],
            None,
            None,
        ),
        (["sprite", "create", "den-repo", "--skip-console"], tmp_path / "den-project", None),
        (["sprite", "use", "den-repo"], repo_dir, None),
        (["sprite", "-s", "den-repo", "exec", "--tty", "--dir", "/home/sprite/repo", "--", "bun", "run", "dev"], None, None),
    ]


def test_deploy_reuses_existing_sprite_and_skips_run_when_not_inferred(monkeypatch, tmp_path) -> None:
    checked_calls: list[tuple[list[str], object | None, str | None]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del capture_output, error_hint, input_text
        checked_calls.append((cmd, cwd, None))
        return object()

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)
    monkeypatch.setattr(cli, "_command_exists", lambda name: False)
    monkeypatch.setattr(cli, "_sesame_command", lambda: (_ for _ in ()).throw(cli.CommandError("sesame executable not found")))
    monkeypatch.setattr(cli, "_list_den_names", lambda: ["den-repo"])
    monkeypatch.setattr(cli, "_sync_repo_to_sprite", lambda name, repo_dir: f"/home/sprite/{repo_dir.name}")
    monkeypatch.setattr(cli, "DHALL_DIR", tmp_path / "dhall")
    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path / "den-project")

    (tmp_path / "dhall").mkdir()
    (tmp_path / "den-project" / "scripts").mkdir(parents=True)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "Dockerfile").write_text("FROM scratch\n")

    result = runner.invoke(cli.app, ["deploy", str(repo_dir)])

    assert result.exit_code == 0
    assert checked_calls == [
        (
            ["bash", str(tmp_path / "den-project" / "scripts" / "generate-from-dhall.sh"), str(repo_dir / "den.dhall"), str(repo_dir)],
            None,
            None,
        ),
        (["sprite", "use", "den-repo"], repo_dir, None),
    ]


def test_deploy_no_run_prepares_sprite_without_exec(monkeypatch, tmp_path) -> None:
    checked_calls: list[tuple[list[str], object | None, str | None]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del capture_output, error_hint
        checked_calls.append((cmd, cwd, input_text))
        return object()

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)
    monkeypatch.setattr(cli, "_command_exists", lambda name: False)
    monkeypatch.setattr(cli, "_sesame_command", lambda: (_ for _ in ()).throw(cli.CommandError("sesame executable not found")))
    monkeypatch.setattr(cli, "_list_den_names", lambda: [])
    monkeypatch.setattr(cli, "_sync_repo_to_sprite", lambda name, repo_dir: f"/home/sprite/{repo_dir.name}")
    monkeypatch.setattr(cli, "DHALL_DIR", tmp_path / "dhall")
    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path / "den-project")

    (tmp_path / "dhall").mkdir()
    (tmp_path / "den-project" / "scripts").mkdir(parents=True)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}))

    result = runner.invoke(cli.app, ["deploy", str(repo_dir), "--no-run"])

    assert result.exit_code == 0
    assert checked_calls == [
        (
            ["bash", str(tmp_path / "den-project" / "scripts" / "generate-from-dhall.sh"), str(repo_dir / "den.dhall"), str(repo_dir)],
            None,
            None,
        ),
        (["sprite", "create", "den-repo", "--skip-console"], tmp_path / "den-project", None),
        (["sprite", "use", "den-repo"], repo_dir, None),
    ]


def test_deploy_reuses_existing_den_dhall_without_rerunning_setup(monkeypatch, tmp_path) -> None:
    checked_calls: list[tuple[list[str], object | None, str | None]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del capture_output, error_hint
        checked_calls.append((cmd, cwd, input_text))
        return object()

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)
    monkeypatch.setattr(cli, "_command_exists", lambda name: False)
    monkeypatch.setattr(cli, "_sesame_command", lambda: (_ for _ in ()).throw(cli.CommandError("sesame executable not found")))
    monkeypatch.setattr(cli, "_list_den_names", lambda: ["den-repo"])
    monkeypatch.setattr(cli, "_sync_repo_to_sprite", lambda name, repo_dir: f"/home/sprite/{repo_dir.name}")
    monkeypatch.setattr(cli, "DHALL_DIR", tmp_path / "dhall")
    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path / "den-project")

    (tmp_path / "dhall").mkdir()
    (tmp_path / "den-project" / "scripts").mkdir(parents=True)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "Cargo.toml").write_text("[package]\nname='sample-app'\nversion='0.1.0'\n")
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "main.rs").write_text("fn main() {}\n")
    (repo_dir / "den.dhall").write_text("existing")

    result = runner.invoke(cli.app, ["deploy", str(repo_dir), "--no-run"])

    assert result.exit_code == 0
    assert checked_calls == [
        (["sprite", "use", "den-repo"], repo_dir, None),
    ]


def test_deploy_prefers_mise_start_command_for_orchestrated_repo(monkeypatch, tmp_path) -> None:
    checked_calls: list[tuple[list[str], object | None, str | None]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del capture_output, error_hint
        checked_calls.append((cmd, cwd, input_text))
        return object()

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)
    monkeypatch.setattr(cli, "_command_exists", lambda name: False)
    monkeypatch.setattr(cli, "_sesame_command", lambda: (_ for _ in ()).throw(cli.CommandError("sesame executable not found")))
    monkeypatch.setattr(cli, "_list_den_names", lambda: [])
    monkeypatch.setattr(cli, "_sync_repo_to_sprite", lambda name, repo_dir: f"/home/sprite/{repo_dir.name}")
    monkeypatch.setattr(cli, "DHALL_DIR", tmp_path / "dhall")
    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path / "den-project")

    (tmp_path / "dhall").mkdir()
    (tmp_path / "den-project" / "scripts").mkdir(parents=True)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "mise.toml").write_text("[tasks.start]\nrun='echo boot'\n")
    (repo_dir / "Cargo.toml").write_text("[package]\nname='sample-app'\nversion='0.1.0'\n")
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "main.rs").write_text("fn main() {}\n")

    result = runner.invoke(cli.app, ["deploy", str(repo_dir)])

    assert result.exit_code == 0
    assert checked_calls == [
        (
            ["bash", str(tmp_path / "den-project" / "scripts" / "generate-from-dhall.sh"), str(repo_dir / "den.dhall"), str(repo_dir)],
            None,
            None,
        ),
        (["sprite", "create", "den-repo", "--skip-console"], tmp_path / "den-project", None),
        (["sprite", "use", "den-repo"], repo_dir, None),
        (
            [
                "sprite",
                "-s",
                "den-repo",
                "exec",
                "--tty",
                "--dir",
                "/home/sprite/repo",
                "--",
                "bash",
                "-lc",
                "mise trust && mise run start",
            ],
            None,
            None,
        ),
    ]


def test_deploy_railway_uses_railway_up(monkeypatch, tmp_path) -> None:
    checked_calls: list[tuple[list[str], object | None, str | None]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del capture_output, error_hint
        checked_calls.append((cmd, cwd, input_text))
        return object()

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)
    monkeypatch.setattr(cli, "_command_exists", lambda name: False)
    monkeypatch.setattr(cli, "_sesame_command", lambda: (_ for _ in ()).throw(cli.CommandError("sesame executable not found")))
    monkeypatch.setattr(cli, "DHALL_DIR", tmp_path / "dhall")
    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path / "den-project")

    (tmp_path / "dhall").mkdir()
    (tmp_path / "den-project" / "scripts").mkdir(parents=True)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}))

    result = runner.invoke(cli.app, ["deploy", str(repo_dir), "--runtime", "railway"])

    assert result.exit_code == 0
    assert checked_calls == [
        (
            ["bash", str(tmp_path / "den-project" / "scripts" / "generate-from-dhall.sh"), str(repo_dir / "den.dhall"), str(repo_dir)],
            None,
            None,
        ),
        ([*cli.resolve_railway_command(), "status", "--json"], tmp_path / "den-project", None),
        ([*cli.resolve_railway_command(), "up", str(repo_dir), "--detach"], repo_dir, None),
    ]


def test_list_shows_url_and_auth_table(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_list_den_names", lambda: ["den-alpha", "den-beta"])

    call_count = 0

    def fake_run(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1
        if "url" in cmd:
            if "den-alpha" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="URL: https://den-alpha.sprites.app\nAuth: public\n", stderr="")
            if "den-beta" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="URL: https://den-beta.sprites.app\nAuth: sprite\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

    monkeypatch.setattr(cli, "_run", fake_run)

    result = runner.invoke(cli.app, ["list"])

    assert result.exit_code == 0
    assert "den-alpha" in result.stdout
    assert "den-beta" in result.stdout
    assert "https://den-alpha.sprites.app" in result.stdout
    assert "public" in result.stdout
    assert "sprite" in result.stdout


def test_list_json_output(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_list_den_names", lambda: ["den-alpha"])

    def fake_run(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout="URL: https://den-alpha.sprites.app\nAuth: public\n", stderr="")

    monkeypatch.setattr(cli, "_run", fake_run)

    result = runner.invoke(cli.app, ["list", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert payload[0]["name"] == "den-alpha"
    assert payload[0]["url"] == "https://den-alpha.sprites.app"
    assert payload[0]["auth"] == "public"


def test_list_handles_unavailable_url(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_list_den_names", lambda: ["den-broken"])

    def fake_run(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not found")

    monkeypatch.setattr(cli, "_run", fake_run)

    result = runner.invoke(cli.app, ["list"])

    assert result.exit_code == 0
    assert "den-broken" in result.stdout
    assert "(unavailable)" in result.stdout


def test_list_empty_json(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_list_den_names", lambda: [])

    result = runner.invoke(cli.app, ["list", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_list_railway_shows_den_projects(monkeypatch) -> None:
    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, capture_output, error_hint, input_text
        payload = [
            {"id": "p1", "name": "den-alpha", "workspace": {"name": "Main"}},
            {"id": "p2", "name": "other-project", "workspace": {"name": "Main"}},
        ]
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)

    result = runner.invoke(cli.app, ["list", "--runtime", "railway"])

    assert result.exit_code == 0
    assert "Dens in Railway" in result.stdout
    assert "den-alpha" in result.stdout
    assert "other-project" not in result.stdout


def test_list_railway_json_output(monkeypatch) -> None:
    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, capture_output, error_hint, input_text
        payload = [{"id": "p1", "name": "den-alpha", "workspace": {"name": "Main"}}]
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)

    result = runner.invoke(cli.app, ["list", "--runtime", "railway", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"name": "den-alpha", "project_id": "p1", "workspace": "Main"}]


def test_status_railway_renders_linked_project_summary(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_ensure_project_dir", lambda: None)

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, capture_output, error_hint, input_text
        payload = {
            "project": {"name": "den-myproject"},
            "environment": {"name": "production"},
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
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)

    result = runner.invoke(cli.app, ["status", "myproject", "--runtime", "railway"])

    assert result.exit_code == 0
    assert "Linked project: den-myproject" in result.stdout
    assert "Match:          yes" in result.stdout
    assert "dio-web: deployment=SUCCESS stopped=False" in result.stdout


def test_status_railway_service_renders_selected_service(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_ensure_project_dir", lambda: None)

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, capture_output, error_hint, input_text
        payload = {
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
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)

    result = runner.invoke(cli.app, ["status", "myproject", "--runtime", "railway", "--service", "dio-web"])

    assert result.exit_code == 0
    assert "Name:           dio-web" in result.stdout
    assert "Deployment:     SUCCESS" in result.stdout


def test_status_railway_service_rejects_unknown_service(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_ensure_project_dir", lambda: None)

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, capture_output, error_hint, input_text
        payload = {"project": {"name": "den-myproject"}, "environments": {"edges": []}}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)

    result = runner.invoke(cli.app, ["status", "myproject", "--runtime", "railway", "--service", "missing"])

    assert result.exit_code == 1
    assert isinstance(result.exception, cli.CommandError)
    assert "Railway service 'missing' not found" in str(result.exception)


def test_destroy_railway_deletes_matching_linked_project(monkeypatch) -> None:
    checked_calls: list[list[str]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, capture_output, error_hint, input_text
        checked_calls.append(cmd)
        if cmd == cli.railway_status_command():
            payload = {"project": {"name": "den-myproject"}}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)

    result = runner.invoke(cli.app, ["destroy", "myproject", "--runtime", "railway"], input="y\n")

    assert result.exit_code == 0
    assert checked_calls == [
        cli.railway_status_command(),
        cli.railway_delete_command("den-myproject"),
    ]


def test_destroy_railway_rejects_mismatched_linked_project(monkeypatch) -> None:
    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, capture_output, error_hint, input_text
        payload = {"project": {"name": "den-other"}}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)

    result = runner.invoke(cli.app, ["destroy", "myproject", "--runtime", "railway"], input="y\n")

    assert result.exit_code == 1
    assert isinstance(result.exception, cli.CommandError)
    assert "linked project is den-other" in str(result.exception)


def test_should_bundle_path_excludes_ignored_names() -> None:
    from pathlib import Path

    assert cli._should_bundle_path(Path("src/main.py")) is True
    assert cli._should_bundle_path(Path(".git")) is False
    assert cli._should_bundle_path(Path(".jj")) is False
    assert cli._should_bundle_path(Path(".venv")) is False
    assert cli._should_bundle_path(Path("node_modules")) is False
    assert cli._should_bundle_path(Path("target")) is False
    assert cli._should_bundle_path(Path("__pycache__")) is False
    assert cli._should_bundle_path(Path(".direnv")) is False
    assert cli._should_bundle_path(Path("foo.pyc")) is False
    assert cli._should_bundle_path(Path("foo.pyo")) is False
    assert cli._should_bundle_path(Path("regular_dir")) is True
    assert cli._should_bundle_path(Path("file.rs")) is True


def test_sync_repo_to_sprite_builds_tar_and_execs(monkeypatch, tmp_path) -> None:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('hello')")
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "pkg").write_text("")

    calls: list[tuple[list[str], bytes | None]] = []

    def fake_run_checked_binary(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_bytes: bytes | None = None,
    ) -> object:
        del cwd, capture_output, error_hint
        calls.append((cmd, input_bytes))
        return object()

    monkeypatch.setattr(cli, "_run_checked_binary", fake_run_checked_binary)

    result = cli._sync_repo_to_sprite("test", repo)

    assert result.startswith("/home/sprite/myrepo-")
    assert len(calls) == 1
    command, archive_bytes = calls[0]
    assert command[:5] == ["sprite", "-s", "den-test", "exec", "--"]
    assert archive_bytes is not None
    assert archive_bytes


def test_deploy_allows_explicit_command_override(monkeypatch, tmp_path) -> None:
    checked_calls: list[tuple[list[str], object | None, str | None]] = []

    def fake_run_checked(
        cmd: list[str],
        *,
        cwd=None,
        capture_output: bool = False,
        error_hint: str | None = None,
        input_text: str | None = None,
    ) -> object:
        del capture_output, error_hint
        checked_calls.append((cmd, cwd, input_text))
        return object()

    monkeypatch.setattr(cli, "_run_checked", fake_run_checked)
    monkeypatch.setattr(cli, "_command_exists", lambda name: False)
    monkeypatch.setattr(cli, "_sesame_command", lambda: (_ for _ in ()).throw(cli.CommandError("sesame executable not found")))
    monkeypatch.setattr(cli, "_list_den_names", lambda: ["den-repo"])
    monkeypatch.setattr(cli, "_sync_repo_to_sprite", lambda name, repo_dir: f"/home/sprite/{repo_dir.name}")
    monkeypatch.setattr(cli, "DHALL_DIR", tmp_path / "dhall")
    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path / "den-project")

    (tmp_path / "dhall").mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "den.dhall").write_text("existing")

    result = runner.invoke(cli.app, ["deploy", str(repo_dir), "--", "cargo", "run", "--", "tui"])

    assert result.exit_code == 0
    assert checked_calls == [
        (["sprite", "use", "den-repo"], repo_dir, None),
        (["sprite", "-s", "den-repo", "exec", "--tty", "--dir", "/home/sprite/repo", "--", "cargo", "run", "--", "tui"], None, None),
    ]
