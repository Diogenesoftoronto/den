//! Proptest parity with `tests/python/test_core_properties.py`.
//!
//! Each test in this file mirrors a `@given` test from the Hypothesis
//! suite 1:1. When a function is ported into `den-core`, its property
//! test is ported here in the same order so parity is auditable.

use den_core::{
    make_sprite_redeploy_comment, normalize_den_name, short_den_name, sprite_checkpoint_create_command,
    sprite_command, sprite_exec_command, sprite_logs_command, sprite_restore_command,
    sprite_tty_exec_command, sprite_use_command,
    build_sesame_dns_create_command, build_sesame_dns_edit_command, build_sesame_dns_list_command,
    build_sesame_url_forward_command, resolve_custom_domain, sesame_dns_records_exist,
    sesame_record_subdomain, split_custom_domain,
    DomainError, DomainProvider, DnsRecord, DomainMode,
    normalize_dns_name,
    railway_delete_command, railway_domain_attach_command, railway_status_command,
    railway_list_command, parse_railway_projects, extract_railway_linked_project_name,
    parse_railway_service_statuses,
    fly_certs_add_command, fly_certs_check_command, fly_certs_setup_command,
    infer_backend, infer_nix_packages, infer_guix_packages, Backend,
    ProjectMarkers, render_den_dhall, InferredDenSetup,
    parse_sprite_url, parse_sprite_url_info,
    find_checkpoint_version_in_api_output, find_checkpoint_version_in_list_output,
    extract_den_peers,
    RuntimeProvider,
};
use proptest::prelude::*;
use std::collections::HashMap;

fn safe_name() -> impl Strategy<Value = String> {
    "[^\\x00-\\x1f]{1,48}".prop_filter("non-empty after trim", |s| !s.is_empty())
}

fn safe_arg() -> impl Strategy<Value = String> {
    "[^\\x00-\\x1f]{1,24}".prop_filter("non-empty", |s| !s.is_empty())
}

fn safe_token() -> impl Strategy<Value = String> {
    "[A-Za-z0-9_:.\\-]{1,24}"
}

fn safe_domain_label() -> impl Strategy<Value = String> {
    "[a-z0-9]([a-z0-9\\-]{0,61}[a-z0-9])?".prop_filter("non-empty", |s| !s.is_empty())
}

fn safe_host() -> impl Strategy<Value = String> {
    (safe_domain_label(), safe_domain_label())
        .prop_map(|(a, b)| format!("{a}.{b}"))
}

