use rust_mcp_sdk::macros::{self, JsonSchema};
use rust_mcp_sdk::schema::schema_utils::CallToolError;
use rust_mcp_sdk::schema::{CallToolResult, TextContent};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};
use tokio::io::AsyncWriteExt;

pub fn project_dir() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| "/root".into()))
        .join("Projects")
        .join("den")
}

#[macros::mcp_tool(
    name = "provision_den",
    description = "Provision workflow: prerequisites + spawn + optional domain in one call."
)]
#[derive(Debug, Deserialize, Serialize, JsonSchema)]
pub struct ProvisionDenTool {
    /// Name for the den
    pub name: String,
    /// Backend: nix or guix (default: nix)
    pub backend: Option<String>,
    /// Tailscale authkey (or set TAILSCALE_AUTHKEY env)
    pub tailscale_authkey: Option<String>,
    /// Custom domain to attach
    pub custom_domain: Option<String>,
    /// Domain mode: dns or forward (default: dns)
    pub domain_mode: Option<String>,
    /// Whether the DNS record should be proxied through Cloudflare (default: false)
    pub proxied: Option<bool>,
    /// Runtime: sprite or railway (default: sprite)
    pub runtime: Option<String>,
    /// Port for railway domain attach
    pub port: Option<i32>,
}

#[macros::mcp_tool(
    name = "operate_den",
    description = "Operations workflow: Sprite lifecycle actions plus sesame-backed domains."
)]
#[derive(Debug, Deserialize, Serialize, JsonSchema)]
pub struct OperateDenTool {
    /// Action: list, redeploy, destroy, domain, logs, or status
    pub action: String,
    /// Name of the den (required for most actions)
    pub name: Option<String>,
    /// Custom domain for domain action
    pub custom_domain: Option<String>,
    /// Service name filter for Railway status
    pub service: Option<String>,
    /// Must be true to confirm destroy
    #[serde(default)]
    pub confirm_destroy: bool,
    /// Log timeout in seconds (default: 20)
    pub log_timeout_s: Option<i32>,
    /// Domain mode: dns or forward (default: dns)
    pub domain_mode: Option<String>,
    /// Whether the DNS record should be proxied through Cloudflare (default: false)
    pub proxied: Option<bool>,
    /// Runtime: sprite or railway (default: sprite)
    pub runtime: Option<String>,
    /// Port for railway domain attach
    pub port: Option<i32>,
}

#[macros::mcp_tool(
    name = "diagnose_den",
    description = "Diagnostics workflow: strict typing, property tests, and den smoke tests in one call."
)]
#[derive(Debug, Deserialize, Serialize, JsonSchema)]
pub struct DiagnoseDenTool {
    /// Whether to include the full Docker build in diagnostics (default: false)
    #[serde(default)]
    pub include_docker_build: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StepResult {
    pub step: String,
    pub command: Vec<String>,
    pub cwd: String,
    pub ok: bool,
    pub exit_code: Option<i32>,
    pub timed_out: bool,
    pub duration_ms: u64,
    pub stdout: String,
    pub stderr: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkflowError {
    pub kind: String,
    pub message: String,
    pub failing_step: String,
    pub command: Vec<String>,
    pub exit_code: Option<i32>,
    pub timed_out: bool,
    pub stdout: String,
    pub stderr: String,
    pub remediation: Vec<String>,
}

pub fn build_error(step: &StepResult, message: &str, remediation: Vec<String>) -> WorkflowError {
    WorkflowError {
        kind: "command_failure".to_string(),
        message: message.to_string(),
        failing_step: step.step.clone(),
        command: step.command.clone(),
        exit_code: step.exit_code,
        timed_out: step.timed_out,
        stdout: step.stdout.clone(),
        stderr: step.stderr.clone(),
        remediation,
    }
}

pub fn workflow_result(
    workflow: &str,
    ok: bool,
    steps: Vec<StepResult>,
    data: Value,
    error: Option<WorkflowError>,
    next_steps: Vec<String>,
) -> Value {
    json!({
        "workflow": workflow,
        "ok": ok,
        "data": data,
        "error": error,
        "next_steps": next_steps,
        "steps": steps,
    })
}

pub fn to_text(data: &Value) -> CallToolResult {
    CallToolResult::text_content(vec![TextContent::from(data.to_string())])
}

pub async fn run_step(
    step: &str,
    command: &[String],
    cwd: Option<&Path>,
    timeout_s: u64,
    input_text: Option<&str>,
) -> StepResult {
    let started = Instant::now();
    let run_cwd = cwd
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| "/root".into())));

    let (program, args) = match command.split_first() {
        Some((p, a)) => (p.as_str(), a),
        None => {
            return StepResult {
                step: step.to_string(),
                command: command.to_vec(),
                cwd: run_cwd.to_string_lossy().to_string(),
                ok: false,
                exit_code: None,
                timed_out: false,
                duration_ms: 0,
                stdout: String::new(),
                stderr: "empty command".to_string(),
            }
        }
    };

    let outcome = tokio::time::timeout(Duration::from_secs(timeout_s), async {
        let mut cmd = tokio::process::Command::new(program);
        cmd.args(args)
            .current_dir(&run_cwd)
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());

        if input_text.is_some() {
            cmd.stdin(std::process::Stdio::piped());
        } else {
            cmd.stdin(std::process::Stdio::null());
        }

        let mut child = match cmd.spawn() {
            Ok(c) => c,
            Err(e) => return Err(e.to_string()),
        };

        if let Some(text) = input_text {
            if let Some(mut stdin) = child.stdin.take() {
                let _ = stdin.write_all(text.as_bytes()).await;
                drop(stdin);
            }
        }

        match child.wait_with_output().await {
            Ok(output) => Ok(output),
            Err(e) => Err(e.to_string()),
        }
    })
    .await;

    let duration_ms = started.elapsed().as_millis() as u64;

    match outcome {
        Ok(Ok(output)) => StepResult {
            step: step.to_string(),
            command: command.to_vec(),
            cwd: run_cwd.to_string_lossy().to_string(),
            ok: output.status.success(),
            exit_code: output.status.code(),
            timed_out: false,
            duration_ms,
            stdout: String::from_utf8_lossy(&output.stdout).to_string(),
            stderr: String::from_utf8_lossy(&output.stderr).to_string(),
        },
        Ok(Err(e)) => StepResult {
            step: step.to_string(),
            command: command.to_vec(),
            cwd: run_cwd.to_string_lossy().to_string(),
            ok: false,
            exit_code: None,
            timed_out: false,
            duration_ms,
            stdout: String::new(),
            stderr: e,
        },
        Err(_) => StepResult {
            step: step.to_string(),
            command: command.to_vec(),
            cwd: run_cwd.to_string_lossy().to_string(),
            ok: false,
            exit_code: None,
            timed_out: true,
            duration_ms,
            stdout: String::new(),
            stderr: format!("Timed out after {timeout_s}s"),
        },
    }
}

pub async fn command_exists(cmd: &str) -> bool {
    let step = run_step(
        "check_command",
        &[
            "bash".to_string(),
            "-lc".to_string(),
            format!("command -v {cmd}"),
        ],
        None,
        15,
        None,
    )
    .await;
    step.ok
}

