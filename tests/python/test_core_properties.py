from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from den_cli.core import (
    DnsRecord,
    DomainProvider,
    DenPeer,
    DomainMatch,
    InferredDenSetup,
    SpriteUrlInfo,
    build_cloudflare_dns_records,
    build_sesame_dns_create_command,
    build_sesame_dns_edit_command,
    build_sesame_dns_list_command,
    build_sesame_url_forward_command,
    detect_project_markers,
    extract_den_peers,
    extract_railway_linked_project_name,
    parse_railway_service_statuses,
    find_checkpoint_version_in_api_output,
    find_checkpoint_version_in_list_output,
    infer_den_setup,
    infer_run_command,
    make_sprite_redeploy_comment,
    normalize_den_name,
    parse_railway_projects,
    parse_sprite_url,
    parse_sprite_url_info,
    railway_delete_command,
    resolve_custom_domain,
    railway_domain_attach_command,
    railway_list_command,
    railway_status_command,
    render_den_dhall,
    sesame_dns_records_exist,
    short_den_name,
    split_custom_domain,
    sprite_command,
    sprite_exec_command,
    sprite_logs_command,
    sprite_restore_command,
    sprite_tty_exec_command,
    sprite_use_command,
)

SAFE_NAME = st.text(alphabet=st.characters(blacklist_characters=["\x00", "\n", "\r"]), min_size=1, max_size=48)
HOST_SAFE_NAME = st.text(
    alphabet=list("abcdefghijklmnopqrstuvwxyz0123456789-"),
    min_size=1,
    max_size=32,
).filter(lambda value: value[0] != "-" and value[-1] != "-")
SAFE_ARG = st.text(alphabet=st.characters(blacklist_characters=["\x00", "\n", "\r"]), min_size=1, max_size=24)
SAFE_TOKEN = st.text(alphabet=list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_:."), min_size=1, max_size=24)
SAFE_DIR_NAME = st.text(alphabet=list("abcdefghijklmnopqrstuvwxyz0123456789-_"), min_size=1, max_size=24)


@given(SAFE_NAME)
def test_normalize_den_name_is_idempotent(name: str) -> None:
    normalized = normalize_den_name(name)
    assert normalized.startswith("den-")
    assert normalize_den_name(normalized) == normalized


@given(SAFE_NAME)
def test_short_name_round_trip(name: str) -> None:
    normalized = normalize_den_name(name)
    short = short_den_name(normalized)
    assert normalize_den_name(short) == normalized


@given(SAFE_NAME)
def test_sprite_command_uses_normalized_name(name: str) -> None:
    command = sprite_command("url", sprite_name=name)
    assert command[0] == "sprite"
    assert "-s" in command
    sprite_name = command[command.index("-s") + 1]
    assert sprite_name.startswith("den-")


@given(SAFE_NAME, st.lists(SAFE_ARG, min_size=1, max_size=6))
def test_sprite_exec_command_preserves_payload(name: str, payload: list[str]) -> None:
    command = sprite_exec_command(name, payload)
    assert command[:5] == ["sprite", "-s", normalize_den_name(name), "exec", "--"]
    assert command[5:] == payload


@given(SAFE_NAME, st.lists(SAFE_ARG, min_size=1, max_size=6))
def test_sprite_tty_exec_command_preserves_payload(name: str, payload: list[str]) -> None:
    command = sprite_tty_exec_command(name, payload)
    assert command[:6] == ["sprite", "-s", normalize_den_name(name), "exec", "--tty", "--"]
    assert command[6:] == payload


@given(SAFE_NAME)
def test_sprite_use_command_targets_normalized_name(name: str) -> None:
    command = sprite_use_command(name)
    assert command == ["sprite", "use", normalize_den_name(name)]


@given(SAFE_NAME, st.none() | SAFE_ARG)
def test_sprite_logs_command_attaches_or_selects(name: str, selector: str | None) -> None:
    command = sprite_logs_command(name, selector)
    expected = ["sprite", "-s", normalize_den_name(name), "attach"]
    if selector is not None:
        expected.append(selector)
    assert command == expected


@given(SAFE_NAME)
def test_sprite_logs_command_list_mode_ignores_selector(name: str) -> None:
    command = sprite_logs_command(name, "ignored", list_only=True)
    assert command == ["sprite", "-s", normalize_den_name(name), "sessions", "list"]


@given(SAFE_NAME, SAFE_ARG)
def test_make_sprite_redeploy_comment_normalizes_name(name: str, nonce: str) -> None:
    comment = make_sprite_redeploy_comment(name, nonce)
    assert comment == f"den-redeploy:{normalize_den_name(name)}:{nonce}"


@given(SAFE_NAME, SAFE_ARG)
def test_sprite_restore_command_targets_normalized_name(name: str, version_id: str) -> None:
    command = sprite_restore_command(name, version_id)
    assert command == ["sprite", "-s", normalize_den_name(name), "restore", version_id]


@given(HOST_SAFE_NAME)
def test_parse_sprite_url_accepts_expected_line(name: str) -> None:
    output = f"URL: https://{normalize_den_name(name)}.sprites.app\nAuth: public\n"
    assert parse_sprite_url(output) == f"https://{normalize_den_name(name)}.sprites.app"


@given(SAFE_TOKEN, SAFE_TOKEN)
def test_find_checkpoint_version_in_api_output_handles_list_payload(version_id: str, comment: str) -> None:
    payload = json.dumps([{"id": version_id, "comment": comment}])
    assert find_checkpoint_version_in_api_output(payload, comment) == version_id


@given(SAFE_TOKEN, SAFE_TOKEN)
def test_find_checkpoint_version_in_api_output_handles_nested_payload(version_id: str, comment: str) -> None:
    payload = json.dumps({"data": [{"version": version_id, "comment": comment}]})
    assert find_checkpoint_version_in_api_output(payload, comment) == version_id


@given(SAFE_TOKEN, SAFE_TOKEN)
def test_find_checkpoint_version_in_list_output_matches_first_token(version_id: str, comment: str) -> None:
    output = f"{version_id}  {comment}  just-now\n"
    assert find_checkpoint_version_in_list_output(output, comment) == version_id


@given(
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.booleans(),
)
def test_detect_project_markers_matches_filesystem(
    has_package_json: bool,
    has_bun_lock: bool,
    has_pyproject: bool,
    has_cargo_toml: bool,
    has_dockerfile: bool,
    has_containerfile: bool,
    has_mise_toml: bool,
    has_flox_toml: bool,
    has_helm_chart: bool,
    has_nix_flake: bool,
    has_shell_nix: bool,
    has_guix_manifest: bool,
    has_guix_channels: bool,
) -> None:
    with tempfile.TemporaryDirectory() as raw_dir:
        tmp_path = Path(raw_dir)
        if has_package_json:
            (tmp_path / "package.json").write_text("{}")
        if has_bun_lock:
            (tmp_path / "bun.lock").write_text("")
        if has_pyproject:
            (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        if has_cargo_toml:
            (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\nversion='0.1.0'\n")
        if has_dockerfile:
            (tmp_path / "Dockerfile").write_text("FROM scratch\n")
        if has_containerfile:
            (tmp_path / "Containerfile").write_text("FROM scratch\n")
        if has_mise_toml:
            (tmp_path / "mise.toml").write_text("")
        if has_flox_toml:
            (tmp_path / "flox.toml").write_text("")
        if has_helm_chart:
            (tmp_path / "Chart.yaml").write_text("apiVersion: v2\n")
        if has_nix_flake:
            (tmp_path / "flake.nix").write_text("{}")
        if has_shell_nix:
            (tmp_path / "shell.nix").write_text("{}")
        if has_guix_manifest:
            (tmp_path / "guix").mkdir(exist_ok=True)
            (tmp_path / "guix" / "manifest.scm").write_text("")
        if has_guix_channels:
            (tmp_path / "guix").mkdir(exist_ok=True)
            (tmp_path / "guix" / "channels.scm").write_text("")

        markers = detect_project_markers(tmp_path)

        assert markers.has_package_json is has_package_json
        assert markers.has_bun_lock is has_bun_lock
        assert markers.has_pyproject is has_pyproject
        assert markers.has_cargo_toml is has_cargo_toml
        assert markers.has_dockerfile is has_dockerfile
        assert markers.has_containerfile is has_containerfile
        assert markers.has_mise_toml is has_mise_toml
        assert markers.has_flox_toml is has_flox_toml
        assert markers.has_helm_chart is has_helm_chart
        assert markers.has_nix_flake is has_nix_flake
        assert markers.has_shell_nix is has_shell_nix
        assert markers.has_guix_manifest is has_guix_manifest
        assert markers.has_guix_channels is has_guix_channels


@given(SAFE_DIR_NAME)
def test_infer_den_setup_prefers_guix_for_standalone_pyproject(name: str) -> None:
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir) / name
        root.mkdir()
        (root / "pyproject.toml").write_text("[project]\nname='x'\n")

        inferred = infer_den_setup(root)

        assert inferred.backend == "guix"
        assert any(reason == "standalone Python project detected" for reason in inferred.reasons)


@given(SAFE_DIR_NAME, st.sampled_from(["nix", "guix"]), st.lists(SAFE_TOKEN, unique=True, max_size=5))
def test_render_den_dhall_is_self_consistent(name: str, backend: str, packages: list[str]) -> None:
    config = InferredDenSetup(
        name=name,
        backend=backend,
        dockerfile="Dockerfile" if backend == "nix" else None,
        nix_packages=tuple(packages),
        guix_packages=tuple(packages),
        environment=(
            ("DEN_NAME", normalize_den_name(name)),
            ("DEN_BACKEND", backend),
            *((("DEN_DOCKERFILE", "Dockerfile"),) if backend == "nix" else ()),
        ),
        reasons=("test",),
    )

    rendered = render_den_dhall(config, Path("/tmp/dhall"))

    assert f'name = "{name}"' in rendered
    assert f"backend = Types.Backend.{backend.capitalize()}" in rendered
    assert f'mapKey = "DEN_NAME", mapValue = "{normalize_den_name(name)}"' in rendered
    assert f'mapKey = "DEN_BACKEND", mapValue = "{backend}"' in rendered
    assert ('dockerfile = Some "Dockerfile"' in rendered) == (backend == "nix")
    assert ('mapKey = "DEN_DOCKERFILE"' in rendered) == (backend == "nix")
    for package in packages:
        assert f'name = "{package}", version = None Text' in rendered
    assert ('nix = Some' in rendered) == (backend == "nix")
    assert ('guix = Some' in rendered) == (backend == "guix")


@given(SAFE_DIR_NAME)
def test_infer_den_setup_bun_projects_prefer_nix(name: str) -> None:
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir) / name
        root.mkdir()
        (root / "package.json").write_text("{}")
        (root / "bun.lock").write_text("")

        inferred = infer_den_setup(root)

        assert inferred.backend == "nix"
        assert "bun lockfile detected" in inferred.reasons
        assert "bun" in inferred.nix_packages


@given(SAFE_DIR_NAME)
def test_infer_den_setup_cargo_projects_prefer_nix(name: str) -> None:
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir) / name
        root.mkdir()
        (root / "Cargo.toml").write_text("[package]\nname='sample-app'\nversion='0.1.0'\n")
        (root / "src").mkdir()
        (root / "src" / "main.rs").write_text("fn main() {}\n")

        inferred = infer_den_setup(root)

        assert inferred.backend == "nix"
        assert "Cargo.toml detected" in inferred.reasons
        assert "cargo" in inferred.nix_packages
        assert "rustc" in inferred.nix_packages