proptest! {
    #[test]
    fn normalize_den_name_is_idempotent(name in safe_name()) {
        let normalized = normalize_den_name(&name);
        prop_assert!(normalized.starts_with("den-"));
        prop_assert_eq!(normalize_den_name(&normalized), normalized.clone());
    }

    #[test]
    fn short_name_round_trip(name in safe_name()) {
        let normalized = normalize_den_name(&name);
        let short = short_den_name(&normalized);
        prop_assert_eq!(normalize_den_name(&short), normalized);
    }

    #[test]
    fn sprite_command_uses_normalized_name(name in safe_name()) {
        let cmd = sprite_command(&["url"], Some(&name));
        prop_assert_eq!(&cmd[0], "sprite");
        let s_idx = cmd.iter().position(|a| a == "-s").expect("-s flag present");
        prop_assert!(cmd[s_idx + 1].starts_with("den-"));
    }

    #[test]
    fn sprite_exec_command_preserves_payload(
        name in safe_name(),
        payload in prop::collection::vec(safe_arg(), 1..7),
    ) {
        let cmd = sprite_exec_command(&name, &payload);
        let head = &cmd[..5];
        prop_assert_eq!(head, &[
            "sprite".to_string(),
            "-s".to_string(),
            normalize_den_name(&name),
            "exec".to_string(),
            "--".to_string(),
        ]);
        prop_assert_eq!(&cmd[5..], payload.as_slice());
    }

    #[test]
    fn sprite_tty_exec_command_preserves_payload(
        name in safe_name(),
        payload in prop::collection::vec(safe_arg(), 1..7),
    ) {
        let cmd = sprite_tty_exec_command(&name, &payload);
        let head = &cmd[..6];
        prop_assert_eq!(head, &[
            "sprite".to_string(),
            "-s".to_string(),
            normalize_den_name(&name),
            "exec".to_string(),
            "--tty".to_string(),
            "--".to_string(),
        ]);
        prop_assert_eq!(&cmd[6..], payload.as_slice());
    }

    #[test]
    fn sprite_use_command_targets_normalized_name(name in safe_name()) {
        let cmd = sprite_use_command(&name);
        prop_assert_eq!(cmd, vec![
            "sprite".to_string(),
            "use".to_string(),
            normalize_den_name(&name),
        ]);
    }

    #[test]
    fn sprite_logs_command_attaches_or_selects(
        name in safe_name(),
        selector in prop::option::of(safe_arg()),
    ) {
        let cmd = sprite_logs_command(&name, selector.as_deref(), false);
        let mut expected = vec![
            "sprite".to_string(),
            "-s".to_string(),
            normalize_den_name(&name),
            "attach".to_string(),
        ];
        if let Some(sel) = selector.as_ref() {
            expected.push(sel.clone());
        }
        prop_assert_eq!(cmd, expected);
    }

    #[test]
    fn sprite_logs_command_list_mode_ignores_selector(name in safe_name()) {
        let cmd = sprite_logs_command(&name, Some("ignored"), true);
        prop_assert_eq!(cmd, vec![
            "sprite".to_string(),
            "-s".to_string(),
            normalize_den_name(&name),
            "sessions".to_string(),
            "list".to_string(),
        ]);
    }

    #[test]
    fn sprite_checkpoint_create_command_wires_comment(
        name in safe_name(),
        comment in safe_arg(),
    ) {
        let cmd = sprite_checkpoint_create_command(&name, &comment);
        prop_assert_eq!(cmd, vec![
            "sprite".to_string(),
            "-s".to_string(),
            normalize_den_name(&name),
            "checkpoint".to_string(),
            "create".to_string(),
            "--comment".to_string(),
            comment,
        ]);
    }

    #[test]
    fn sprite_restore_command_wires_version(
        name in safe_name(),
        version in safe_token(),
    ) {
        let cmd = sprite_restore_command(&name, &version);
        prop_assert_eq!(cmd, vec![
            "sprite".to_string(),
            "-s".to_string(),
            normalize_den_name(&name),
            "restore".to_string(),
            version,
        ]);
    }

    #[test]
    fn redeploy_comment_format(name in safe_name(), nonce in safe_token()) {
        let comment = make_sprite_redeploy_comment(&name, &nonce);
        let expected = format!("den-redeploy:{}:{}", normalize_den_name(&name), nonce);
        prop_assert_eq!(comment, expected);
    }

    // --- Domain proptests ---

    #[test]
    fn split_custom_domain_apex_has_no_subdomain(host in safe_host()) {
        let (zone, subdomain) = split_custom_domain(&host, None).unwrap();
        if zone == host.to_lowercase() {
            prop_assert!(subdomain.is_none());
        }
    }

    #[test]
    fn split_custom_domain_with_owned_zone_longest_match(
        _host in safe_host(),
        zone_label in safe_domain_label(),
    ) {
        let zone = format!("{zone_label}.example.com");
        let full_host = format!("sub.{zone}");
        let (resolved_zone, subdomain) = split_custom_domain(&full_host, Some(&[zone.clone(), "example.com".to_string()])).unwrap();
        prop_assert_eq!(resolved_zone, zone.to_lowercase());
        prop_assert_eq!(subdomain, Some("sub".to_string()));
    }

    #[test]
    fn split_custom_domain_invalid_host(name in "[a-z]{0,1}") {
        let result = split_custom_domain(&name, None);
        prop_assert!(matches!(result, Err(DomainError::InvalidHost(_))));
    }

    #[test]
    fn resolve_custom_domain_no_owner(host in safe_host()) {
        let provider_domains = HashMap::new();
        let result = resolve_custom_domain(&host, &provider_domains);
        prop_assert!(matches!(result, Err(DomainError::NoOwner(_))));
    }

    #[test]
    fn resolve_custom_domain_sesame_match(host in safe_host()) {
        let mut provider_domains = HashMap::new();
        provider_domains.insert(DomainProvider::Sesame, vec![host.to_lowercase()]);
        let result = resolve_custom_domain(&host, &provider_domains).unwrap();
        prop_assert_eq!(result.provider, DomainProvider::Sesame);
        prop_assert!(result.subdomain.is_none());
    }

    #[test]
    fn resolve_custom_domain_longest_suffix_wins(
        subdomain in safe_domain_label(),
        zone_label in safe_domain_label(),
    ) {
        let zone = format!("{zone_label}.example.com");
        let full_host = format!("{subdomain}.{zone}");
        let mut provider_domains = HashMap::new();
        provider_domains.insert(DomainProvider::Cloudflare, vec!["example.com".to_string()]);
        provider_domains.insert(DomainProvider::Sesame, vec![zone.to_lowercase()]);
        let result = resolve_custom_domain(&full_host, &provider_domains).unwrap();
        prop_assert_eq!(result.provider, DomainProvider::Sesame);
        prop_assert_eq!(result.zone, zone.to_lowercase());
    }

    #[test]
    fn sesame_record_subdomain_normalizes(name in safe_domain_label()) {
        let result = sesame_record_subdomain(&name);
        prop_assert_eq!(result, Some(name.to_lowercase()));
    }

    #[test]
    fn build_sesame_dns_list_command_structure(zone in safe_domain_label()) {
        let record = DnsRecord {
            record_type: "CNAME".to_string(),
            name: "www".to_string(),
            content: "target.example.com".to_string(),
            proxied: false,
        };
        let cmd = build_sesame_dns_list_command(&zone, &record);
        prop_assert!(cmd[0] == "dns");
        prop_assert!(cmd[1] == "list-by-name-type");
        prop_assert!(cmd.contains(&"--type".to_string()));
        prop_assert!(cmd.contains(&"--json".to_string()));
    }

    #[test]
    fn build_sesame_dns_create_command_structure(zone in safe_domain_label()) {
        let record = DnsRecord {
            record_type: "A".to_string(),
            name: "@".to_string(),
            content: "1.2.3.4".to_string(),
            proxied: false,
        };
        let cmd = build_sesame_dns_create_command(&zone, &record);
        prop_assert!(cmd[0] == "dns");
        prop_assert!(cmd[1] == "create");
        prop_assert!(cmd.contains(&"--content".to_string()));
    }

    #[test]
    fn build_sesame_dns_edit_command_structure(zone in safe_domain_label()) {
        let record = DnsRecord {
            record_type: "TXT".to_string(),
            name: "_acme-challenge".to_string(),
            content: "token-value".to_string(),
            proxied: false,
        };
        let cmd = build_sesame_dns_edit_command(&zone, &record);
        prop_assert!(cmd[0] == "dns");
        prop_assert!(cmd[1] == "edit-by-name-type");
        prop_assert!(cmd.contains(&"--subdomain".to_string()));
    }

    #[test]
    fn build_sesame_url_forward_command_structure(zone in safe_domain_label()) {
        let custom_domain = format!("sub.{zone}");
        let owned = vec![zone.to_lowercase()];
        let cmd = build_sesame_url_forward_command(&custom_domain, "https://target.example.com", &owned).unwrap();
        prop_assert!(cmd[0] == "domain");
        prop_assert!(cmd[1] == "add-url-forward");
        prop_assert!(cmd.contains(&"--location".to_string()));
        prop_assert!(cmd.contains(&"--type".to_string()));
        prop_assert!(cmd.contains(&"permanent".to_string()));
    }

    #[test]
    fn normalize_dns_name_apex(zone in safe_domain_label()) {
        prop_assert_eq!(normalize_dns_name(&zone, &zone), "@");
    }

    #[test]
    fn normalize_dns_name_subdomain(zone in safe_domain_label(), sub in safe_domain_label()) {
        let fqdn = format!("{sub}.{zone}");
        let result = normalize_dns_name(&fqdn, &zone);
        prop_assert_eq!(result, sub.to_lowercase());
    }
}