async fn discover_porkbun_domains_fallback() -> Vec<String> {
    let client = match reqwest::Client::builder()
        .use_rustls_tls()
        .build()
    {
        Ok(c) => c,
        Err(_) => return vec![],
    };
    den_core::porkbun::discover_porkbun_domains_from_sesame_config(&client, None)
        .await
        .unwrap_or_default()
}

pub async fn sesame_owned_domains() -> Vec<String> {
    match den_core::resolve_sesame_command() {
        Ok(mut sesame_cmd) => {
            sesame_cmd.extend_from_slice(&[
                "domain".to_string(),
                "list".to_string(),
                "--all".to_string(),
                "--json".to_string(),
            ]);
            let step = run_step("sesame_domain_list", &sesame_cmd, None, 30, None).await;
            if step.ok {
                if let Ok(payload) = serde_json::from_str::<Vec<Value>>(&step.stdout) {
                    let domains: Vec<String> = payload
                        .iter()
                        .filter_map(|row| {
                            row.get("domain")
                                .and_then(|v| v.as_str())
                                .map(|s| s.to_string())
                        })
                        .filter(|s| !s.is_empty())
                        .collect();
                    if !domains.is_empty() {
                        return domains;
                    }
                }
            }
            discover_porkbun_domains_fallback().await
        }
        Err(_) => discover_porkbun_domains_fallback().await,
    }
}

pub async fn configured_domain_zones() -> HashMap<den_core::DomainProvider, Vec<String>> {
    let mut map = HashMap::new();
    let cloudflare_domains = match den_core::cloudflare_api_token() {
        Some(token) => {
            let client = den_core::CloudflareClient::new(token);
            client.discover_domains().await
        }
        None => vec![],
    };
    let sesame_domains = sesame_owned_domains().await;
    map.insert(den_core::DomainProvider::Cloudflare, cloudflare_domains);
    map.insert(den_core::DomainProvider::Sesame, sesame_domains);
    map
}

fn resolve_runtime(s: Option<&str>) -> den_core::RuntimeProvider {
    match s {
        Some("railway") => den_core::RuntimeProvider::Railway,
        _ => den_core::RuntimeProvider::Sprite,
    }
}