@given(SAFE_DIR_NAME)
def test_infer_den_setup_guix_markers_dominate_other_signals(name: str) -> None:
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir) / name
        root.mkdir()
        (root / "package.json").write_text("{}")
        (root / "Dockerfile").write_text("FROM scratch\n")
        (root / "guix").mkdir()
        (root / "guix" / "manifest.scm").write_text("")

        inferred = infer_den_setup(root)

        assert inferred.backend == "guix"
        assert inferred.reasons == ("existing Guix manifests detected",)


@given(SAFE_DIR_NAME)
def test_infer_den_setup_is_stable_under_irrelevant_files(name: str) -> None:
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir) / name
        root.mkdir()
        (root / "pyproject.toml").write_text("[project]\nname='x'\n")

        before = infer_den_setup(root)
        (root / "README.md").write_text("# hello\n")
        (root / ".env.example").write_text("X=1\n")
        (root / "notes.txt").write_text("ignore me\n")
        after = infer_den_setup(root)

        assert before == after


@given(SAFE_DIR_NAME)
def test_infer_run_command_prefers_bun_dev_script(name: str) -> None:
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir) / name
        root.mkdir()
        (root / "package.json").write_text(json.dumps({"scripts": {"dev": "bun run server.ts"}}))
        (root / "bun.lock").write_text("")

        inferred = infer_run_command(root)

        assert inferred is not None
        assert inferred.command == ("bun", "run", "dev")
        assert 'package.json script "dev" detected' in inferred.reasons


