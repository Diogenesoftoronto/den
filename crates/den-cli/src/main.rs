//! den — Remote dev environments (Sprite/Fly + Railway)
//!
//! Rust is the canonical implementation. This binary owns the workflow surface
//! documented in the repository README: setup inference, runtime provisioning,
//! deploy flows, ownership-aware domain attachment, and local Guix image builds.

use anyhow::{anyhow, bail, Context, Result};
use clap::{Parser, Subcommand};
use den_cli::assets::locate_or_materialize_assets;
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Parser)]
#[command(
    name = "den",
    version,
    about = "Remote dev environments (Sprite/Fly + Railway)"
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Inspect whether den is installed correctly and whether optional integrations are available
    Doctor {
        /// Output report as JSON
        #[arg(long)]
        json: bool,
        /// Verify provider authentication/readiness where possible
        #[arg(long)]
        verify_auth: bool,
    },
    /// Infer den.dhall from a repository and generate reproducible artifacts
    Setup {
        /// Repository root (defaults to current directory)
        #[arg(default_value = ".")]
        path: PathBuf,
        /// Overwrite an existing den.dhall
        #[arg(long)]
        force: bool,
        /// Print inferred den.dhall instead of writing files
        #[arg(long)]
        print: bool,
        /// Explicit Dhall template directory
        #[arg(long)]
        dhall_dir: Option<PathBuf>,
    },
    /// Create a new den environment or verify Railway readiness
    Spawn {
        /// Name for the den
        name: String,
        /// Use Guix backend
        #[arg(long)]
        guix: bool,
        /// Backend: nix or guix
        #[arg(long)]
        backend: Option<String>,
        /// Runtime: sprite or railway
        #[arg(long, value_enum, default_value = "sprite")]
        runtime: den_core::RuntimeProvider,
    },
    /// Prepare a repository for deployment and start it on the selected runtime
    Deploy {
        /// Repository path to deploy
        #[arg(default_value = ".")]
        path: PathBuf,
        /// Explicit runtime name or service name
        #[arg(long)]
        name: Option<String>,
        /// Overwrite an existing den.dhall
        #[arg(long)]
        force: bool,
        /// Only prepare the runtime; do not start an inferred command
        #[arg(long)]
        no_run: bool,
        /// Runtime: sprite or railway
        #[arg(long, value_enum, default_value = "sprite")]
        runtime: den_core::RuntimeProvider,
        /// Explicit command override after `--`
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        command: Vec<String>,
    },
    /// Open a console in a den via Sprite
    Connect {
        /// Name of the den
        name: String,
    },
    /// Run a command in a den without opening an interactive console
    Exec {
        /// Name of the den
        name: String,
        /// Command to run
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        command: Vec<String>,
    },
    /// Bind the current directory to a den via sprite use
    SpriteUse {
        /// Name of the den
        name: String,
    },
    /// List dens managed by the selected runtime provider
    List {
        /// Runtime: sprite or railway
        #[arg(long, value_enum, default_value = "sprite")]
        runtime: den_core::RuntimeProvider,
        /// Output as JSON
        #[arg(long)]
        json: bool,
    },
    /// Show status for a den or linked runtime project
    Status {
        /// Name of the den
        name: Option<String>,
        /// Runtime: sprite or railway
        #[arg(long, value_enum, default_value = "sprite")]
        runtime: den_core::RuntimeProvider,
        /// Specific Railway service to inspect
        #[arg(long)]
        service: Option<String>,
    },
    /// Attach a custom domain to a den
    Domain {
        /// Name of the den
        name: String,
        /// Custom domain
        domain: String,
        /// Runtime that serves the hostname
        #[arg(long, value_enum, default_value = "sprite")]
        runtime: den_core::RuntimeProvider,
        /// Domain mode: dns or forward
        #[arg(long, default_value = "dns")]
        mode: String,
        /// Whether Cloudflare should proxy supported DNS records
        #[arg(long, default_value_t = false)]
        proxied: bool,
        /// Port for providers that require it
        #[arg(long)]
        port: Option<u16>,
    },
    /// Toggle the Sprite URL between public and org-authenticated
    Funnel {
        /// Name of the den
        name: String,
        /// Disable public URL and restore org-authenticated mode
        #[arg(long)]
        off: bool,
    },
    /// Destroy a den in the selected runtime provider
    Destroy {
        /// Name of the den
        name: String,
        /// Runtime: sprite or railway
        #[arg(long, value_enum, default_value = "sprite")]
        runtime: den_core::RuntimeProvider,
        /// Skip confirmation prompt
        #[arg(long)]
        yes: bool,
    },
    /// Inspect running Sprite exec sessions or attach to one
    Logs {
        /// Name of the den
        name: String,
        /// Session selector
        selector: Option<String>,
        /// List sessions only
        #[arg(long)]
        list: bool,
    },
    /// Restart a sprite by checkpointing current state and restoring it
    Redeploy {
        /// Name of the den
        name: String,
    },
    /// Build a Guix image locally
    BuildGuix {
        /// Build the full Guix System image
        #[arg(long)]
        system: bool,
        /// Push target image
        #[arg(long)]
        push: Option<String>,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DomainModeArg {
    Dns,
    Forward,
}

#[derive(Debug, Clone)]
struct DoctorCheck {
    name: String,
    ok: bool,
    required: bool,
    detail: String,
}

fn current_context_dir() -> Result<PathBuf> {
    std::env::current_dir().context("failed to resolve current working directory")
}

fn command_path(name: &str) -> Option<PathBuf> {
    which::which(name).ok()
}

fn command_status_ok(program: &str, args: &[&str], cwd: Option<&Path>) -> Result<bool> {
    let mut cmd = Command::new(program);
    cmd.args(args);
    if let Some(dir) = cwd {
        cmd.current_dir(dir);
    }
    let status = cmd
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .with_context(|| format!("failed to execute {program}"))?;
    Ok(status.success())
}

fn doctor_checks(verify_auth: bool) -> Result<Vec<DoctorCheck>> {
    let mut checks = Vec::new();

    let exe = std::env::current_exe().context("failed to resolve current executable")?;
    checks.push(DoctorCheck {
        name: "current executable".to_string(),
        ok: exe.is_file(),
        required: true,
        detail: exe.display().to_string(),
    });

    let den_on_path = command_path("den");
    let path_ok = den_on_path.as_ref().map(|p| p.is_file()).unwrap_or(false);
    let path_detail = match den_on_path {
        Some(path) => path.display().to_string(),
        None => "not found on PATH".to_string(),
    };
    checks.push(DoctorCheck {
        name: "`den` on PATH".to_string(),
        ok: path_ok,
        required: true,
        detail: path_detail,
    });

    let assets = locate_or_materialize_assets()?;
    checks.push(DoctorCheck {
        name: "asset root".to_string(),
        ok: assets.root.is_dir(),
        required: true,
        detail: assets.root.display().to_string(),
    });
    checks.push(DoctorCheck {
        name: "dhall templates".to_string(),
        ok: assets.dhall_dir.join("Types.dhall").is_file(),
        required: true,
        detail: assets.dhall_dir.display().to_string(),
    });
    checks.push(DoctorCheck {
        name: "generator script".to_string(),
        ok: assets.scripts_dir.join("generate-from-dhall.sh").is_file(),
        required: true,
        detail: assets
            .scripts_dir
            .join("generate-from-dhall.sh")
            .display()
            .to_string(),
    });
    checks.push(DoctorCheck {
        name: "guix templates".to_string(),
        ok: assets.guix_dir.join("manifest.scm").is_file(),
        required: true,
        detail: assets.guix_dir.display().to_string(),
    });

    for tool in ["bash", "tar"] {
        let found = command_path(tool);
        checks.push(DoctorCheck {
            name: format!("required tool `{tool}`"),
            ok: found.is_some(),
            required: true,
            detail: found
                .map(|p| p.display().to_string())
                .unwrap_or_else(|| "not found".to_string()),
        });
    }

    for tool in [
        "sprite", "railway", "sesame", "dhall", "guix", "uv", "python3",
    ] {
        let found = command_path(tool);
        checks.push(DoctorCheck {
            name: format!("optional tool `{tool}`"),
            ok: found.is_some(),
            required: false,
            detail: found
                .map(|p| p.display().to_string())
                .unwrap_or_else(|| "not found".to_string()),
        });
    }

    if verify_auth {
        let cwd = current_context_dir()?;

        let sprite_auth = if command_path("sprite").is_some() {
            command_status_ok("sprite", &["list"], None)?
        } else {
            false
        };
        checks.push(DoctorCheck {
            name: "sprite authentication".to_string(),
            ok: sprite_auth,
            required: false,
            detail: if command_path("sprite").is_some() {
                if sprite_auth {
                    "sprite list succeeded".to_string()
                } else {
                    "sprite list failed".to_string()
                }
            } else {
                "sprite not installed".to_string()
            },
        });

        let railway_auth = if command_path("railway").is_some() {
            command_status_ok("railway", &["status", "--json"], Some(&cwd))?
        } else {
            false
        };
        checks.push(DoctorCheck {
            name: "railway readiness".to_string(),
            ok: railway_auth,
            required: false,
            detail: if command_path("railway").is_some() {
                if railway_auth {
                    format!("railway status --json succeeded in {}", cwd.display())
                } else {
                    format!("railway status --json failed in {}", cwd.display())
                }
            } else {
                "railway not installed".to_string()
            },
        });
    } else {
        checks.push(DoctorCheck {
            name: "provider authentication".to_string(),
            ok: true,
            required: false,
            detail: "skipped; rerun with --verify-auth".to_string(),
        });
    }

    Ok(checks)
}

fn run_doctor(json: bool, verify_auth: bool) -> Result<()> {
    let checks = doctor_checks(verify_auth)?;
    let required_ok = checks.iter().filter(|c| c.required).all(|c| c.ok);
    let optional_ok = checks
        .iter()
        .filter(|c| !c.required)
        .filter(|c| c.ok)
        .count();
    let optional_total = checks.iter().filter(|c| !c.required).count();

    if json {
        let payload = serde_json::json!({
            "ok": required_ok,
            "optional_ok": optional_ok,
            "optional_total": optional_total,
            "checks": checks.iter().map(|c| serde_json::json!({
                "name": c.name,
                "ok": c.ok,
                "required": c.required,
                "detail": c.detail,
            })).collect::<Vec<_>>()
        });
        println!("{}", serde_json::to_string_pretty(&payload)?);
    } else {
        println!("den doctor");
        println!();
        for check in &checks {
            let marker = if check.ok { "OK" } else { "FAIL" };
            let scope = if check.required {
                "required"
            } else {
                "optional"
            };
            println!("{marker:<4} [{scope}] {}: {}", check.name, check.detail);
        }
        println!();
        println!(
            "summary: required={} optional={}/{}",
            if required_ok { "healthy" } else { "broken" },
            optional_ok,
            optional_total
        );
    }

    if !required_ok {
        bail!("den is not installed properly; required checks failed");
    }
    Ok(())
}

fn parse_backend(guix: bool, backend: Option<&str>) -> Result<den_core::Backend> {
    if guix {
        return Ok(den_core::Backend::Guix);
    }
    match backend.unwrap_or("nix") {
        "nix" => Ok(den_core::Backend::Nix),
        "guix" => Ok(den_core::Backend::Guix),
        other => bail!("unsupported backend: {other}"),
    }
}

fn parse_domain_mode(mode: &str) -> Result<DomainModeArg> {
    match mode {
        "dns" => Ok(DomainModeArg::Dns),
        "forward" => Ok(DomainModeArg::Forward),
        other => bail!("unsupported domain mode: {other}"),
    }
}

fn run_cmd(cmd: &[String]) -> Result<()> {
    let (program, args) = cmd.split_first().context("empty command")?;
    let status = Command::new(program)
        .args(args)
        .status()
        .with_context(|| format!("failed to execute {program}"))?;
    if !status.success() {
        bail!("command exited with {}", status);
    }
    Ok(())
}

fn run_cmd_in(cmd: &[String], cwd: &Path) -> Result<()> {
    let (program, args) = cmd.split_first().context("empty command")?;
    let status = Command::new(program)
        .args(args)
        .current_dir(cwd)
        .status()
        .with_context(|| format!("failed to execute {program}"))?;
    if !status.success() {
        bail!("command exited with {}", status);
    }
    Ok(())
}

fn capture_cmd(cmd: &[String]) -> Result<String> {
    let (program, args) = cmd.split_first().context("empty command")?;
    let output = Command::new(program)
        .args(args)
        .output()
        .with_context(|| format!("failed to execute {program}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("command failed: {stderr}");
    }
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

fn capture_cmd_in(cmd: &[String], cwd: &Path) -> Result<String> {
    let (program, args) = cmd.split_first().context("empty command")?;
    let output = Command::new(program)
        .args(args)
        .current_dir(cwd)
        .output()
        .with_context(|| format!("failed to execute {program}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("command failed: {stderr}");
    }
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

fn run_cmd_with_input_bytes(cmd: &[String], input: &[u8]) -> Result<()> {
    let (program, args) = cmd.split_first().context("empty command")?;
    let mut child = Command::new(program)
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .spawn()
        .with_context(|| format!("failed to execute {program}"))?;
    if let Some(stdin) = child.stdin.as_mut() {
        stdin.write_all(input)?;
    }
    let status = child.wait()?;
    if !status.success() {
        bail!("command exited with {}", status);
    }
    Ok(())
}

fn command_exists(name: &str) -> bool {
    Command::new("bash")
        .args(["-lc", &format!("command -v {name}")])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn now_nonce() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos().to_string())
        .unwrap_or_else(|_| "0".to_string())
}

fn ensure_railway_ready() -> Result<()> {
    let cmd = den_core::railway_status_command()?;
    let _ = capture_cmd_in(&cmd, &current_context_dir()?).context(
        "Railway status failed. Login or link this directory to a Railway project first.",
    )?;
    Ok(())
}

fn railway_up_command(path: &Path, detach: bool) -> Result<Vec<String>> {
    let mut cmd = den_core::resolve_railway_command()?;
    cmd.push("up".to_string());
    cmd.push(path.to_string_lossy().to_string());
    if detach {
        cmd.push("--detach".to_string());
    }
    Ok(cmd)
}

fn railway_projects() -> Result<Vec<den_core::RailwayProjectSummary>> {
    let payload = capture_cmd(&den_core::railway_list_command()?)?;
    let json: Value =
        serde_json::from_str(&payload).context("could not parse Railway project list")?;
    den_core::parse_railway_projects(&json).map_err(|e| anyhow!(e))
}

fn railway_status_payload() -> Result<Value> {
    let output = capture_cmd_in(
        &den_core::railway_status_command()?,
        &current_context_dir()?,
    )?;
    serde_json::from_str(&output).context("Railway returned malformed JSON for status")
}

fn linked_railway_project_name() -> Result<Option<String>> {
    Ok(den_core::extract_railway_linked_project_name(
        &railway_status_payload()?,
    ))
}

fn list_sprite_dens() -> Result<Vec<String>> {
    let output = capture_cmd(&den_core::sprite_command(
        &["list", "-prefix", "den-"],
        None,
    ))?;
    Ok(output
        .lines()
        .map(str::trim)
        .filter(|line| line.starts_with("den-"))
        .map(|line| line.to_string())
        .collect())
}

fn sprite_exists(name: &str) -> Result<bool> {
    let den_name = den_core::normalize_den_name(name);
    Ok(list_sprite_dens()?.iter().any(|n| n == &den_name))
}

fn create_sprite(name: &str) -> Result<()> {
    let cmd = den_core::sprite_command(&["create", "--skip-console"], Some(name));
    run_cmd_in(&cmd, &current_context_dir()?)
}

fn sync_repo_to_sprite(name: &str, repo_dir: &Path) -> Result<String> {
    let den_name = den_core::normalize_den_name(name);
    let nonce = now_nonce();
    let remote_dir = format!(
        "/home/sprite/{}-{nonce}",
        repo_dir
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("repo")
    );
    let archive_path = std::env::temp_dir().join(format!("den-sync-{nonce}.tar"));

    let repo_name = repo_dir
        .file_name()
        .and_then(|n| n.to_str())
        .context("repository path must have a terminal directory name")?;
    let parent = repo_dir
        .parent()
        .context("repository path must have a parent directory")?;

    let tar_status = Command::new("tar")
        .args([
            "-cf",
            archive_path.to_string_lossy().as_ref(),
            "--exclude=.git",
            "--exclude=.jj",
            "--exclude=.direnv",
            "--exclude=.venv",
            "--exclude=node_modules",
            "--exclude=target",
            "--exclude=__pycache__",
            "--exclude=*.pyc",
            "--exclude=*.pyo",
            "-C",
            parent.to_string_lossy().as_ref(),
            repo_name,
        ])
        .status()
        .context("failed to build repository tarball")?;
    if !tar_status.success() {
        bail!("failed to build repository tarball");
    }

    let archive_bytes = fs::read(&archive_path).context("failed to read repository tarball")?;
    let _ = fs::remove_file(&archive_path);

    let remote_archive = format!("/home/sprite/{}-{nonce}.tar", repo_name);
    let unpack_command = format!(
        "mkdir -p {remote_dir} && cat > {remote_archive} && tar -xf {remote_archive} -C {remote_dir} --strip-components=1 && rm -f {remote_archive}",
    );
    let cmd = den_core::sprite_command(
        &["exec", "--", "sh", "-lc", &unpack_command],
        Some(&den_name),
    );
    run_cmd_with_input_bytes(&cmd, &archive_bytes)?;
    Ok(remote_dir)
}

async fn sesame_owned_domains() -> Result<Vec<String>> {
    if let Ok(mut sesame_cmd) = den_core::resolve_sesame_command() {
        sesame_cmd.extend([
            "domain".to_string(),
            "list".to_string(),
            "--all".to_string(),
            "--json".to_string(),
        ]);
        if let Ok(output) = capture_cmd(&sesame_cmd) {
            if let Ok(payload) = serde_json::from_str::<Value>(&output) {
                if let Some(arr) = payload.as_array() {
                    let domains: Vec<String> = arr
                        .iter()
                        .filter_map(|row| row.get("domain").and_then(|v| v.as_str()))
                        .filter(|s| !s.is_empty())
                        .map(|s| s.to_string())
                        .collect();
                    if !domains.is_empty() {
                        return Ok(domains);
                    }
                }
            }
        }
    }

    let client = reqwest::Client::builder()
        .use_rustls_tls()
        .build()
        .context("failed to build HTTP client")?;
    Ok(
        den_core::porkbun::discover_porkbun_domains_from_sesame_config(&client, None)
            .await
            .unwrap_or_default(),
    )
}

async fn configured_domain_zones() -> Result<HashMap<den_core::DomainProvider, Vec<String>>> {
    let mut zones = HashMap::new();
    let cloudflare_domains = if let Some(token) = den_core::cloudflare_api_token() {
        let client = den_core::CloudflareClient::new(token);
        client.discover_domains().await
    } else {
        vec![]
    };
    zones.insert(den_core::DomainProvider::Cloudflare, cloudflare_domains);
    zones.insert(
        den_core::DomainProvider::Sesame,
        sesame_owned_domains().await?,
    );
    Ok(zones)
}

fn sprite_url(name: &str) -> Result<String> {
    let output = capture_cmd(&den_core::sprite_command(&["url"], Some(name)))?;
    den_core::parse_sprite_url(&output).context("could not parse sprite URL")
}

async fn attach_cloudflare_dns_to_sprite(
    den_name: &str,
    host: &str,
    zone: &str,
    proxied: bool,
) -> Result<()> {
    let output = capture_cmd(&den_core::fly_certs_add_command(den_name, host)?)?;
    let payload: Value = serde_json::from_str(&output)
        .context("Fly returned malformed JSON while attaching the hostname")?;
    let records = den_core::parse_fly_dns_records(host, zone, &payload, proxied)?;
    let token = den_core::cloudflare_api_token().context("Cloudflare API token not configured")?;
    let client = den_core::CloudflareClient::new(token);
    let applied = client.upsert_dns_records(zone, &records).await?;
    for entry in &applied {
        println!("  Cloudflare DNS: {} {}", entry.action, entry.record);
    }
    Ok(())
}

async fn attach_cloudflare_dns_to_railway(
    service: &str,
    host: &str,
    zone: &str,
    proxied: bool,
    port: Option<u16>,
) -> Result<()> {
    let output = capture_cmd_in(
        &den_core::railway_domain_attach_command(service, host, port)?,
        &current_context_dir()?,
    )?;
    let payload: Value = serde_json::from_str(&output)
        .context("Railway returned malformed JSON while attaching the hostname")?;
    let records = den_core::parse_railway_dns_records(host, zone, &payload, proxied)?;
    let token = den_core::cloudflare_api_token().context("Cloudflare API token not configured")?;
    let client = den_core::CloudflareClient::new(token);
    let applied = client.upsert_dns_records(zone, &records).await?;
    for entry in &applied {
        println!("  Cloudflare DNS: {} {}", entry.action, entry.record);
    }
    Ok(())
}

async fn upsert_sesame_dns_records(zone: &str, records: &[den_core::DnsRecord]) -> Result<()> {
    if let Ok(sesame_cmd) = den_core::resolve_sesame_command() {
        for record in records {
            let lookup_cmd = {
                let mut cmd = sesame_cmd.clone();
                cmd.extend(den_core::build_sesame_dns_list_command(zone, record));
                cmd
            };
            let lookup_output = capture_cmd(&lookup_cmd)?;
            let lookup_payload: Value = serde_json::from_str(&lookup_output)
                .context("sesame returned malformed JSON while listing DNS records")?;
            let mut write_cmd = sesame_cmd.clone();
            let action = if den_core::sesame_dns_records_exist(&lookup_payload) {
                write_cmd.extend(den_core::build_sesame_dns_edit_command(zone, record));
                "updated"
            } else {
                write_cmd.extend(den_core::build_sesame_dns_create_command(zone, record));
                "created"
            };
            run_cmd(&write_cmd)?;
            let fqdn = if record.name == "@" || record.name.is_empty() {
                zone.to_string()
            } else {
                format!("{}.{}", record.name, zone)
            };
            println!(
                "  Porkbun DNS: {action} {} {fqdn} -> {}",
                record.record_type, record.content
            );
        }
        return Ok(());
    }

    let client = reqwest::Client::builder()
        .use_rustls_tls()
        .build()
        .context("failed to build HTTP client")?;
    let applied =
        den_core::porkbun::porkbun_upsert_dns_records(&client, zone, records, None).await?;
    for (action, record) in &applied {
        let fqdn = if record.name == "@" || record.name.is_empty() {
            zone.to_string()
        } else {
            format!("{}.{}", record.name, zone)
        };
        println!(
            "  Porkbun DNS: {action} {} {fqdn} -> {}",
            record.record_type, record.content
        );
    }
    Ok(())
}

async fn attach_sesame_dns_to_railway(
    service: &str,
    host: &str,
    zone: &str,
    port: Option<u16>,
) -> Result<()> {
    let output = capture_cmd_in(
        &den_core::railway_domain_attach_command(service, host, port)?,
        &current_context_dir()?,
    )?;
    let payload: Value = serde_json::from_str(&output)
        .context("Railway returned malformed JSON while attaching the hostname")?;
    let records = den_core::parse_railway_dns_records(host, zone, &payload, false)?;
    upsert_sesame_dns_records(zone, &records).await
}

async fn attach_sesame_dns_to_sprite(den_name: &str, host: &str, zone: &str) -> Result<String> {
    let target_url = sprite_url(den_name)?;
    let content = target_url.replace("https://", "").replace("http://", "");
    let subdomain = if host.eq_ignore_ascii_case(zone) {
        "@".to_string()
    } else {
        host.trim_end_matches(&format!(".{zone}"))
            .trim_end_matches('.')
            .to_string()
    };
    let record = den_core::DnsRecord {
        name: if subdomain.is_empty() {
            "@".to_string()
        } else {
            subdomain
        },
        record_type: "CNAME".to_string(),
        content,
        proxied: false,
    };
    upsert_sesame_dns_records(zone, &[record]).await?;
    Ok(target_url)
}

async fn attach_custom_domain(
    name: &str,
    host: &str,
    runtime: den_core::RuntimeProvider,
    mode: DomainModeArg,
    proxied: bool,
    port: Option<u16>,
) -> Result<String> {
    let provider_domains = configured_domain_zones().await?;
    let domain_match = den_core::resolve_custom_domain(host, &provider_domains)?;
    let target_url = if runtime == den_core::RuntimeProvider::Sprite {
        sprite_url(name)?
    } else {
        format!("railway://{}", den_core::normalize_den_name(name))
    };

    match mode {
        DomainModeArg::Dns => match domain_match.provider {
            den_core::DomainProvider::Cloudflare => {
                if runtime == den_core::RuntimeProvider::Sprite {
                    attach_cloudflare_dns_to_sprite(name, host, &domain_match.zone, proxied)
                        .await?;
                } else {
                    attach_cloudflare_dns_to_railway(name, host, &domain_match.zone, proxied, port)
                        .await?;
                }
                Ok(target_url)
            }
            den_core::DomainProvider::Sesame => {
                if runtime == den_core::RuntimeProvider::Sprite {
                    attach_sesame_dns_to_sprite(name, host, &domain_match.zone).await
                } else {
                    attach_sesame_dns_to_railway(name, host, &domain_match.zone, port).await?;
                    Ok(target_url)
                }
            }
        },
        DomainModeArg::Forward => {
            if runtime != den_core::RuntimeProvider::Sprite {
                bail!("forward mode is currently implemented for Sprite-backed runtimes only");
            }
            if domain_match.provider != den_core::DomainProvider::Sesame {
                bail!("{host} is held by {}. Forward mode is currently implemented for sesame/Porkbun-hosted zones.", domain_match.provider);
            }
            run_cmd(&den_core::sprite_command(
                &["url", "update", "--auth", "public"],
                Some(name),
            ))
            .context("failed to make the Sprite URL public")?;
            let owned_domains = provider_domains
                .get(&den_core::DomainProvider::Sesame)
                .cloned()
                .unwrap_or_default();
            if let Ok(mut sesame_cmd) = den_core::resolve_sesame_command() {
                sesame_cmd.extend(den_core::build_sesame_url_forward_command(
                    host,
                    &target_url,
                    &owned_domains,
                )?);
                run_cmd(&sesame_cmd)?;
            } else {
                let client = reqwest::Client::builder()
                    .use_rustls_tls()
                    .build()
                    .context("failed to build HTTP client")?;
                den_core::porkbun::porkbun_add_url_forward(
                    &client,
                    host,
                    &target_url,
                    &owned_domains,
                    None,
                )
                .await?;
            }
            Ok(target_url)
        }
    }
}

fn run_setup(
    path: &Path,
    force: bool,
    print_only: bool,
    explicit_dhall_dir: Option<&Path>,
) -> Result<()> {
    let repo_dir = path.resolve_path()?;
    if !repo_dir.is_dir() {
        bail!("repository path not found: {}", repo_dir.display());
    }
    let bundled_assets = locate_or_materialize_assets()?;
    let dhall_dir = explicit_dhall_dir
        .map(PathBuf::from)
        .unwrap_or(bundled_assets.dhall_dir);
    if !dhall_dir.is_dir() {
        bail!("Dhall templates not found at {}", dhall_dir.display());
    }

    let inferred = den_core::infer_den_setup(&repo_dir);
    let markers = den_core::detect_project_markers(&repo_dir);
    let rendered = den_core::render_den_dhall(&inferred, &dhall_dir);

    println!("==> den setup {}", repo_dir.display());
    println!("  Name:       {}", inferred.name);
    println!("  Backend:    {}", inferred.backend);
    println!(
        "  Dockerfile: {}",
        inferred.dockerfile.as_deref().unwrap_or("default")
    );
    println!("  Signals:");
    if inferred.reasons.is_empty() {
        println!("    - no strong signals detected");
    } else {
        for reason in &inferred.reasons {
            println!("    - {reason}");
        }
    }

    let detected_markers = [
        ("package.json", markers.has_package_json),
        ("bun.lock", markers.has_bun_lock),
        ("pyproject.toml", markers.has_pyproject),
        ("Cargo.toml", markers.has_cargo_toml),
        (
            "Dockerfile/Containerfile",
            markers.has_dockerfile || markers.has_containerfile,
        ),
        ("mise.toml", markers.has_mise_toml),
        ("flox.toml", markers.has_flox_toml),
        ("Helm chart", markers.has_helm_chart),
        (
            "Guix manifest",
            markers.has_guix_manifest || markers.has_guix_channels,
        ),
        (
            "Nix metadata",
            markers.has_nix_flake || markers.has_shell_nix,
        ),
    ];
    for (label, present) in detected_markers {
        if present {
            println!("    - detected {label}");
        }
    }

    if print_only {
        println!();
        println!("{rendered}");
        return Ok(());
    }

    let den_file = repo_dir.join("den.dhall");
    if den_file.exists() && !force {
        bail!(
            "{} already exists. Re-run with --force to overwrite it.",
            den_file.display()
        );
    }
    fs::write(&den_file, rendered)
        .with_context(|| format!("failed to write {}", den_file.display()))?;
    println!("OK Wrote {}", den_file.display());

    if command_exists("sprite") {
        println!("OK Sprite CLI available");
    } else {
        println!("NOTE Sprite CLI not found; setup still generated Dhall config.");
    }

    if den_core::resolve_sesame_command().is_ok() {
        println!("OK sesame available");
    } else {
        println!("NOTE sesame not found; continuing without domain automation checks.");
    }

    let script = bundled_assets.scripts_dir.join("generate-from-dhall.sh");
    run_cmd(&[
        "bash".to_string(),
        script.to_string_lossy().to_string(),
        den_file.to_string_lossy().to_string(),
        repo_dir.to_string_lossy().to_string(),
    ])
    .context("Dhall generation failed")?;
    println!("OK Generated reproducible artifacts from den.dhall");
    Ok(())
}

trait ResolvePath {
    fn resolve_path(&self) -> Result<PathBuf>;
}

impl ResolvePath for Path {
    fn resolve_path(&self) -> Result<PathBuf> {
        if self.is_absolute() {
            Ok(self.to_path_buf())
        } else {
            Ok(std::env::current_dir()?.join(self))
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("warn")),
        )
        .init();

    let cli = Cli::try_parse();
    let cli = match cli {
        Ok(c) => c,
        Err(e) => {
            e.print()?;
            std::process::exit(if e.use_stderr() { 1 } else { 0 });
        }
    };

    match cli.command {
        Commands::Doctor { json, verify_auth } => {
            run_doctor(json, verify_auth)?;
        }
        Commands::Setup {
            path,
            force,
            print,
            dhall_dir,
        } => {
            run_setup(&path, force, print, dhall_dir.as_deref())?;
        }
        Commands::Spawn {
            name,
            guix,
            backend,
            runtime,
        } => {
            let den_name = den_core::normalize_den_name(&name);
            let backend = parse_backend(guix, backend.as_deref())?;
            println!("==> Spawning {den_name} ({backend}, runtime={runtime})");
            if runtime == den_core::RuntimeProvider::Sprite {
                create_sprite(&den_name)?;
                let short_name = den_core::short_den_name(&den_name);
                println!("OK {den_name} created in Sprite");
                println!("  Backend selection is recorded locally; Sprite owns the runtime image.");
                println!("  Connect:    den connect {short_name}");
                println!("  Status:     den status {short_name}");
                println!("  Domain:     den domain {short_name} dev.example.com");
            } else {
                ensure_railway_ready()?;
                let short_name = den_core::short_den_name(&den_name);
                println!("OK Railway project/service is reachable for deployment");
                println!("  Spawn on Railway is a readiness check rather than a separate environment creation step.");
                println!("  Deploy:     den deploy . --name {short_name} --runtime railway");
                println!("  Domain:     den domain {short_name} dev.example.com --runtime railway");
            }
        }
        Commands::Deploy {
            path,
            name,
            force,
            no_run,
            runtime,
            command,
        } => {
            let repo_dir = path.resolve_path()?;
            if !repo_dir.is_dir() {
                bail!("repository path not found: {}", repo_dir.display());
            }
            let den_file = repo_dir.join("den.dhall");
            println!("==> den deploy {} (runtime={runtime})", repo_dir.display());
            if den_file.exists() && !force {
                println!("  Reusing existing config: {}", den_file.display());
            } else {
                run_setup(&repo_dir, force, false, None)?;
            }

            let inferred = den_core::infer_den_setup(&repo_dir);
            let den_name = den_core::normalize_den_name(name.as_deref().unwrap_or(&inferred.name));

            if runtime == den_core::RuntimeProvider::Sprite {
                if sprite_exists(&den_name)? {
                    println!("  Reusing existing sprite: {den_name}");
                } else {
                    println!("  Creating sprite:        {den_name}");
                    create_sprite(&den_name)?;
                }

                println!("  Binding repository:     {}", repo_dir.display());
                run_cmd_in(&den_core::sprite_use_command(&den_name), &repo_dir)
                    .context("Sprite use failed")?;
                let remote_dir = sync_repo_to_sprite(&den_name, &repo_dir)
                    .context("Sprite source sync failed")?;

                if no_run {
                    println!("OK {den_name} prepared for deployment");
                    println!("  Remote dir:      {remote_dir}");
                    println!(
                        "  Start manually: den exec {} -- <cmd...>",
                        den_core::short_den_name(&den_name)
                    );
                    println!(
                        "  Console:        den connect {}",
                        den_core::short_den_name(&den_name)
                    );
                    return Ok(());
                }

                let (run_command, run_reasons) = if !command.is_empty() {
                    (
                        command,
                        vec!["explicit deploy command provided".to_string()],
                    )
                } else if let Some(inferred_run) = den_core::infer_run_command(&repo_dir) {
                    (inferred_run.command, inferred_run.reasons)
                } else {
                    println!("OK {den_name} prepared, but no start command was inferred");
                    println!("  Remote dir:      {remote_dir}");
                    println!("  den deploy prefers deterministic generation over guessing.");
                    println!(
                        "  Run manually: den exec {} -- <cmd...>",
                        den_core::short_den_name(&den_name)
                    );
                    println!(
                        "  Console:      den connect {}",
                        den_core::short_den_name(&den_name)
                    );
                    return Ok(());
                };

                println!("  Starting:               {}", run_command.join(" "));
                for reason in &run_reasons {
                    println!("    - {reason}");
                }
                let mut cmd =
                    den_core::sprite_command(&["exec", "--tty", "--dir"], Some(&den_name));
                cmd.push(remote_dir);
                cmd.push("--".to_string());
                cmd.extend(run_command);
                run_cmd(&cmd).context("Sprite exec failed")?;
                println!("OK {den_name} deployed and running on Sprite");
            } else {
                ensure_railway_ready()?;
                if no_run {
                    println!("OK Railway runtime verified and repo prepared locally");
                    println!("  Run deploy manually: den deploy . --runtime railway");
                    return Ok(());
                }
                println!("  Deploying to Railway:  {}", repo_dir.display());
                run_cmd_in(&railway_up_command(&repo_dir, true)?, &repo_dir)
                    .context("Railway deploy failed")?;
                println!("OK {den_name} deployed to Railway");
            }
        }
        Commands::Connect { name } => {
            run_cmd(&den_core::sprite_command(&["console"], Some(&name)))?;
        }
        Commands::Exec { name, command } => {
            if command.is_empty() {
                bail!("provide a command to run inside the den");
            }
            run_cmd(&den_core::sprite_exec_command(&name, &command))?;
        }
        Commands::SpriteUse { name } => {
            run_cmd(&den_core::sprite_use_command(&name))?;
        }
        Commands::List { runtime, json } => match runtime {
            den_core::RuntimeProvider::Sprite => {
                let entries = list_sprite_dens()?;
                if json {
                    println!("{}", serde_json::to_string_pretty(&entries)?);
                } else {
                    for entry in &entries {
                        println!("{entry}");
                    }
                }
            }
            den_core::RuntimeProvider::Railway => {
                let projects: Vec<_> = railway_projects()?
                    .into_iter()
                    .filter(|p| p.name.starts_with("den-"))
                    .collect();
                if json {
                    println!("{}", serde_json::to_string_pretty(&projects.iter().map(|p| serde_json::json!({"name": p.name, "project_id": p.project_id, "workspace": p.workspace_name})).collect::<Vec<_>>())?);
                } else {
                    for project in &projects {
                        println!(
                            "{:<30} {:<15} {}",
                            project.name,
                            project.project_id.as_deref().unwrap_or("-"),
                            project.workspace_name.as_deref().unwrap_or("-")
                        );
                    }
                }
            }
        },
        Commands::Status {
            name,
            runtime,
            service,
        } => match runtime {
            den_core::RuntimeProvider::Sprite => {
                let den_name = name.context("status requires a den name for sprite runtime")?;
                let output = capture_cmd(&den_core::sprite_command(&["url"], Some(&den_name)))?;
                let info = den_core::parse_sprite_url_info(&output);
                if let Some(url) = info.url {
                    println!("URL: {url}");
                }
                if let Some(auth) = info.auth {
                    println!("Auth: {auth}");
                }
            }
            den_core::RuntimeProvider::Railway => {
                let payload = railway_status_payload()?;
                if let Some(project_name) = den_core::extract_railway_linked_project_name(&payload)
                {
                    println!("Project: {project_name}");
                }
                let services = den_core::parse_railway_service_statuses(&payload);
                if let Some(service_name) = service {
                    let svc = services
                        .iter()
                        .find(|entry| entry.name == service_name)
                        .with_context(|| format!("Railway service {service_name:?} not found"))?;
                    println!("Name: {}", svc.name);
                    println!(
                        "Service ID: {}",
                        svc.service_id.as_deref().unwrap_or("unknown")
                    );
                    println!(
                        "Instance ID: {}",
                        svc.instance_id.as_deref().unwrap_or("unknown")
                    );
                    println!(
                        "Deployment ID: {}",
                        svc.latest_deployment_id.as_deref().unwrap_or("unknown")
                    );
                    println!(
                        "Deployment: {}",
                        svc.latest_deployment_status.as_deref().unwrap_or("unknown")
                    );
                    println!(
                        "Stopped: {}",
                        svc.deployment_stopped
                            .map(|v| v.to_string())
                            .unwrap_or_else(|| "unknown".to_string())
                    );
                } else {
                    for svc in &services {
                        let status = svc.latest_deployment_status.as_deref().unwrap_or("UNKNOWN");
                        let stopped = svc.deployment_stopped.unwrap_or(false);
                        let marker = if stopped { " STOPPED" } else { "" };
                        println!("  {:<20} {:<12}{marker}", svc.name, status);
                    }
                }
            }
        },
        Commands::Domain {
            name,
            domain,
            runtime,
            mode,
            proxied,
            port,
        } => {
            let den_name = den_core::normalize_den_name(&name);
            let mode = parse_domain_mode(&mode)?;
            println!(
                "==> Attaching domain {domain} to {den_name} using runtime={runtime} mode={}",
                match mode {
                    DomainModeArg::Dns => "dns",
                    DomainModeArg::Forward => "forward",
                }
            );
            let target_url =
                attach_custom_domain(&den_name, &domain, runtime, mode, proxied, port).await?;
            match mode {
                DomainModeArg::Forward => {
                    println!("OK Domain {domain} now forwards to {target_url}")
                }
                DomainModeArg::Dns => println!("OK Domain {domain} is attached to {target_url}"),
            }
        }
        Commands::Funnel { name, off } => {
            let auth = if off { "sprite" } else { "public" };
            run_cmd(&den_core::sprite_command(
                &["url", "update", "--auth", auth],
                Some(&name),
            ))?;
        }
        Commands::Destroy { name, runtime, yes } => {
            let den_name = den_core::normalize_den_name(&name);
            if !yes {
                bail!("destroy requires --yes");
            }
            match runtime {
                den_core::RuntimeProvider::Sprite => {
                    run_cmd_in(
                        &den_core::sprite_command(&["destroy", "-force"], Some(&den_name)),
                        &current_context_dir()?,
                    )?;
                }
                den_core::RuntimeProvider::Railway => {
                    let linked = linked_railway_project_name()?;
                    if linked.as_deref() != Some(&den_name) {
                        bail!(
                            "refusing Railway project deletion because the linked project is {}, not {}",
                            linked.unwrap_or_else(|| "unknown".to_string()),
                            den_name
                        );
                    }
                    run_cmd_in(
                        &den_core::railway_delete_command(&den_name, true, true)?,
                        &current_context_dir()?,
                    )?;
                }
            }
        }
        Commands::Logs {
            name,
            selector,
            list,
        } => {
            run_cmd(&den_core::sprite_logs_command(
                &name,
                selector.as_deref(),
                list,
            ))?;
        }
        Commands::Redeploy { name } => {
            let den_name = den_core::normalize_den_name(&name);
            let comment = den_core::make_sprite_redeploy_comment(&den_name, &now_nonce());
            run_cmd(&den_core::sprite_checkpoint_create_command(
                &den_name, &comment,
            ))?;

            let api_cmd = den_core::sprite_command(&["api", "/checkpoints"], Some(&den_name));
            let checkpoint_id = capture_cmd(&api_cmd)
                .ok()
                .and_then(|output| {
                    den_core::find_checkpoint_version_in_api_output(&output, &comment)
                })
                .or_else(|| {
                    capture_cmd(&den_core::sprite_command(
                        &["checkpoint", "list"],
                        Some(&den_name),
                    ))
                    .ok()
                    .and_then(|output| {
                        den_core::find_checkpoint_version_in_list_output(&output, &comment)
                    })
                })
                .context("checkpoint created, but could not determine the new checkpoint ID")?;

            run_cmd(&den_core::sprite_restore_command(&den_name, &checkpoint_id))?;
            println!("Redeployed {den_name} (checkpoint {checkpoint_id})");
        }
        Commands::BuildGuix { system, push } => {
            let script = locate_or_materialize_assets()?
                .scripts_dir
                .join("build-guix-image.sh");
            let mut cmd = vec!["bash".to_string(), script.to_string_lossy().to_string()];
            if system {
                cmd.push("--system".to_string());
            }
            if let Some(target) = push {
                cmd.push("--push".to_string());
                cmd.push(target);
            }
            run_cmd(&cmd)?;
        }
    }

    Ok(())
}