pub async fn provision_den(tool: ProvisionDenTool) -> Result<CallToolResult, CallToolError> {
    let mut steps = Vec::new();
    let den_name = den_core::normalize_den_name(&tool.name);
    let backend = tool.backend.as_deref().unwrap_or("nix");
    let runtime_provider = resolve_runtime(tool.runtime.as_deref());
    let domain_mode = tool.domain_mode.as_deref().unwrap_or("dns");
    let proxied = tool.proxied.unwrap_or(false);

    let required_commands = if matches!(runtime_provider, den_core::RuntimeProvider::Sprite) {
        vec!["sprite"]
    } else {
        vec!["railway"]
    };

    for cmd in &required_commands {
        if !command_exists(cmd).await {
            return Ok(to_text(&workflow_result(
                "provision_den",
                false,
                steps,
                json!({}),
                Some(WorkflowError {
                    kind: "missing_dependency".to_string(),
                    message: format!("Required command not found: {cmd}"),
                    failing_step: "preflight".to_string(),
                    command: vec!["command".to_string(), "-v".to_string(), cmd.to_string()],
                    exit_code: None,
                    timed_out: false,
                    stdout: String::new(),
                    stderr: format!("{cmd} is not on PATH"),
                    remediation: vec![
                        format!("Install the {cmd} CLI and authenticate."),
                        "Retry provision_den after the CLI is available.".to_string(),
                    ],
                }),
                vec![],
            )));
        }
    }

    let project = project_dir();
    if !project.is_dir() {
        return Ok(to_text(&workflow_result(
            "provision_den",
            false,
            steps,
            json!({}),
            Some(WorkflowError {
                kind: "missing_project".to_string(),
                message: format!("den project directory not found: {}", project.display()),
                failing_step: "preflight".to_string(),
                command: vec!["test".to_string(), "-d".to_string(), project.to_string_lossy().to_string()],
                exit_code: None,
                timed_out: false,
                stdout: String::new(),
                stderr: "Project directory missing".to_string(),
                remediation: vec![
                    "Clone or restore ~/Projects/den.".to_string(),
                    "Run the command again after restoring project files.".to_string(),
                ],
            }),
            vec![],
        )));
    }

    match runtime_provider {
        den_core::RuntimeProvider::Sprite => {
            let sprite_auth = run_step(
                "sprite_list",
                &den_core::sprite_command(&["list"], None),
                Some(&project),
                20,
                None,
            )
            .await;
            steps.push(sprite_auth.clone());
            if !sprite_auth.ok {
                return Ok(to_text(&workflow_result(
                    "provision_den",
                    false,
                    steps,
                    json!({}),
                    Some(build_error(
                        &sprite_auth,
                        "Sprite authentication check failed.",
                        vec![
                            "Run: sprite login".to_string(),
                            "Verify you can run: sprite list".to_string(),
                            "Retry provision_den after successful login".to_string(),
                        ],
                    )),
                    vec![],
                )));
            }

            let create_cmd = den_core::sprite_command(&["create", "-skip-console"], Some(&den_name));
            let create_step = run_step(
                "sprite_create",
                &create_cmd,
                Some(&project),
                180,
                Some(&format!("{den_name}\n")),
            )
            .await;
            steps.push(create_step.clone());
            if !create_step.ok {
                return Ok(to_text(&workflow_result(
                    "provision_den",
                    false,
                    steps,
                    json!({}),
                    Some(build_error(
                        &create_step,
                        "Provisioning failed at sprite_create",
                        vec![
                            "Inspect stderr/stdout in this error payload.".to_string(),
                            "Fix auth or provider state, then retry.".to_string(),
                        ],
                    )),
                    vec![],
                )));
            }
        }
        den_core::RuntimeProvider::Railway => {
            let railway_status = run_step(
                "railway_status",
                &vec!["railway".to_string(), "status".to_string(), "--json".to_string()],
                Some(&project),
                20,
                None,
            )
            .await;
            steps.push(railway_status.clone());
            if !railway_status.ok {
                return Ok(to_text(&workflow_result(
                    "provision_den",
                    false,
                    steps,
                    json!({}),
                    Some(build_error(
                        &railway_status,
                        "Railway authentication or project check failed.",
                        vec![
                            "Run: railway login".to_string(),
                            "Link the project directory with Railway if needed.".to_string(),
                            "Retry provision_den after railway status succeeds.".to_string(),
                        ],
                    )),
                    vec![],
                )));
            }
        }
    }

    if let Some(ref custom_domain) = tool.custom_domain {
        if matches!(runtime_provider, den_core::RuntimeProvider::Sprite) {
            let url_step = run_step(
                "sprite_url",
                &den_core::sprite_command(&["url"], Some(&den_name)),
                Some(&project),
                20,
                None,
            )
            .await;
            steps.push(url_step.clone());
            let target_url = if url_step.ok {
                den_core::parse_sprite_url(&url_step.stdout)
            } else {
                None
            };

            if !url_step.ok || target_url.is_none() {
                return Ok(to_text(&workflow_result(
                    "provision_den",
                    false,
                    steps,
                    json!({ "den_name": den_name, "backend": backend, "partial_success": true }),
                    Some(build_error(
                        &url_step,
                        "Provision succeeded but reading the Sprite URL failed.",
                        vec![
                            "Run sprite url manually for the target den.".to_string(),
                            "Retry the domain operation after confirming the URL.".to_string(),
                        ],
                    )),
                    vec![],
                )));
            }

            let provider_domains = configured_domain_zones().await;

            if domain_mode == "forward" {
                let public_step = run_step(
                    "sprite_url_public",
                    &den_core::sprite_command(
                        &["url", "update", "--auth", "public"],
                        Some(&den_name),
                    ),
                    Some(&project),
                    30,
                    None,
                )
                .await;
                steps.push(public_step.clone());
                if !public_step.ok {
                    return Ok(to_text(&workflow_result(
                        "provision_den",
                        false,
                        steps,
                        json!({ "den_name": den_name, "backend": backend, "partial_success": true }),
                        Some(build_error(
                            &public_step,
                            "Provision succeeded but making the Sprite URL public failed.",
                            vec![
                                "Run sprite url update --auth public manually.".to_string(),
                                "Retry the domain operation after the URL is public.".to_string(),
                            ],
                        )),
                        vec![],
                    )));
                }

                match den_core::resolve_sesame_command() {
                    Ok(sesame_cmd) => {
                        let sesame_domains = provider_domains
                            .get(&den_core::DomainProvider::Sesame)
                            .cloned()
                            .unwrap_or_default();
                        let forward_cmd = den_core::build_sesame_url_forward_command(
                            custom_domain,
                            target_url.as_deref().unwrap_or(""),
                            &sesame_domains,
                        )
                        .unwrap_or_default();
                        let mut full_cmd = sesame_cmd;
                        full_cmd.extend(forward_cmd);
                        let sesame_step = run_step("sesame_add_url_forward", &full_cmd, None, 60, None).await;
                        steps.push(sesame_step.clone());
                        if !sesame_step.ok {
                            return Ok(to_text(&workflow_result(
                                "provision_den",
                                false,
                                steps,
                                json!({ "den_name": den_name, "backend": backend, "partial_success": true }),
                                Some(build_error(
                                    &sesame_step,
                                    "Provision succeeded but adding the Porkbun URL forward failed.",
                                    vec![
                                        "Verify sesame credentials and owned domain resolution.".to_string(),
                                        "Retry operate_den(action='domain', ...).".to_string(),
                                    ],
                                )),
                                vec![],
                            )));
                        }
                    }
                    Err(_) => {
                        return Ok(to_text(&workflow_result(
                            "provision_den",
                            false,
                            steps,
                            json!({ "den_name": den_name, "backend": backend, "partial_success": true }),
                            Some(WorkflowError {
                                kind: "missing_dependency".to_string(),
                                message: "sesame is not on PATH and no local build was found".to_string(),
                                failing_step: "sesame_add_url_forward".to_string(),
                                command: vec!["sesame".to_string()],
                                exit_code: None,
                                timed_out: false,
                                stdout: String::new(),
                                stderr: "sesame is not on PATH".to_string(),
                                remediation: vec!["Install sesame CLI.".to_string()],
                            }),
                            vec![],
                        )));
                    }
                }
            } else {
                match den_core::resolve_custom_domain(custom_domain, &provider_domains) {
                    Ok(domain_match) => {
                        if matches!(domain_match.provider, den_core::DomainProvider::Cloudflare) {
                            let certs_cmd = den_core::fly_certs_add_command(&den_name, custom_domain)
                                .unwrap_or_default();
                            let certs_step = run_step(
                                "fly_certs_add",
                                &certs_cmd,
                                Some(&project),
                                60,
                                None,
                            )
                            .await;
                            steps.push(certs_step.clone());
                            if !certs_step.ok {
                                return Ok(to_text(&workflow_result(
                                    "provision_den",
                                    false,
                                    steps,
                                    json!({ "den_name": den_name, "backend": backend, "partial_success": true }),
                                    Some(build_error(
                                        &certs_step,
                                        "Provision succeeded but Cloudflare DNS attachment failed (fly certs add).",
                                        vec![
                                            "Verify Cloudflare API token access and Fly certificate attach state.".to_string(),
                                            "Retry the domain operation after fixing DNS or certificate requirements.".to_string(),
                                        ],
                                    )),
                                    vec![],
                                )));
                            }

                            let payload: Value = serde_json::from_str(&certs_step.stdout).unwrap_or(json!({}));
                            let zone = &domain_match.zone;
                            let records = den_core::parse_fly_dns_records(custom_domain, zone, &payload, proxied)
                                .unwrap_or_default();

                            let upsert_results = match den_core::cloudflare_api_token() {
                                Some(token) => {
                                    let client = den_core::CloudflareClient::new(token);
                                    client.upsert_dns_records(zone, &records).await.unwrap_or_default()
                                }
                                None => vec![],
                            };
                            let applied: Vec<Value> = upsert_results
                                .iter()
                                .map(|r| json!({"action": r.action, "record": r.record}))
                                .collect();

                            steps.push(StepResult {
                                step: "cloudflare_dns_upsert".to_string(),
                                command: vec!["cloudflare-api".to_string(), "dns-records".to_string(), zone.clone()],
                                cwd: std::env::var("HOME").unwrap_or_else(|_| "/root".into()),
                                ok: true,
                                exit_code: Some(0),
                                timed_out: false,
                                duration_ms: 0,
                                stdout: serde_json::to_string(&applied).unwrap_or_default(),
                                stderr: String::new(),
                            });
                        } else {
                            return Ok(to_text(&workflow_result(
                                "provision_den",
                                false,
                                steps,
                                json!({ "den_name": den_name, "backend": backend, "partial_success": true }),
                                Some(WorkflowError {
                                    kind: "unsupported_action".to_string(),
                                    message: format!("DNS mode for sesame/Porkbun-held zones with sprite is not yet implemented for {custom_domain}"),
                                    failing_step: "domain_provider_dispatch".to_string(),
                                    command: vec![],
                                    exit_code: None,
                                    timed_out: false,
                                    stdout: String::new(),
                                    stderr: format!("{custom_domain} is held by {}", domain_match.provider),
                                    remediation: vec![
                                        "Use runtime='railway' to manage sesame/Porkbun DNS in dns mode.".to_string(),
                                        "Or move the zone to Cloudflare for managed DNS attachment.".to_string(),
                                    ],
                                }),
                                vec![],
                            )));
                        }
                    }
                    Err(_) => {
                        return Ok(to_text(&workflow_result(
                            "provision_den",
                            false,
                            steps,
                            json!({ "den_name": den_name, "backend": backend, "partial_success": true }),
                            Some(WorkflowError {
                                kind: "unsupported_action".to_string(),
                                message: format!("Could not resolve domain provider for {custom_domain}"),
                                failing_step: "domain_provider_dispatch".to_string(),
                                command: vec![],
                                exit_code: None,
                                timed_out: false,
                                stdout: String::new(),
                                stderr: format!("{custom_domain} domain provider unknown"),
                                remediation: vec!["Ensure the domain is managed by Cloudflare or Porkbun/sesame.".to_string()],
                            }),
                            vec![],
                        )));
                    }
                }
            }
        } else {
            return Ok(to_text(&workflow_result(
                "provision_den",
                false,
                steps,
                json!({}),
                Some(WorkflowError {
                    kind: "unsupported_action".to_string(),
                    message: "Domain attachment for Railway runtime in provision_den is not yet implemented in Rust".to_string(),
                    failing_step: "runtime_provider_dispatch".to_string(),
                    command: vec![],
                    exit_code: None,
                    timed_out: false,
                    stdout: String::new(),
                    stderr: format!("runtime={}", tool.runtime.as_deref().unwrap_or("railway")),
                    remediation: vec![
                        "Use operate_den(action='domain', runtime='railway') after provisioning.".to_string(),
                    ],
                }),
                vec![],
            )));
        }
    }

    let short_name = den_name.strip_prefix("den-").unwrap_or(&den_name);
    Ok(to_text(&workflow_result(
        "provision_den",
        true,
        steps,
        json!({ "den_name": den_name, "backend": backend, "custom_domain": tool.custom_domain }),
        None,
        vec![
            format!("den connect {short_name}"),
            format!("den status {short_name}"),
        ],
    )))
}