@given(SAFE_DIR_NAME)
def test_infer_run_command_uses_project_script_for_pyproject(name: str) -> None:
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir) / name
        root.mkdir()
        (root / "pyproject.toml").write_text(
            "[project]\nname='sample-app'\n[project.scripts]\nserve='sample_app:main'\n"
        )

        inferred = infer_run_command(root)

        assert inferred is not None
        assert inferred.command == ("uv", "run", "serve")
        assert 'project.scripts entry "serve" detected' in inferred.reasons


@given(SAFE_DIR_NAME)
def test_infer_run_command_uses_python_module_when_project_module_exists(name: str) -> None:
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir) / name
        root.mkdir()
        (root / "pyproject.toml").write_text("[project]\nname='sample-app'\n")
        (root / "src").mkdir()
        (root / "src" / "sample_app").mkdir()

        inferred = infer_run_command(root)

        assert inferred is not None
        assert inferred.command == ("uv", "run", "python", "-m", "sample_app")
        assert 'Python module "sample_app" detected' in inferred.reasons


@given(SAFE_DIR_NAME)
def test_infer_run_command_uses_cargo_run_for_src_main(name: str) -> None:
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir) / name
        root.mkdir()
        (root / "Cargo.toml").write_text("[package]\nname='sample-app'\nversion='0.1.0'\n")
        (root / "src").mkdir()
        (root / "src" / "main.rs").write_text("fn main() {}\n")

        inferred = infer_run_command(root)

        assert inferred is not None
        assert inferred.command == ("cargo", "run")
        assert "Cargo.toml detected" in inferred.reasons
        assert "src/main.rs detected" in inferred.reasons


