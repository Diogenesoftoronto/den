from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from antithesis.assertions import always, reachable, sometimes
from antithesis.random import AntithesisRandom
from typer.testing import CliRunner

from den_cli import cli
from den_cli.core import (
    detect_project_markers,
    infer_den_setup,
    normalize_den_name,
    render_den_dhall,
    short_den_name,
    split_custom_domain,
    sprite_exec_command,
)


ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-"
TOKEN_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
runner = CliRunner()


def _random_token(rng: AntithesisRandom, *, min_size: int = 1, max_size: int = 12) -> str:
    size = rng.randint(min_size, max_size)
    return "".join(rng.choice(TOKEN_ALPHABET) for _ in range(size))


def _random_name(rng: AntithesisRandom) -> str:
    head = rng.choice("abcdefghijklmnopqrstuvwxyz0123456789")
    if rng.randint(0, 1) == 0:
        return head
    tail = "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 15)))
    candidate = (head + tail).rstrip("-")
    return candidate or "x"


@contextmanager
def _patched_setup_environment(base_dir: Path) -> object:
    original_run_checked = cli._run_checked
    original_command_exists = cli._command_exists
    original_sesame_command = cli._sesame_command
    original_dhall_dir = cli.DHALL_DIR
    original_project_dir = cli.PROJECT_DIR

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

    cli._run_checked = fake_run_checked
    cli._command_exists = lambda name: False
    cli._sesame_command = lambda: (_ for _ in ()).throw(cli.CommandError("sesame executable not found"))
    cli.DHALL_DIR = base_dir / "dhall"
    cli.PROJECT_DIR = base_dir / "den-project"

    try:
        yield calls
    finally:
        cli._run_checked = original_run_checked
        cli._command_exists = original_command_exists
        cli._sesame_command = original_sesame_command
        cli.DHALL_DIR = original_dhall_dir
        cli.PROJECT_DIR = original_project_dir


def _exercise_name_invariants(rng: AntithesisRandom) -> None:
    name = _random_name(rng)
    normalized = normalize_den_name(name)
    short = short_den_name(normalized)

    always(
        normalized.startswith("den-"),
        "normalize_den_name adds den prefix",
        {"name": name, "normalized": normalized},
    )
    always(
        normalize_den_name(normalized) == normalized,
        "normalize_den_name is idempotent",
        {"name": name, "normalized": normalized},
    )
    always(
        normalize_den_name(short) == normalized,
        "short_den_name round trips through normalize_den_name",
        {"name": name, "normalized": normalized, "short": short},
    )


def _exercise_sprite_exec_invariants(rng: AntithesisRandom) -> None:
    name = _random_name(rng)
    payload = [_random_token(rng) for _ in range(rng.randint(1, 4))]
    command = sprite_exec_command(name, payload)

    always(
        command[:4] == ["sprite", "-s", normalize_den_name(name), "exec"],
        "sprite_exec_command builds expected prefix",
        {"name": name, "command": command},
    )
    always(
        command[4:] == payload,
        "sprite_exec_command preserves payload argv",
        {"payload": payload, "command": command},
    )


def _exercise_domain_invariants(rng: AntithesisRandom) -> None:
    root = f"{_random_token(rng)}.com"
    nested_zone = f"dev.{root}"
    host = f"app.{nested_zone}"
    zone, subdomain = split_custom_domain(host, owned_domains=[root, nested_zone])

    always(
        zone == nested_zone,
        "split_custom_domain prefers the longest owned suffix",
        {"host": host, "zone": zone, "expected_zone": nested_zone},
    )
    always(
        subdomain == "app",
        "split_custom_domain preserves subdomain when owned suffix matches",
        {"host": host, "subdomain": subdomain},
    )


def _exercise_setup_inference_invariants(rng: AntithesisRandom) -> None:
    repo_name = _random_token(rng)
    with TemporaryDirectory() as raw_dir:
        root = Path(raw_dir) / repo_name
        root.mkdir()

        if rng.randint(0, 1) == 1:
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n")
        if rng.randint(0, 1) == 1:
            (root / "package.json").write_text("{}")
        if rng.randint(0, 1) == 1:
            (root / "bun.lock").write_text("")
        if rng.randint(0, 1) == 1:
            (root / "Dockerfile").write_text("FROM scratch\n")
        if rng.randint(0, 1) == 1:
            (root / "mise.toml").write_text("")

        markers = detect_project_markers(root)
        inferred = infer_den_setup(root)
        rendered = render_den_dhall(inferred, Path("/tmp/dhall"))

        always(
            inferred.name == repo_name,
            "infer_den_setup uses the repository directory name",
            {"repo_name": repo_name, "inferred_name": inferred.name},
        )
        always(
            ("Types.Backend.Nix" in rendered) or ("Types.Backend.Guix" in rendered),
            "render_den_dhall emits a concrete backend",
            {"backend": inferred.backend},
        )
        always(
            f'name = "{repo_name}"' in rendered,
            "render_den_dhall includes the inferred project name",
            {"repo_name": repo_name},
        )
        always(
            markers.has_package_json == (root / "package.json").is_file(),
            "detect_project_markers matches package.json presence",
            {"repo_name": repo_name, "has_package_json": markers.has_package_json},
        )

        if markers.has_pyproject and not (
            markers.has_bun_lock
            or markers.has_package_json
            or markers.has_mise_toml
            or markers.has_flox_toml
            or markers.has_nix_flake
            or markers.has_shell_nix
            or markers.has_dockerfile
            or markers.has_containerfile
            or markers.has_helm_chart
        ):
            sometimes(
                inferred.backend == "guix",
                "standalone pyproject repositories can infer guix backend",
                {"repo_name": repo_name, "backend": inferred.backend},
            )
            reachable(
                "standalone pyproject inference path reached",
                {"repo_name": repo_name},
            )