// --- Deterministic (non-proptest) domain tests ---

#[test]
fn sesame_record_subdomain_apex_is_none() {
    assert_eq!(sesame_record_subdomain("@"), None);
    assert_eq!(sesame_record_subdomain(""), None);
}

#[test]
fn sesame_dns_records_exist_empty_object() {
    let payload = serde_json::json!({});
    assert!(!sesame_dns_records_exist(&payload));
}

#[test]
fn sesame_dns_records_exist_with_records() {
    let payload = serde_json::json!({"records": [{"id": "1", "name": "test", "type": "A", "content": "1.2.3.4", "ttl": "300", "notes": ""}]});
    assert!(sesame_dns_records_exist(&payload));
}

#[test]
fn domain_provider_display() {
    assert_eq!(format!("{}", DomainProvider::Cloudflare), "cloudflare");
    assert_eq!(format!("{}", DomainProvider::Sesame), "sesame");
}

#[test]
fn domain_mode_display() {
    assert_eq!(format!("{}", DomainMode::Dns), "dns");
    assert_eq!(format!("{}", DomainMode::Forward), "forward");
}

// --- Railway proptests ---

proptest! {
    #[test]
    fn railway_delete_command_structure(project in safe_name()) {
        let cmd = railway_delete_command(&project, true, true).unwrap();
        prop_assert!(cmd.contains(&"delete".to_string()));
        prop_assert!(cmd.contains(&"-p".to_string()));
        prop_assert!(cmd.contains(&project));
        prop_assert!(cmd.contains(&"-y".to_string()));
        prop_assert!(cmd.contains(&"--json".to_string()));
    }

    #[test]
    fn railway_delete_command_no_flags(project in safe_name()) {
        let cmd = railway_delete_command(&project, false, false).unwrap();
        prop_assert!(cmd.contains(&"delete".to_string()));
        prop_assert!(cmd.contains(&project));
        prop_assert!(!cmd.contains(&"-y".to_string()));
        prop_assert!(!cmd.contains(&"--json".to_string()));
    }

    #[test]
    fn railway_domain_attach_command_structure(
        service in safe_name(),
        domain in safe_domain_label(),
    ) {
        let cmd = railway_domain_attach_command(&service, &domain, None).unwrap();
        prop_assert!(cmd.contains(&"domain".to_string()));
        prop_assert!(cmd.contains(&domain));
        prop_assert!(cmd.contains(&"--service".to_string()));
        prop_assert!(cmd.contains(&service));
        prop_assert!(cmd.contains(&"--json".to_string()));
    }

    #[test]
    fn railway_domain_attach_command_with_port(
        service in safe_name(),
        domain in safe_domain_label(),
        port in 1u16..65535u16,
    ) {
        let cmd = railway_domain_attach_command(&service, &domain, Some(port)).unwrap();
        prop_assert!(cmd.contains(&"--port".to_string()));
        prop_assert!(cmd.contains(&port.to_string()));
    }

    #[test]
    fn railway_status_command_has_json_flag(dummy in safe_token()) {
        let _ = dummy;
        let cmd = railway_status_command().unwrap();
        prop_assert!(cmd.contains(&"status".to_string()));
        prop_assert!(cmd.contains(&"--json".to_string()));
    }

    #[test]
    fn railway_list_command_has_json_flag(dummy in safe_token()) {
        let _ = dummy;
        let cmd = railway_list_command().unwrap();
        prop_assert!(cmd.contains(&"list".to_string()));
        prop_assert!(cmd.contains(&"--json".to_string()));
    }
}