@given(SAFE_DIR_NAME)
def test_infer_run_command_prefers_mise_start_task_over_cargo(name: str) -> None:
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir) / name
        root.mkdir()
        (root / "mise.toml").write_text("[tasks.start]\nrun='echo boot'\n")
        (root / "Cargo.toml").write_text("[package]\nname='sample-app'\nversion='0.1.0'\n")
        (root / "src").mkdir()
        (root / "src" / "main.rs").write_text("fn main() {}\n")

        inferred = infer_run_command(root)

        assert inferred is not None
        assert inferred.command == ("bash", "-lc", "mise trust && mise run start")
        assert "mise.toml detected" in inferred.reasons
        assert 'mise task "start" detected' in inferred.reasons


PEER_VALUE = st.one_of(
    st.integers(),
    st.text(max_size=20),
    st.none(),
    st.booleans(),
    st.fixed_dictionaries(
        {
            "HostName": st.one_of(st.text(max_size=24), st.integers(), st.none()),
            "TailscaleIPs": st.one_of(
                st.lists(st.one_of(st.text(max_size=24), st.integers(), st.none()), max_size=4),
                st.text(max_size=24),
                st.none(),
            ),
            "Online": st.one_of(st.booleans(), st.integers(), st.text(max_size=8), st.none()),
        },
        optional={"Extra": st.one_of(st.integers(), st.text(max_size=12))},
    ),
)