def _exercise_setup_state_transitions(rng: AntithesisRandom) -> None:
    repo_name = _random_token(rng)
    with TemporaryDirectory() as raw_dir:
        root = Path(raw_dir) / repo_name
        root.mkdir()

        states: list[str] = []

        def record_state(label: str) -> None:
            inferred = infer_den_setup(root)
            rendered = render_den_dhall(inferred, Path("/tmp/dhall"))
            states.append(f"{label}:{inferred.backend}")
            always(
                f'name = "{repo_name}"' in rendered,
                "rendered Dhall keeps the repo name across setup transitions",
                {"repo_name": repo_name, "label": label, "states": states},
            )
            always(
                f'mapKey = "DEN_BACKEND", mapValue = "{inferred.backend}"' in rendered,
                "rendered Dhall environment tracks inferred backend",
                {"repo_name": repo_name, "label": label, "backend": inferred.backend, "states": states},
            )

        record_state("empty")

        if rng.randint(0, 1) == 1:
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n")
            record_state("pyproject")

        if rng.randint(0, 1) == 1:
            (root / "package.json").write_text("{}")
            record_state("package_json")

        if rng.randint(0, 1) == 1:
            (root / "bun.lock").write_text("")
            record_state("bun_lock")

        if rng.randint(0, 1) == 1:
            (root / "Dockerfile").write_text("FROM scratch\n")
            record_state("dockerfile")

        if rng.randint(0, 1) == 1:
            (root / "guix").mkdir(exist_ok=True)
            (root / "guix" / "manifest.scm").write_text("")
            inferred = infer_den_setup(root)
            sometimes(
                inferred.backend == "guix",
                "adding guix metadata can force guix backend inference",
                {"repo_name": repo_name, "states": states, "backend": inferred.backend},
            )
            reachable(
                "guix metadata transition reached",
                {"repo_name": repo_name, "states": states},
            )
            record_state("guix_manifest")


def _exercise_setup_cli_semantics(rng: AntithesisRandom) -> None:
    repo_name = _random_token(rng)
    with TemporaryDirectory() as raw_dir:
        base_dir = Path(raw_dir)
        (base_dir / "dhall").mkdir()
        (base_dir / "den-project" / "scripts").mkdir(parents=True)
        repo_dir = base_dir / repo_name
        repo_dir.mkdir()

        if rng.randint(0, 1) == 1:
            (repo_dir / "pyproject.toml").write_text("[project]\nname='demo'\n")
        else:
            (repo_dir / "package.json").write_text("{}")
            if rng.randint(0, 1) == 1:
                (repo_dir / "bun.lock").write_text("")

        den_file = repo_dir / "den.dhall"
        with _patched_setup_environment(base_dir) as calls:
            print_result = runner.invoke(cli.app, ["setup", str(repo_dir), "--print"])
            always(
                print_result.exit_code == 0,
                "setup --print succeeds without writing",
                {"repo_name": repo_name, "stdout": print_result.stdout},
            )
            always(
                not den_file.exists(),
                "setup --print does not create den.dhall",
                {"repo_name": repo_name},
            )
            always(
                calls == [],
                "setup --print does not invoke the generator",
                {"repo_name": repo_name, "calls": calls},
            )

            first_result = runner.invoke(cli.app, ["setup", str(repo_dir)])
            first_contents = den_file.read_text() if den_file.exists() else ""
            always(
                first_result.exit_code == 0,
                "setup first write succeeds",
                {"repo_name": repo_name, "stdout": first_result.stdout},
            )
            always(
                den_file.exists(),
                "setup writes den.dhall on first non-print run",
                {"repo_name": repo_name},
            )
            always(
                len(calls) == 1,
                "setup first write invokes the generator once",
                {"repo_name": repo_name, "calls": calls},
            )

            second_result = runner.invoke(cli.app, ["setup", str(repo_dir)])
            always(
                second_result.exit_code == 1,
                "setup refuses to overwrite without force",
                {"repo_name": repo_name, "stdout": second_result.stdout},
            )
            always(
                den_file.read_text() == first_contents,
                "overwrite refusal leaves den.dhall unchanged",
                {"repo_name": repo_name},
            )
            reachable(
                "setup overwrite refusal path reached",
                {"repo_name": repo_name},
            )

            force_result = runner.invoke(cli.app, ["setup", str(repo_dir), "--force"])
            always(
                force_result.exit_code == 0,
                "setup --force succeeds after prior write",
                {"repo_name": repo_name, "stdout": force_result.stdout},
            )
            always(
                den_file.read_text() == first_contents,
                "setup --force is deterministic for an unchanged repo",
                {"repo_name": repo_name},
            )
            sometimes(
                len(calls) == 2,
                "setup --force invokes the generator on overwrite",
                {"repo_name": repo_name, "calls": calls},
            )


def main() -> None:
    rng = AntithesisRandom()
    for _ in range(256):
        _exercise_name_invariants(rng)
        _exercise_sprite_exec_invariants(rng)
        _exercise_domain_invariants(rng)
        _exercise_setup_inference_invariants(rng)
        _exercise_setup_state_transitions(rng)
        _exercise_setup_cli_semantics(rng)


if __name__ == "__main__":
    main()