#[test]
fn parse_railway_projects_empty_array() {
    let payload = serde_json::json!([]);
    let result = parse_railway_projects(&payload).unwrap();
    assert!(result.is_empty());
}

#[test]
fn parse_railway_projects_valid_entries() {
    let payload = serde_json::json!([
        {"name": "my-project", "id": "abc123", "workspace": {"name": "team-a"}},
        {"name": "other-project", "id": "def456"},
    ]);
    let result = parse_railway_projects(&payload).unwrap();
    assert_eq!(result.len(), 2);
    assert_eq!(result[0].name, "my-project");
    assert_eq!(result[0].project_id, Some("abc123".to_string()));
    assert_eq!(result[0].workspace_name, Some("team-a".to_string()));
    assert_eq!(result[1].workspace_name, None);
}

#[test]
fn parse_railway_projects_skips_empty_names() {
    let payload = serde_json::json!([
        {"name": "", "id": "1"},
        {"name": "valid", "id": "2"},
    ]);
    let result = parse_railway_projects(&payload).unwrap();
    assert_eq!(result.len(), 1);
    assert_eq!(result[0].name, "valid");
}

#[test]
fn parse_railway_projects_rejects_non_array() {
    let payload = serde_json::json!({"not": "array"});
    assert!(parse_railway_projects(&payload).is_err());
}