pub async fn operate_den(tool: OperateDenTool) -> Result<CallToolResult, CallToolError> {
    let mut steps = Vec::new();
    let runtime_provider = resolve_runtime(tool.runtime.as_deref());
    let runtime_str = tool.runtime.as_deref().unwrap_or("sprite");
    let domain_mode = tool.domain_mode.as_deref().unwrap_or("dns");
    let proxied = tool.proxied.unwrap_or(false);
    let project = project_dir();

    match tool.action.as_str() {
        "list" => {
            if matches!(runtime_provider, den_core::RuntimeProvider::Sprite) {
                let list_step = run_step(
                    "sprite_list_dens",
                    &den_core::sprite_command(&["list", "-prefix", "den-"], None),
                    Some(&project),
                    20,
                    None,
                )
                .await;
                steps.push(list_step.clone());
                if !list_step.ok {
                    return Ok(to_text(&workflow_result(
                        "operate_den",
                        false,
                        steps,
                        json!({}),
                        Some(build_error(
                            &list_step,
                            "Failed to list dens from Sprite.",
                            vec![
                                "Ensure sprite is installed and authenticated.".to_string(),
                                "Run sprite list manually.".to_string(),
                                "Retry operate_den(action='list').".to_string(),
                            ],
                        )),
                        vec![],
                    )));
                }
                let dens: Vec<&str> = list_step
                    .stdout
                    .lines()
                    .filter(|l| l.starts_with("den-"))
                    .map(|l| l.trim())
                    .collect();
                return Ok(to_text(&workflow_result(
                    "operate_den",
                    true,
                    steps,
                    json!({ "runtime": runtime_str, "dens": dens, "count": dens.len() }),
                    None,
                    vec![],
                )));
            }

            let list_cmd = match den_core::railway_list_command() {
                Ok(c) => c,
                Err(e) => {
                    return Ok(to_text(&workflow_result(
                        "operate_den",
                        false,
                        steps,
                        json!({}),
                        Some(WorkflowError {
                            kind: "missing_dependency".to_string(),
                            message: format!("Railway CLI not available: {e}"),
                            failing_step: "preflight".to_string(),
                            command: vec![],
                            exit_code: None,
                            timed_out: false,
                            stdout: String::new(),
                            stderr: e.to_string(),
                            remediation: vec!["Install railway CLI.".to_string()],
                        }),
                        vec![],
                    )));
                }
            };
            let list_step = run_step("railway_list_projects", &list_cmd, Some(&project), 30, None).await;
            steps.push(list_step.clone());
            if !list_step.ok {
                return Ok(to_text(&workflow_result(
                    "operate_den",
                    false,
                    steps,
                    json!({}),
                    Some(build_error(
                        &list_step,
                        "Failed to list Railway projects.",
                        vec![
                            "Ensure railway is installed and authenticated.".to_string(),
                            "Run railway list --json manually.".to_string(),
                            "Retry operate_den(action='list', runtime='railway').".to_string(),
                        ],
                    )),
                    vec![],
                )));
            }
            let payload: Value = match serde_json::from_str(&list_step.stdout) {
                Ok(v) => v,
                Err(e) => {
                    return Ok(to_text(&workflow_result(
                        "operate_den",
                        false,
                        steps,
                        json!({}),
                        Some(WorkflowError {
                            kind: "command_failure".to_string(),
                            message: "Railway project list returned malformed JSON.".to_string(),
                            failing_step: list_step.step.clone(),
                            command: list_step.command.clone(),
                            exit_code: list_step.exit_code,
                            timed_out: list_step.timed_out,
                            stdout: list_step.stdout.clone(),
                            stderr: e.to_string(),
                            remediation: vec![
                                "Run railway list --json manually to inspect the payload.".to_string(),
                                "Retry operate_den(action='list', runtime='railway') after fixing Railway auth.".to_string(),
                            ],
                        }),
                        vec![],
                    )));
                }
            };
            let projects = den_core::parse_railway_projects(&payload).unwrap_or_default();
            let dens: Vec<&str> = projects.iter().filter(|p| p.name.starts_with("den-")).map(|p| p.name.as_str()).collect();
            return Ok(to_text(&workflow_result(
                "operate_den",
                true,
                steps,
                json!({ "runtime": runtime_str, "dens": dens, "count": dens.len() }),
                None,
                vec![],
            )));
        }



        _ => {}
    }

    let name = match &tool.name {
        Some(n) => n.clone(),
        None => {
            return Ok(to_text(&workflow_result(
                "operate_den",
                false,
                steps,
                json!({}),
                Some(WorkflowError {
                    kind: "invalid_input".to_string(),
                    message: format!("name is required for action={}", tool.action),
                    failing_step: "input_validation".to_string(),
                    command: vec![],
                    exit_code: None,
                    timed_out: false,
                    stdout: String::new(),
                    stderr: "Missing name".to_string(),
                    remediation: vec![format!("Provide name, e.g. operate_den(action='{}', name='myproject').", tool.action)],
                }),
                vec![],
            )));
        }
    };

    let den_name = den_core::normalize_den_name(&name);

    match tool.action.as_str() {
        "redeploy" => {
            match runtime_provider {
                den_core::RuntimeProvider::Sprite => {
                    let nonce = format!(
                        "{}",
                        std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH)
                            .unwrap()
                            .as_nanos()
                    );
                    let comment = den_core::make_sprite_redeploy_comment(&den_name, &nonce);

                    let cp_step = run_step(
                        "sprite_checkpoint_create",
                        &den_core::sprite_checkpoint_create_command(&den_name, &comment),
                        Some(&project),
                        60,
                        None,
                    )
                    .await;
                    steps.push(cp_step.clone());
                    if !cp_step.ok {
                        return Ok(to_text(&workflow_result(
                            "operate_den",
                            false,
                            steps,
                            json!({}),
                            Some(build_error(
                                &cp_step,
                                &format!("Checkpoint creation failed for {den_name}"),
                                vec![
                                    "Run sprite checkpoint list manually to verify checkpoints.".to_string(),
                                    "Ensure sprite CLI is authenticated and den exists.".to_string(),
                                ],
                            )),
                            vec![],
                        )));
                    }

                    // Try API first, fall back to CLI list
                    let api_cmd = den_core::sprite_command(&["api", "/checkpoints"], Some(&den_name));
                    let api_step =
                        run_step("sprite_api_list_checkpoints", &api_cmd, Some(&project), 30, None)
                            .await;
                    steps.push(api_step.clone());

                    let checkpoint_id = if api_step.ok && !api_step.stdout.is_empty() {
                        den_core::find_checkpoint_version_in_api_output(&api_step.stdout, &comment)
                    } else {
                        let list_cmd =
                            den_core::sprite_command(&["checkpoint", "list"], Some(&den_name));
                        let list_step = run_step(
                            "sprite_checkpoint_list",
                            &list_cmd,
                            Some(&project),
                            30,
                            None,
                        )
                        .await;
                        steps.push(list_step.clone());
                        if list_step.ok && !list_step.stdout.is_empty() {
                            den_core::find_checkpoint_version_in_list_output(&list_step.stdout, &comment)
                        } else {
                            None
                        }
                    };

                    let checkpoint_id = match checkpoint_id {
                        Some(id) => id,
                        None => {
                            return Ok(to_text(&workflow_result(
                                "operate_den",
                                false,
                                steps,
                                json!({}),
                                Some(WorkflowError {
                                    kind: "checkpoint_not_found".to_string(),
                                    message: format!(
                                        "Checkpoint created for {den_name} but ID could not be determined. Run 'sprite checkpoint list -s den_name' and 'sprite restore <id>' manually."
                                    ),
                                    failing_step: "checkpoint_lookup".to_string(),
                                    command: vec![],
                                    exit_code: None,
                                    timed_out: false,
                                    stdout: String::new(),
                                    stderr: String::new(),
                                    remediation: vec![
                                        "Run sprite checkpoint list -s den_name manually.".to_string(),
                                        "Then sprite restore <checkpoint_id> to complete redeploy."
                                            .to_string(),
                                    ],
                                }),
                                vec![],
                            )));
                        }
                    };

                    let restore_step = run_step(
                        "sprite_restore",
                        &den_core::sprite_restore_command(&den_name, &checkpoint_id),
                        Some(&project),
                        60,
                        None,
                    )
                    .await;
                    steps.push(restore_step.clone());
                    if !restore_step.ok {
                        return Ok(to_text(&workflow_result(
                            "operate_den",
                            false,
                            steps,
                            json!({}),
                            Some(build_error(
                                &restore_step,
                                &format!("Restore failed for {den_name}"),
                                vec![
                                    "Checkpoint was created. Run 'sprite restore <checkpoint_id>' manually."
                                        .to_string(),
                                ],
                            )),
                            vec![],
                        )));
                    }

                    return Ok(to_text(&workflow_result(
                        "operate_den",
                        true,
                        steps,
                        json!({
                            "action": "redeploy",
                            "den_name": den_name,
                            "checkpoint_id": checkpoint_id
                        }),
                        None,
                        vec![],
                    )));
                }
                den_core::RuntimeProvider::Railway => {
                    let redeploy_cmd = match den_core::railway_redeploy_command() {
                        Ok(c) => c,
                        Err(e) => {
                            return Ok(to_text(&workflow_result(
                                "operate_den",
                                false,
                                steps,
                                json!({}),
                                Some(WorkflowError {
                                    kind: "missing_dependency".to_string(),
                                    message: format!("Railway CLI not available: {e}"),
                                    failing_step: "preflight".to_string(),
                                    command: vec![],
                                    exit_code: None,
                                    timed_out: false,
                                    stdout: String::new(),
                                    stderr: e.to_string(),
                                    remediation: vec!["Install railway CLI.".to_string()],
                                }),
                                vec![],
                            )));
                        }
                    };
                    let step = run_step("railway_redeploy", &redeploy_cmd, Some(&project), 60, None).await;
                    steps.push(step.clone());
                    if !step.ok {
                        return Ok(to_text(&workflow_result(
                            "operate_den",
                            false,
                            steps,
                            json!({}),
                            Some(build_error(
                                &step,
                                "Railway redeploy failed",
                                vec![
                                    "Ensure railway CLI is authenticated and linked to a project.".to_string(),
                                    "Use railway login and railway link first.".to_string(),
                                ],
                            )),
                            vec![],
                        )));
                    }
                    return Ok(to_text(&workflow_result(
                        "operate_den",
                        true,
                        steps,
                        json!({ "action": "redeploy", "den_name": den_name }),
                        None,
                        vec![],
                    )));
                }
            }
        }
        "destroy" => {
            if !tool.confirm_destroy {
                return Ok(to_text(&workflow_result(
                    "operate_den",
                    false,
                    steps,
                    json!({}),
                    Some(WorkflowError {
                        kind: "safety_check".to_string(),
                        message: "Destroy requested without confirm_destroy=true".to_string(),
                        failing_step: "safety_guard".to_string(),
                        command: den_core::sprite_command(&["destroy", "-force"], Some(&den_name)),
                        exit_code: None,
                        timed_out: false,
                        stdout: String::new(),
                        stderr: "Operation blocked by safety guard".to_string(),
                        remediation: vec![
                            "Set confirm_destroy=true if deletion is intended.".to_string(),
                            "Use action='list' first to verify target den.".to_string(),
                        ],
                    }),
                    vec![],
                )));
            }

            match runtime_provider {
                den_core::RuntimeProvider::Sprite => {
                    let step = run_step(
                        "sprite_destroy",
                        &den_core::sprite_command(&["destroy", "-force"], Some(&den_name)),
                        Some(&project),
                        60,
                        None,
                    )
                    .await;
                    steps.push(step.clone());
                    if !step.ok {
                        return Ok(to_text(&workflow_result(
                            "operate_den",
                            false,
                            steps,
                            json!({}),
                            Some(build_error(
                                &step,
                                &format!("Action destroy failed for {den_name}"),
                                vec![
                                    "Use command, stdout, and stderr in this payload to debug.".to_string(),
                                    "Fix auth/state issues, then retry the same action.".to_string(),
                                ],
                            )),
                            vec![],
                        )));
                    }
                }
                den_core::RuntimeProvider::Railway => {
                    let status_cmd = match den_core::railway_status_command() {
                        Ok(c) => c,
                        Err(e) => {
                            return Ok(to_text(&workflow_result(
                                "operate_den",
                                false,
                                steps,
                                json!({}),
                                Some(WorkflowError {
                                    kind: "missing_dependency".to_string(),
                                    message: format!("Railway CLI not available: {e}"),
                                    failing_step: "preflight".to_string(),
                                    command: vec![],
                                    exit_code: None,
                                    timed_out: false,
                                    stdout: String::new(),
                                    stderr: e.to_string(),
                                    remediation: vec!["Install railway CLI.".to_string()],
                                }),
                                vec![],
                            )));
                        }
                    };
                    let status_step = run_step("railway_status", &status_cmd, Some(&project), 30, None).await;
                    steps.push(status_step.clone());
                    if !status_step.ok {
                        return Ok(to_text(&workflow_result(
                            "operate_den",
                            false,
                            steps,
                            json!({}),
                            Some(build_error(
                                &status_step,
                                "Railway destroy requires a linked project, but Railway status failed.",
                                vec![
                                    "Run railway login and railway link in the den project directory.".to_string(),
                                    "Retry operate_den(action='destroy', runtime='railway', confirm_destroy=True).".to_string(),
                                ],
                            )),
                            vec![],
                        )));
                    }

                    let linked_payload: Value = serde_json::from_str(&status_step.stdout).unwrap_or(json!(null));
                    let linked_project = den_core::extract_railway_linked_project_name(&linked_payload);

                    if linked_project.as_deref() != Some(den_name.as_str()) {
                        return Ok(to_text(&workflow_result(
                            "operate_den",
                            false,
                            steps,
                            json!({}),
                            Some(WorkflowError {
                                kind: "safety_check".to_string(),
                                message: "Refusing Railway project deletion: linked project does not match requested den name.".to_string(),
                                failing_step: status_step.step.clone(),
                                command: status_step.command.clone(),
                                exit_code: status_step.exit_code,
                                timed_out: status_step.timed_out,
                                stdout: status_step.stdout.clone(),
                                stderr: status_step.stderr.clone(),
                                remediation: vec![
                                    format!("Link {} to the intended Railway project ({den_name}) before retrying.", project.display()),
                                    "Or delete the Railway project manually if you intend to target a different linked project.".to_string(),
                                ],
                            }),
                            vec![],
                        )));
                    }

                    let delete_cmd = match den_core::railway_delete_command(&den_name, true, true) {
                        Ok(c) => c,
                        Err(e) => {
                            return Ok(to_text(&workflow_result(
                                "operate_den",
                                false,
                                steps,
                                json!({}),
                                Some(WorkflowError {
                                    kind: "command_failure".to_string(),
                                    message: format!("Failed to build railway delete command: {e}"),
                                    failing_step: "command_build".to_string(),
                                    command: vec![],
                                    exit_code: None,
                                    timed_out: false,
                                    stdout: String::new(),
                                    stderr: e.to_string(),
                                    remediation: vec!["Check railway CLI availability.".to_string()],
                                }),
                                vec![],
                            )));
                        }
                    };
                    let step = run_step("railway_delete_project", &delete_cmd, Some(&project), 60, None).await;
                    steps.push(step.clone());
                    if !step.ok {
                        return Ok(to_text(&workflow_result(
                            "operate_den",
                            false,
                            steps,
                            json!({}),
                            Some(build_error(
                                &step,
                                &format!("Action destroy failed for {den_name}"),
                                vec![
                                    "Use command, stdout, and stderr in this payload to debug.".to_string(),
                                    "Fix auth/state issues, then retry the same action.".to_string(),
                                ],
                            )),
                            vec![],
                        )));
                    }
                }
            }
            return Ok(to_text(&workflow_result(
                "operate_den",
                true,
                steps,
                json!({ "action": "destroy", "den_name": den_name }),
                None,
                vec![],
            )));
        }

        "status" => {
            match runtime_provider {
                den_core::RuntimeProvider::Sprite => {
                    let step = run_step(
                        "sprite_status",
                        &den_core::sprite_command(&["url"], Some(&den_name)),
                        Some(&project),
                        30,
                        None,
                    )
                    .await;
                    steps.push(step.clone());
                    if !step.ok {
                        return Ok(to_text(&workflow_result(
                            "operate_den",
                            false,
                            steps,
                            json!({}),
                            Some(build_error(
                                &step,
                                &format!("Action status failed for {den_name}"),
                                vec![
                                    "Use command, stdout, and stderr in this payload to debug.".to_string(),
                                    "Fix auth/state issues, then retry the same action.".to_string(),
                                ],
                            )),
                            vec![],
                        )));
                    }
                    let url = den_core::parse_sprite_url(&step.stdout);
                    return Ok(to_text(&workflow_result(
                        "operate_den",
                        true,
                        steps,
                        json!({ "action": "status", "den_name": den_name, "url": url }),
                        None,
                        vec![],
                    )));
                }
                den_core::RuntimeProvider::Railway => {
                    let status_cmd = match den_core::railway_status_command() {
                        Ok(c) => c,
                        Err(e) => {
                            return Ok(to_text(&workflow_result(
                                "operate_den",
                                false,
                                steps,
                                json!({}),
                                Some(WorkflowError {
                                    kind: "missing_dependency".to_string(),
                                    message: format!("Railway CLI not available: {e}"),
                                    failing_step: "preflight".to_string(),
                                    command: vec![],
                                    exit_code: None,
                                    timed_out: false,
                                    stdout: String::new(),
                                    stderr: e.to_string(),
                                    remediation: vec!["Install railway CLI.".to_string()],
                                }),
                                vec![],
                            )));
                        }
                    };
                    let step = run_step("railway_status", &status_cmd, Some(&project), 30, None).await;
                    steps.push(step.clone());
                    if !step.ok {
                        return Ok(to_text(&workflow_result(
                            "operate_den",
                            false,
                            steps,
                            json!({}),
                            Some(build_error(
                                &step,
                                &format!("Action status failed for {den_name}"),
                                vec![
                                    "Use command, stdout, and stderr in this payload to debug.".to_string(),
                                    "Fix auth/state issues, then retry the same action.".to_string(),
                                ],
                            )),
                            vec![],
                        )));
                    }
                    let payload: Value = serde_json::from_str(&step.stdout).unwrap_or(json!(null));
                    let linked_project = den_core::extract_railway_linked_project_name(&payload);
                    let services = den_core::parse_railway_service_statuses(&payload);
                    let services_json: Vec<Value> = services
                        .iter()
                        .map(|s| {
                            json!({
                                "name": s.name,
                                "service_id": s.service_id,
                                "instance_id": s.instance_id,
                                "latest_deployment_id": s.latest_deployment_id,
                                "latest_deployment_status": s.latest_deployment_status,
                                "deployment_stopped": s.deployment_stopped,
                            })
                        })
                        .collect();

                    let mut data = json!({
                        "action": "status",
                        "den_name": den_name,
                        "custom_domain": tool.custom_domain,
                        "runtime": runtime_str,
                        "linked_project": linked_project,
                        "services": services_json,
                    });

                    if let Some(ref svc) = tool.service {
                        let matched = services.iter().find(|s| s.name == *svc);
                        match matched {
                            Some(m) => {
                                data.as_object_mut().unwrap().insert(
                                    "service".to_string(),
                                    json!({
                                        "name": m.name,
                                        "service_id": m.service_id,
                                        "instance_id": m.instance_id,
                                        "latest_deployment_id": m.latest_deployment_id,
                                        "latest_deployment_status": m.latest_deployment_status,
                                        "deployment_stopped": m.deployment_stopped,
                                    }),
                                );
                            }
                            None => {
                                return Ok(to_text(&workflow_result(
                                    "operate_den",
                                    false,
                                    steps,
                                    json!({}),
                                    Some(WorkflowError {
                                        kind: "invalid_input".to_string(),
                                        message: format!("Railway service not found: {svc}"),
                                        failing_step: step.step.clone(),
                                        command: step.command.clone(),
                                        exit_code: step.exit_code,
                                        timed_out: step.timed_out,
                                        stdout: step.stdout.clone(),
                                        stderr: "Requested service is not present in linked project status.".to_string(),
                                        remediation: vec![
                                            "Call operate_den(action='status', runtime='railway') without service to inspect available services.".to_string(),
                                            "Retry with a service name from the returned services list.".to_string(),
                                        ],
                                    }),
                                    vec![],
                                )));
                            }
                        }
                    }

                    data.as_object_mut().unwrap().insert("status".to_string(), payload);
                    return Ok(to_text(&workflow_result("operate_den", true, steps, data, None, vec![])));
                }
            }
        }

        "domain" => {
            let custom_domain = match &tool.custom_domain {
                Some(d) => d.clone(),
                None => {
                    return Ok(to_text(&workflow_result(
                        "operate_den",
                        false,
                        steps,
                        json!({}),
                        Some(WorkflowError {
                            kind: "invalid_input".to_string(),
                            message: "custom_domain is required for action=domain".to_string(),
                            failing_step: "input_validation".to_string(),
                            command: vec![],
                            exit_code: None,
                            timed_out: false,
                            stdout: String::new(),
                            stderr: "Missing custom_domain".to_string(),
                            remediation: vec!["Provide custom_domain like dev.example.com".to_string()],
                        }),
                        vec![],
                    )));
                }
            };

            let target_url: Option<String> = if matches!(runtime_provider, den_core::RuntimeProvider::Sprite) {
                let url_step = run_step(
                    "sprite_url",
                    &den_core::sprite_command(&["url"], Some(&den_name)),
                    Some(&project),
                    20,
                    None,
                )
                .await;
                steps.push(url_step.clone());
                let url = if url_step.ok {
                    den_core::parse_sprite_url(&url_step.stdout)
                } else {
                    None
                };
                if !url_step.ok || url.is_none() {
                    return Ok(to_text(&workflow_result(
                        "operate_den",
                        false,
                        steps,
                        json!({}),
                        Some(build_error(
                            &url_step,
                            &format!("Action domain failed for {den_name}"),
                            vec![
                                "Use command, stdout, and stderr in this payload to debug.".to_string(),
                                "Fix auth/state issues, then retry the same action.".to_string(),
                            ],
                        )),
                        vec![],
                    )));
                }
                url
            } else {
                None
            };

            let provider_domains = configured_domain_zones().await;

            if domain_mode == "dns" {
                match den_core::resolve_custom_domain(&custom_domain, &provider_domains) {
                    Ok(domain_match) => {
                        if matches!(domain_match.provider, den_core::DomainProvider::Cloudflare) {
                            let certs_cmd = den_core::fly_certs_add_command(&den_name, &custom_domain)
                                .unwrap_or_default();
                            let certs_step = run_step(
                                "fly_certs_add",
                                &certs_cmd,
                                Some(&project),
                                60,
                                None,
                            )
                            .await;
                            steps.push(certs_step.clone());
                            if !certs_step.ok {
                                return Ok(to_text(&workflow_result(
                                    "operate_den",
                                    false,
                                    steps,
                                    json!({}),
                                    Some(build_error(
                                        &certs_step,
                                        &format!("Action domain failed for {den_name}"),
                                        vec![
                                            "Use command, stdout, and stderr in this payload to debug.".to_string(),
                                            "Fix auth/state issues, then retry the same action.".to_string(),
                                        ],
                                    )),
                                    vec![],
                                )));
                            }

                            let payload: Value = serde_json::from_str(&certs_step.stdout).unwrap_or(json!({}));
                            let zone = &domain_match.zone;
                            let records = if matches!(runtime_provider, den_core::RuntimeProvider::Sprite) {
                                den_core::parse_fly_dns_records(&custom_domain, zone, &payload, proxied).unwrap_or_default()
                            } else {
                                den_core::parse_railway_dns_records(&custom_domain, zone, &payload, proxied).unwrap_or_default()
                            };

                            let upsert_results = match den_core::cloudflare_api_token() {
                                Some(token) => {
                                    let client = den_core::CloudflareClient::new(token);
                                    client.upsert_dns_records(zone, &records).await.unwrap_or_default()
                                }
                                None => vec![],
                            };
                            let applied: Vec<Value> = upsert_results
                                .iter()
                                .map(|r| json!({"action": r.action, "record": r.record}))
                                .collect();

                            steps.push(StepResult {
                                step: "cloudflare_dns_upsert".to_string(),
                                command: vec!["cloudflare-api".to_string(), "dns-records".to_string(), zone.clone()],
                                cwd: std::env::var("HOME").unwrap_or_else(|_| "/root".into()),
                                ok: true,
                                exit_code: Some(0),
                                timed_out: false,
                                duration_ms: 0,
                                stdout: serde_json::to_string(&applied).unwrap_or_default(),
                                stderr: String::new(),
                            });
                        } else if matches!(domain_match.provider, den_core::DomainProvider::Sesame)
                            && matches!(runtime_provider, den_core::RuntimeProvider::Sprite)
                            && target_url.is_some()
                        {
                            let target = target_url.as_ref().unwrap();
                            let upsert_results = match den_core::porkbun::load_porkbun_creds(None) {
                                Ok(_creds) => {
                                    let client = reqwest::Client::new();
                                    let records = vec![den_core::DnsRecord {
                                        name: domain_match.subdomain.clone().unwrap_or_default(),
                                        record_type: "ALIAS".to_string(),
                                        content: target.clone(),
                                        proxied: false,
                                    }];
                                    den_core::porkbun::porkbun_upsert_dns_records(
                                        &client,
                                        &domain_match.zone,
                                        &records,
                                        None,
                                    )
                                    .await
                                    .unwrap_or_default()
                                }
                                Err(_) => vec![],
                            };
                            let applied: Vec<Value> = upsert_results
                                .iter()
                                .map(|(action, record)| {
                                    json!({
                                        "action": action,
                                        "record": {
                                            "name": record.name,
                                            "type": record.record_type,
                                            "content": record.content,
                                        }
                                    })
                                })
                                .collect();

                            steps.push(StepResult {
                                step: "porkbun_dns_upsert".to_string(),
                                command: vec!["porkbun-api".to_string(), "dns-records".to_string(), domain_match.zone.clone()],
                                cwd: std::env::var("HOME").unwrap_or_else(|_| "/root".into()),
                                ok: true,
                                exit_code: Some(0),
                                timed_out: false,
                                duration_ms: 0,
                                stdout: serde_json::to_string(&applied).unwrap_or_default(),
                                stderr: String::new(),
                            });
                        } else if matches!(domain_match.provider, den_core::DomainProvider::Sesame)
                            && matches!(runtime_provider, den_core::RuntimeProvider::Railway)
                        {
                            let attach_cmd = match den_core::railway_domain_attach_command(
                                &den_name,
                                &custom_domain,
                                tool.port.map(|p| p as u16),
                            ) {
                                Ok(c) => c,
                                Err(e) => {
                                    return Ok(to_text(&workflow_result(
                                        "operate_den",
                                        false,
                                        steps,
                                        json!({}),
                                        Some(WorkflowError {
                                            kind: "command_failure".to_string(),
                                            message: format!("Failed to build railway domain attach command: {e}"),
                                            failing_step: "command_build".to_string(),
                                            command: vec![],
                                            exit_code: None,
                                            timed_out: false,
                                            stdout: String::new(),
                                            stderr: e.to_string(),
                                            remediation: vec!["Check railway CLI availability.".to_string()],
                                        }),
                                        vec![],
                                    )));
                                }
                            };
                            let attach_step = run_step("railway_domain_attach", &attach_cmd, Some(&project), 60, None).await;
                            steps.push(attach_step.clone());
                            if !attach_step.ok {
                                return Ok(to_text(&workflow_result(
                                    "operate_den",
                                    false,
                                    steps,
                                    json!({}),
                                    Some(build_error(
                                        &attach_step,
                                        &format!("Action domain failed for {den_name}"),
                                        vec![
                                            "Use command, stdout, and stderr in this payload to debug.".to_string(),
                                            "Fix auth/state issues, then retry the same action.".to_string(),
                                        ],
                                    )),
                                    vec![],
                                )));
                            }
                        } else {
                            return Ok(to_text(&workflow_result(
                                "operate_den",
                                false,
                                steps,
                                json!({}),
                                Some(WorkflowError {
                                    kind: "unsupported_action".to_string(),
                                    message: format!("DNS mode is not implemented yet for {}-held zones", domain_match.provider),
                                    failing_step: "domain_provider_dispatch".to_string(),
                                    command: vec![],
                                    exit_code: None,
                                    timed_out: false,
                                    stdout: String::new(),
                                    stderr: format!("{custom_domain} is held by {}", domain_match.provider),
                                    remediation: vec![
                                        "Use runtime='railway' to manage sesame/Porkbun DNS in dns mode.".to_string(),
                                        "Or move the zone to Cloudflare for managed DNS attachment.".to_string(),
                                    ],
                                }),
                                vec![],
                            )));
                        }
                    }
                    Err(_) => {
                        return Ok(to_text(&workflow_result(
                            "operate_den",
                            false,
                            steps,
                            json!({}),
                            Some(WorkflowError {
                                kind: "unsupported_action".to_string(),
                                message: format!("Could not resolve domain provider for {custom_domain}"),
                                failing_step: "domain_provider_dispatch".to_string(),
                                command: vec![],
                                exit_code: None,
                                timed_out: false,
                                stdout: String::new(),
                                stderr: format!("{custom_domain} domain provider unknown"),
                                remediation: vec!["Ensure the domain is managed by Cloudflare or Porkbun/sesame.".to_string()],
                            }),
                            vec![],
                        )));
                    }
                }
            } else {
                if !matches!(runtime_provider, den_core::RuntimeProvider::Sprite) {
                    return Ok(to_text(&workflow_result(
                        "operate_den",
                        false,
                        steps,
                        json!({}),
                        Some(WorkflowError {
                            kind: "unsupported_action".to_string(),
                            message: "Forward mode is currently implemented for Sprite-backed runtimes only".to_string(),
                            failing_step: "runtime_provider_dispatch".to_string(),
                            command: vec![],
                            exit_code: None,
                            timed_out: false,
                            stdout: String::new(),
                            stderr: format!("runtime={runtime_str}"),
                            remediation: vec![
                                "Use runtime='sprite' for forward mode.".to_string(),
                                "Use domain_mode='dns' with Cloudflare-managed zones for Railway.".to_string(),
                            ],
                        }),
                        vec![],
                    )));
                }

                let public_step = run_step(
                    "sprite_url_public",
                    &den_core::sprite_command(
                        &["url", "update", "--auth", "public"],
                        Some(&den_name),
                    ),
                    Some(&project),
                    30,
                    None,
                )
                .await;
                steps.push(public_step.clone());
                if !public_step.ok {
                    return Ok(to_text(&workflow_result(
                        "operate_den",
                        false,
                        steps,
                        json!({}),
                        Some(build_error(
                            &public_step,
                            &format!("Action domain failed for {den_name}"),
                            vec![
                                "Use command, stdout, and stderr in this payload to debug.".to_string(),
                                "Fix auth/state issues, then retry the same action.".to_string(),
                            ],
                        )),
                        vec![],
                    )));
                }

                match den_core::resolve_sesame_command() {
                    Ok(sesame_cmd) => {
                        let sesame_domains = provider_domains
                            .get(&den_core::DomainProvider::Sesame)
                            .cloned()
                            .unwrap_or_default();
                        let forward_cmd = den_core::build_sesame_url_forward_command(
                            &custom_domain,
                            target_url.as_deref().unwrap_or(""),
                            &sesame_domains,
                        )
                        .unwrap_or_default();
                        let mut full_cmd = sesame_cmd;
                        full_cmd.extend(forward_cmd);
                        let domain_step = run_step("sesame_add_url_forward", &full_cmd, None, 60, None).await;
                        steps.push(domain_step.clone());
                        if !domain_step.ok {
                            return Ok(to_text(&workflow_result(
                                "operate_den",
                                false,
                                steps,
                                json!({}),
                                Some(build_error(
                                    &domain_step,
                                    &format!("Action domain failed for {den_name}"),
                                    vec![
                                        "Use command, stdout, and stderr in this payload to debug.".to_string(),
                                        "Fix auth/state issues, then retry the same action.".to_string(),
                                    ],
                                )),
                                vec![],
                            )));
                        }
                    }
                    Err(_) => {
                        return Ok(to_text(&workflow_result(
                            "operate_den",
                            false,
                            steps,
                            json!({}),
                            Some(WorkflowError {
                                kind: "missing_dependency".to_string(),
                                message: "sesame is not on PATH".to_string(),
                                failing_step: "sesame_add_url_forward".to_string(),
                                command: vec!["sesame".to_string()],
                                exit_code: None,
                                timed_out: false,
                                stdout: String::new(),
                                stderr: "sesame is not on PATH".to_string(),
                                remediation: vec!["Install sesame CLI.".to_string()],
                            }),
                            vec![],
                        )));
                    }
                }
            }

            return Ok(to_text(&workflow_result(
                "operate_den",
                true,
                steps,
                json!({ "action": "domain", "den_name": den_name, "custom_domain": custom_domain }),
                None,
                vec![],
            )));
        }

        other => Ok(to_text(&workflow_result(
            "operate_den",
            false,
            steps,
            json!({}),
            Some(WorkflowError {
                kind: "invalid_input".to_string(),
                message: format!("Unknown action: {other}"),
                failing_step: "input_validation".to_string(),
                command: vec![],
                exit_code: None,
                timed_out: false,
                stdout: String::new(),
                stderr: format!("action={other} is not supported"),
                remediation: vec!["Supported actions: list, status, destroy, domain, redeploy, logs".to_string()],
            }),
            vec![],
        ))),
    }
}