PEER_MAP = st.dictionaries(
    keys=st.text(min_size=1, max_size=10),
    values=PEER_VALUE,
    max_size=20,
)


def _reference_extract(peer_map: Mapping[str, object]) -> list[DenPeer]:
    peers: list[DenPeer] = []
    for raw_peer in peer_map.values():
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


@given(PEER_MAP)
def test_extract_den_peers_matches_reference_model(peer_map: Mapping[str, object]) -> None:
    payload = {"Peer": dict(peer_map)}
    result = extract_den_peers(payload)
    expected = _reference_extract(peer_map)
    assert result == expected


@given(
    st.one_of(
        st.none(),
        st.integers(),
        st.text(max_size=30),
        st.lists(st.integers(), max_size=5),
        st.dictionaries(st.text(max_size=10), st.integers(), max_size=6),
    )
)
def test_extract_den_peers_handles_non_mapping_peer_values(peer_value: object) -> None:
    payload = {"Peer": peer_value}
    result = extract_den_peers(payload)
    assert isinstance(result, list)
    assert result == []


VALID_HOST = st.text(alphabet=st.characters(blacklist_characters=["\x00", "\n", "\r"]), min_size=1, max_size=18).map(
    lambda x: f"den-{x}"
)


@given(
    st.lists(
        st.tuples(
            VALID_HOST,
            st.one_of(st.text(max_size=24), st.just("-")),
            st.booleans(),
        ),
        unique_by=lambda tup: tup[0],
        max_size=20,
    )
)
def test_extract_den_peers_is_order_independent_for_unique_hosts(rows: list[tuple[str, str, bool]]) -> None:
    peer_map_forward: dict[str, object] = {}
    peer_map_reverse: dict[str, object] = {}

    for idx, (host, ip, online) in enumerate(rows):
        peer_map_forward[f"k{idx}"] = {
            "HostName": host,
            "TailscaleIPs": [ip],
            "Online": online,
        }

    for idx, (host, ip, online) in enumerate(reversed(rows)):
        peer_map_reverse[f"k{idx}"] = {
            "HostName": host,
            "TailscaleIPs": [ip],
            "Online": online,
        }

    forward = extract_den_peers({"Peer": peer_map_forward})
    reverse = extract_den_peers({"Peer": peer_map_reverse})
    assert forward == reverse


def test_split_custom_domain_prefers_owned_domain_match() -> None:
    zone, subdomain = split_custom_domain("app.dev.example.com", owned_domains=["example.com", "dev.example.com"])
    assert zone == "dev.example.com"
    assert subdomain == "app"


def test_split_custom_domain_falls_back_to_last_two_labels() -> None:
    zone, subdomain = split_custom_domain("preview.example.com")
    assert zone == "example.com"
    assert subdomain == "preview"


def test_split_custom_domain_handles_apex_domain() -> None:
    zone, subdomain = split_custom_domain("example.com", owned_domains=["example.com"])
    assert zone == "example.com"
    assert subdomain is None