#[test]
fn extract_railway_linked_project_name_from_nested_project() {
    let payload = serde_json::json!({"project": {"name": "my-project"}});
    assert_eq!(
        extract_railway_linked_project_name(&payload),
        Some("my-project".to_string())
    );
}

#[test]
fn extract_railway_linked_project_name_from_top_level() {
    let payload = serde_json::json!({
        "name": "top-project",
        "environments": [],
        "services": [],
    });
    assert_eq!(
        extract_railway_linked_project_name(&payload),
        Some("top-project".to_string())
    );
}

#[test]
fn extract_railway_linked_project_name_returns_none() {
    let payload = serde_json::json!({"other": "data"});
    assert_eq!(extract_railway_linked_project_name(&payload), None);
}

#[test]
fn parse_railway_service_statuses_empty() {
    let payload = serde_json::json!({});
    assert!(parse_railway_service_statuses(&payload).is_empty());
}

#[test]
fn parse_railway_service_statuses_valid() {
    let payload = serde_json::json!({
        "environments": {
            "edges": [{
                "node": {
                    "serviceInstances": {
                        "edges": [{
                            "node": {
                                "serviceName": "web",
                                "serviceId": "svc-1",
                                "id": "inst-1",
                                "latestDeployment": {
                                    "id": "dep-1",
                                    "status": "SUCCESS",
                                    "deploymentStopped": false
                                }
                            }
                        }]
                    }
                }
            }]
        }
    });
    let result = parse_railway_service_statuses(&payload);
    assert_eq!(result.len(), 1);
    assert_eq!(result[0].name, "web");
    assert_eq!(result[0].service_id, Some("svc-1".to_string()));
    assert_eq!(result[0].latest_deployment_status, Some("SUCCESS".to_string()));
    assert_eq!(result[0].deployment_stopped, Some(false));
}

// --- Fly proptests ---

proptest! {
    #[test]
    fn fly_certs_add_command_structure(app in safe_name(), hostname in safe_host()) {
        let cmd = fly_certs_add_command(&app, &hostname).unwrap();
        prop_assert!(cmd.contains(&"certs".to_string()));
        prop_assert!(cmd.contains(&"add".to_string()));
        prop_assert!(cmd.contains(&hostname.to_lowercase()));
        prop_assert!(cmd.contains(&"--app".to_string()));
        prop_assert!(cmd.contains(&app));
        prop_assert!(cmd.contains(&"--json".to_string()));
    }

    #[test]
    fn fly_certs_check_command_structure(app in safe_name(), hostname in safe_host()) {
        let cmd = fly_certs_check_command(&app, &hostname).unwrap();
        prop_assert!(cmd.contains(&"certs".to_string()));
        prop_assert!(cmd.contains(&"check".to_string()));
        prop_assert!(cmd.contains(&hostname.to_lowercase()));
        prop_assert!(cmd.contains(&"--app".to_string()));
    }

    #[test]
    fn fly_certs_setup_command_structure(app in safe_name(), hostname in safe_host()) {
        let cmd = fly_certs_setup_command(&app, &hostname).unwrap();
        prop_assert!(cmd.contains(&"certs".to_string()));
        prop_assert!(cmd.contains(&"setup".to_string()));
        prop_assert!(cmd.contains(&hostname.to_lowercase()));
        prop_assert!(cmd.contains(&"--app".to_string()));
    }
}

// --- Backend / project inference proptests ---