pub async fn diagnose_den(tool: DiagnoseDenTool) -> Result<CallToolResult, CallToolError> {
    let mut steps = Vec::new();
    let project = project_dir();

    let mut plan: Vec<(&str, Vec<String>, u64)> = vec![
        ("cargo_test", vec!["cargo".to_string(), "test".to_string(), "--workspace".to_string()], 180),
        ("cargo_build", vec!["cargo".to_string(), "build".to_string(), "--workspace".to_string()], 120),
        ("den_smoke", vec!["bash".to_string(), "tests/test-den.sh".to_string(), "--no-build".to_string()], 240),
    ];

    if tool.include_docker_build {
        plan.push(("den_full", vec!["bash".to_string(), "tests/test-den.sh".to_string()], 900));
    }

    for (step_name, command, timeout_s) in plan {
        let step = run_step(step_name, &command, Some(&project), timeout_s, None).await;
        steps.push(step.clone());
        if !step.ok {
            return Ok(to_text(&workflow_result(
                "diagnose_den",
                false,
                steps,
                json!({}),
                Some(build_error(
                    &step,
                    &format!("Diagnostics failed at {step_name}"),
                    vec![
                        "Inspect stderr/stdout in this payload for the exact failing assertion/command.".to_string(),
                        "Fix the root issue and rerun diagnose_den.".to_string(),
                        "Use include_docker_build=true only after smoke checks pass.".to_string(),
                    ],
                )),
                vec![],
            )));
        }
    }

    Ok(to_text(&workflow_result(
        "diagnose_den",
        true,
        steps,
        json!({ "include_docker_build": tool.include_docker_build }),
        None,
        vec![
            "If provisioning changed, run provision_den to validate runtime workflows.".to_string(),
        ],
    )))
}