def test_resolve_custom_domain_prefers_longest_matching_provider_zone() -> None:
    match = resolve_custom_domain(
        "app.dev.example.com",
        {
            DomainProvider.cloudflare: ["example.com"],
            DomainProvider.sesame: ["dev.example.com"],
        },
    )
    assert match == DomainMatch(provider=DomainProvider.sesame, zone="dev.example.com", subdomain="app")


def test_resolve_custom_domain_rejects_unknown_ownership() -> None:
    try:
        resolve_custom_domain(
            "app.unknown.example",
            {
                DomainProvider.cloudflare: ["example.com"],
                DomainProvider.sesame: ["dev.example.com"],
            },
        )
    except ValueError as exc:
        assert "Could not determine who holds" in str(exc)
    else:
        raise AssertionError("expected resolve_custom_domain to reject unknown ownership")


def test_build_sesame_url_forward_command_uses_resolved_zone() -> None:
    command = build_sesame_url_forward_command(
        "app.dev.example.com",
        "https://den-example.sprites.app",
        ["example.com", "dev.example.com"],
    )
    assert command == [
        "domain",
        "add-url-forward",
        "dev.example.com",
        "--location",
        "https://den-example.sprites.app",
        "--type",
        "permanent",
        "--include-path",
        "yes",
        "--subdomain",
        "app",
    ]


def test_build_sesame_dns_commands_handle_apex_and_subdomains() -> None:
    subdomain_record = DnsRecord(type="CNAME", name="app", content="edge.railway.app")
    apex_record = DnsRecord(type="TXT", name="@", content="railway-verify=abc123")

    assert build_sesame_dns_list_command("example.com", subdomain_record) == [
        "dns",
        "list-by-name-type",
        "example.com",
        "--type",
        "CNAME",
        "--json",
        "--subdomain",
        "app",
    ]
    assert build_sesame_dns_create_command("example.com", subdomain_record) == [
        "dns",
        "create",
        "example.com",
        "--type",
        "CNAME",
        "--content",
        "edge.railway.app",
        "--json",
        "--name",
        "app",
    ]
    assert build_sesame_dns_edit_command("example.com", apex_record) == [
        "dns",
        "edit-by-name-type",
        "example.com",
        "--type",
        "TXT",
        "--content",
        "railway-verify=abc123",
        "--json",
    ]


def test_sesame_dns_records_exist_accepts_cli_payload_shapes() -> None:
    assert sesame_dns_records_exist([{"id": "1"}]) is True
    assert sesame_dns_records_exist({"records": [{"id": "1"}]}) is True
    assert sesame_dns_records_exist([]) is False
    assert sesame_dns_records_exist({"records": []}) is False


def test_build_cloudflare_dns_records_prefers_cname_for_subdomain() -> None:
    records = build_cloudflare_dns_records(
        "app.example.com",
        "example.com",
        {
            "cname": "den-myproject.fly.dev",
            "ownership": {"name": "_fly-ownership.app.example.com", "app_value": "app-123"},
        },
        proxied=True,
    )
    assert records == [
        DnsRecord(type="TXT", name="_fly-ownership.app", content="app-123"),
        DnsRecord(type="CNAME", name="app", content="den-myproject.fly.dev", proxied=True),
    ]


def test_build_cloudflare_dns_records_uses_apex_a_and_aaaa() -> None:
    records = build_cloudflare_dns_records(
        "example.com",
        "example.com",
        {
            "a": ["203.0.113.10"],
            "aaaa": ["2001:db8::10"],
            "ownership": {"name": "_fly-ownership.example.com", "app_value": "app-123"},
        },
    )
    assert records == [
        DnsRecord(type="TXT", name="_fly-ownership", content="app-123"),
        DnsRecord(type="A", name="@", content="203.0.113.10", proxied=False),
        DnsRecord(type="AAAA", name="@", content="2001:db8::10", proxied=False),
    ]