proptest! {
    #[test]
    fn backend_display_roundtrip(b in prop_oneof![Just(Backend::Nix), Just(Backend::Guix)]) {
        let s = b.to_string();
        prop_assert!(s == "nix" || s == "guix");
    }

    #[test]
    fn infer_backend_guix_when_guix_manifests(name in safe_token()) {
        let _ = name;
        let markers = ProjectMarkers {
            has_guix_manifest: true,
            ..Default::default()
        };
        let (backend, reasons) = infer_backend(&markers);
        prop_assert_eq!(backend, Backend::Guix);
        prop_assert!(!reasons.is_empty());
    }

    #[test]
    fn infer_backend_guix_when_guix_channels(name in safe_token()) {
        let _ = name;
        let markers = ProjectMarkers {
            has_guix_channels: true,
            ..Default::default()
        };
        let (backend, _) = infer_backend(&markers);
        prop_assert_eq!(backend, Backend::Guix);
    }

    #[test]
    fn infer_backend_nix_default(name in safe_token()) {
        let _ = name;
        let markers = ProjectMarkers::default();
        let (backend, reasons) = infer_backend(&markers);
        prop_assert_eq!(backend, Backend::Nix);
        prop_assert!(!reasons.is_empty());
    }

    #[test]
    fn infer_nix_packages_always_includes_base(name in safe_token()) {
        let _ = name;
        let markers = ProjectMarkers::default();
        let pkgs = infer_nix_packages(&markers);
        prop_assert!(pkgs.contains(&"fish".to_string()));
        prop_assert!(pkgs.contains(&"git".to_string()));
        prop_assert!(pkgs.contains(&"helix".to_string()));
    }

    #[test]
    fn infer_guix_packages_always_includes_base(name in safe_token()) {
        let _ = name;
        let markers = ProjectMarkers::default();
        let pkgs = infer_guix_packages(&markers);
        prop_assert!(pkgs.contains(&"fish".to_string()));
        prop_assert!(pkgs.contains(&"git".to_string()));
        prop_assert!(pkgs.contains(&"helix".to_string()));
        prop_assert!(pkgs.contains(&"zellij".to_string()));
    }

    #[test]
    fn infer_nix_packages_no_duplicates(name in safe_token()) {
        let _ = name;
        let markers = ProjectMarkers {
            has_cargo_toml: true,
            has_pyproject: true,
            has_package_json: true,
            ..Default::default()
        };
        let pkgs = infer_nix_packages(&markers);
        let mut seen = std::collections::HashSet::new();
        for p in &pkgs {
            prop_assert!(seen.insert(p.clone()), "duplicate package: {}", p);
        }
    }

    #[test]
    fn infer_guix_packages_no_duplicates(name in safe_token()) {
        let _ = name;
        let markers = ProjectMarkers {
            has_cargo_toml: true,
            has_pyproject: true,
            has_bun_lock: true,
            ..Default::default()
        };
        let pkgs = infer_guix_packages(&markers);
        let mut seen = std::collections::HashSet::new();
        for p in &pkgs {
            prop_assert!(seen.insert(p.clone()), "duplicate package: {}", p);
        }
    }
}

#[test]
fn infer_backend_standalone_python_is_guix() {
    let markers = ProjectMarkers {
        has_pyproject: true,
        ..Default::default()
    };
    let (backend, _) = infer_backend(&markers);
    assert_eq!(backend, Backend::Guix);
}

#[test]
fn infer_backend_pyproject_with_nix_signals_is_nix() {
    let markers = ProjectMarkers {
        has_pyproject: true,
        has_package_json: true,
        ..Default::default()
    };
    let (backend, _) = infer_backend(&markers);
    assert_eq!(backend, Backend::Nix);
}

#[test]
fn infer_nix_packages_bun_over_nodejs() {
    let markers = ProjectMarkers {
        has_bun_lock: true,
        has_package_json: true,
        ..Default::default()
    };
    let pkgs = infer_nix_packages(&markers);
    assert!(pkgs.contains(&"bun".to_string()));
    assert!(!pkgs.contains(&"nodejs".to_string()));
}

#[test]
fn infer_nix_packages_cargo_adds_rustc() {
    let markers = ProjectMarkers {
        has_cargo_toml: true,
        ..Default::default()
    };
    let pkgs = infer_nix_packages(&markers);
    assert!(pkgs.contains(&"cargo".to_string()));
    assert!(pkgs.contains(&"rustc".to_string()));
}

// --- Dhall rendering proptests ---

proptest! {
    #[test]
    fn render_den_dhall_nix_backend_proptest(name in safe_name()) {
        let config = InferredDenSetup {
            name: name.clone(),
            backend: Backend::Nix,
            dockerfile: None,
            nix_packages: vec!["fish".to_string()],
            guix_packages: vec![],
            environment: vec![("DEN_NAME".to_string(), format!("den-{name}"))],
            reasons: vec!["test reason".to_string()],
        };
        let result = render_den_dhall(&config, std::path::Path::new("/tmp/dhall"));
        prop_assert!(result.contains("Types.Backend.Nix"));
        prop_assert!(result.contains(&name));
        prop_assert!(result.contains("test reason"));
        prop_assert!(result.contains("None Types.GuixConfig"));
    }

    #[test]
    fn render_den_dhall_guix_backend_proptest(name in safe_name()) {
        let config = InferredDenSetup {
            name: name.clone(),
            backend: Backend::Guix,
            dockerfile: Some("Dockerfile".to_string()),
            nix_packages: vec![],
            guix_packages: vec!["python".to_string()],
            environment: vec![],
            reasons: vec![],
        };
        let result = render_den_dhall(&config, std::path::Path::new("/tmp/dhall"));
        prop_assert!(result.contains("Types.Backend.Guix"));
        prop_assert!(result.contains("Some \"Dockerfile\""));
        prop_assert!(result.contains("None Types.NixConfig"));
        prop_assert!(result.contains("python"));
    }

    // --- Sprite parsing proptests ---

    #[test]
    fn parse_sprite_url_info_extracts_valid_url(url in "https://[a-z]{3,8}\\.[a-z]{2,5}/[a-z]{1,10}") {
        let output = format!("URL: {url}\nAuth: google");
        let info = parse_sprite_url_info(&output);
        prop_assert_eq!(info.url, Some(url));
        prop_assert_eq!(info.auth, Some("google".to_string()));
    }

    #[test]
    fn parse_sprite_url_returns_none_for_no_url(line in "[^\\n]{1,40}") {
        let output = format!("SomeOther: {line}");
        prop_assert!(parse_sprite_url(&output).is_none());
    }

    #[test]
    fn find_checkpoint_in_list_output_finds_id(
        id in safe_token(),
        comment in safe_token(),
    ) {
        let line = format!("{id}  2024-01-15  {comment}");
        prop_assert_eq!(
            find_checkpoint_version_in_list_output(&line, &comment),
            Some(id)
        );
    }

    #[test]
    fn find_checkpoint_in_api_output_matches_comment(
        id in safe_token(),
        comment in safe_token(),
    ) {
        let output = serde_json::json!({
            "checkpoints": [{"comment": comment, "id": id}]
        }).to_string();
        prop_assert_eq!(
            find_checkpoint_version_in_api_output(&output, &comment),
            Some(id)
        );
    }

    // --- Tailscale peer extraction proptests ---

    #[test]
    fn extract_den_peers_only_den_prefixed(
        den_name in "[a-z]{1,8}",
        ip in "[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}",
    ) {
        let host = format!("den-{den_name}");
        let payload = serde_json::json!({
            "Peer": {
                "p1": {"HostName": host, "TailscaleIPs": [ip], "Online": true},
                "p2": {"HostName": "laptop", "TailscaleIPs": ["10.0.0.99"], "Online": true},
            }
        });
        let peers = extract_den_peers(&payload);
        prop_assert_eq!(peers.len(), 1);
        prop_assert!(peers[0].host_name.starts_with("den-"));
    }

    // --- RuntimeProvider proptests ---

    #[test]
    fn runtime_provider_display(r in prop_oneof![Just(RuntimeProvider::Sprite), Just(RuntimeProvider::Railway)]) {
        let s = r.to_string();
        prop_assert!(s == "sprite" || s == "railway");
    }
}