def test_railway_domain_attach_command_includes_service_and_port(monkeypatch) -> None:
    monkeypatch.setattr("den_cli.core.resolve_railway_command", lambda: ["railway"])
    command = railway_domain_attach_command("web", "app.example.com", port=8080)
    assert command == ["railway", "domain", "app.example.com", "--service", "web", "--json", "--port", "8080"]


def test_railway_status_and_list_commands_use_json(monkeypatch) -> None:
    monkeypatch.setattr("den_cli.core.resolve_railway_command", lambda: ["railway"])
    assert railway_status_command() == ["railway", "status", "--json"]
    assert railway_list_command() == ["railway", "list", "--json"]


def test_railway_delete_command_targets_explicit_project(monkeypatch) -> None:
    monkeypatch.setattr("den_cli.core.resolve_railway_command", lambda: ["railway"])
    assert railway_delete_command("den-demo") == ["railway", "delete", "-p", "den-demo", "-y", "--json"]


def test_parse_railway_projects_extracts_project_metadata() -> None:
    payload = [
        {
            "id": "proj-1",
            "name": "den-alpha",
            "workspace": {"name": "Main"},
        },
        {
            "id": "proj-2",
            "name": "other-project",
            "workspace": {"name": "Main"},
        },
    ]

    projects = parse_railway_projects(payload)

    assert [(project.name, project.project_id, project.workspace_name) for project in projects] == [
        ("den-alpha", "proj-1", "Main"),
        ("other-project", "proj-2", "Main"),
    ]


def test_extract_railway_linked_project_name_prefers_nested_project_name() -> None:
    payload = {"project": {"name": "den-linked"}}
    assert extract_railway_linked_project_name(payload) == "den-linked"


def test_extract_railway_linked_project_name_accepts_project_shaped_root_payload() -> None:
    payload = {"name": "den-linked", "services": {}, "environments": {}}
    assert extract_railway_linked_project_name(payload) == "den-linked"


def test_parse_railway_service_statuses_extracts_service_summaries() -> None:
    payload = {
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
                                },
                                {
                                    "node": {
                                        "id": "inst-2",
                                        "serviceId": "svc-2",
                                        "serviceName": "worker",
                                        "latestDeployment": {
                                            "id": "dep-2",
                                            "status": "FAILED",
                                            "deploymentStopped": True,
                                        },
                                    }
                                },
                            ]
                        }
                    }
                }
            ]
        }
    }

    services = parse_railway_service_statuses(payload)

    assert [(entry.name, entry.latest_deployment_status, entry.deployment_stopped) for entry in services] == [
        ("dio-web", "SUCCESS", False),
        ("worker", "FAILED", True),
    ]


@given(HOST_SAFE_NAME, st.sampled_from(["public", "sprite"]))
def test_parse_sprite_url_info_extracts_url_and_auth(name: str, auth: str) -> None:
    den_name = normalize_den_name(name)
    output = f"URL: https://{den_name}.sprites.app\nAuth: {auth}\n"
    info = parse_sprite_url_info(output)
    assert info.url == f"https://{den_name}.sprites.app"
    assert info.auth == auth


@given(HOST_SAFE_NAME)
def test_parse_sprite_url_info_handles_missing_auth(name: str) -> None:
    den_name = normalize_den_name(name)
    output = f"URL: https://{den_name}.sprites.app\n"
    info = parse_sprite_url_info(output)
    assert info.url == f"https://{den_name}.sprites.app"
    assert info.auth is None


def test_parse_sprite_url_info_handles_empty_output() -> None:
    info = parse_sprite_url_info("")
    assert info == SpriteUrlInfo(url=None, auth=None)


def test_parse_sprite_url_info_agrees_with_parse_sprite_url() -> None:
    output = "URL: https://den-test.sprites.app\nAuth: public\n"
    assert parse_sprite_url(output) == parse_sprite_url_info(output).url
