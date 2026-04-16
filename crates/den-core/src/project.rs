//! Project detection, backend inference, and run-command inference.
//!
//! Port of the `ProjectMarkers`, `InferredDenSetup`, `InferredRunCommand`,
//! and associated functions in `src/den_cli/core.py`. Functions that detect
//! markers or infer run commands accept `&Path` and perform minimal
//! filesystem reads; the decision logic (`infer_backend`, `infer_nix_packages`,
//! `infer_guix_packages`) is pure given the markers.

use crate::names::normalize_den_name;
use std::collections::HashSet;
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct ProjectMarkers {
    pub has_package_json: bool,
    pub has_bun_lock: bool,
    pub has_pyproject: bool,
    pub has_cargo_toml: bool,
    pub has_dockerfile: bool,
    pub has_containerfile: bool,
    pub has_mise_toml: bool,
    pub has_flox_toml: bool,
    pub has_helm_chart: bool,
    pub has_nix_flake: bool,
    pub has_shell_nix: bool,
    pub has_guix_manifest: bool,
    pub has_guix_channels: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Backend {
    Nix,
    Guix,
}

impl std::fmt::Display for Backend {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Backend::Nix => write!(f, "nix"),
            Backend::Guix => write!(f, "guix"),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InferredDenSetup {
    pub name: String,
    pub backend: Backend,
    pub dockerfile: Option<String>,
    pub nix_packages: Vec<String>,
    pub guix_packages: Vec<String>,
    pub environment: Vec<(String, String)>,
    pub reasons: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InferredRunCommand {
    pub command: Vec<String>,
    pub reasons: Vec<String>,
}

pub fn detect_project_markers(root: &Path) -> ProjectMarkers {
    ProjectMarkers {
        has_package_json: root.join("package.json").is_file(),
        has_bun_lock: root.join("bun.lock").is_file() || root.join("bun.lockb").is_file(),
        has_pyproject: root.join("pyproject.toml").is_file(),
        has_cargo_toml: root.join("Cargo.toml").is_file(),
        has_dockerfile: root.join("Dockerfile").is_file(),
        has_containerfile: root.join("Containerfile").is_file(),
        has_mise_toml: root.join("mise.toml").is_file(),
        has_flox_toml: root.join("flox.toml").is_file(),
        has_helm_chart: root.join("Chart.yaml").is_file() || root.join("charts").is_dir(),
        has_nix_flake: root.join("flake.nix").is_file(),
        has_shell_nix: root.join("shell.nix").is_file(),
        has_guix_manifest: root.join("guix").join("manifest.scm").is_file(),
        has_guix_channels: root.join("guix").join("channels.scm").is_file(),
    }
}

pub fn infer_den_setup(root: &Path) -> InferredDenSetup {
    let markers = detect_project_markers(root);
    let (backend, reasons) = infer_backend(&markers);
    let name = root
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("workspace")
        .to_string();

    let dockerfile = if markers.has_dockerfile {
        Some("Dockerfile".to_string())
    } else if markers.has_containerfile {
        Some("Containerfile".to_string())
    } else {
        None
    };

    let nix_packages = infer_nix_packages(&markers);
    let guix_packages = infer_guix_packages(&markers);

    let mut environment: Vec<(String, String)> = vec![
        ("DEN_NAME".to_string(), normalize_den_name(&name)),
        ("DEN_BACKEND".to_string(), backend.to_string()),
    ];
    if let Some(ref df) = dockerfile {
        environment.push(("DEN_DOCKERFILE".to_string(), df.clone()));
    }

    InferredDenSetup {
        name,
        backend,
        dockerfile,
        nix_packages,
        guix_packages,
        environment,
        reasons,
    }
}

pub fn infer_backend(markers: &ProjectMarkers) -> (Backend, Vec<String>) {
    let mut reasons = Vec::new();

    if markers.has_guix_manifest || markers.has_guix_channels {
        reasons.push("existing Guix manifests detected".to_string());
        return (Backend::Guix, reasons);
    }

    let nix_signals = markers.has_bun_lock
        || markers.has_package_json
        || markers.has_cargo_toml
        || markers.has_mise_toml
        || markers.has_flox_toml
        || markers.has_nix_flake
        || markers.has_shell_nix
        || markers.has_dockerfile
        || markers.has_containerfile
        || markers.has_helm_chart;

    if markers.has_pyproject && !nix_signals {
        reasons.push("standalone Python project detected".to_string());
        return (Backend::Guix, reasons);
    }

    if markers.has_bun_lock {
        reasons.push("bun lockfile detected".to_string());
    }
    if markers.has_package_json {
        reasons.push("package.json detected".to_string());
    }
    if markers.has_cargo_toml {
        reasons.push("Cargo.toml detected".to_string());
    }
    if markers.has_mise_toml {
        reasons.push("mise.toml detected".to_string());
    }
    if markers.has_flox_toml {
        reasons.push("flox.toml detected".to_string());
    }
    if markers.has_nix_flake || markers.has_shell_nix {
        reasons.push("existing Nix metadata detected".to_string());
    }
    if markers.has_dockerfile || markers.has_containerfile {
        reasons.push("container build file detected".to_string());
    }
    if markers.has_helm_chart {
        reasons.push("Helm chart detected".to_string());
    }
    if markers.has_pyproject && nix_signals {
        reasons.push("pyproject.toml detected alongside Nix/container signals".to_string());
    }

    if reasons.is_empty() {
        reasons.push("defaulting to Nix for portable podenv/container workflows".to_string());
    }

    (Backend::Nix, reasons)
}

pub fn infer_nix_packages(markers: &ProjectMarkers) -> Vec<String> {
    let mut packages = vec![
        "fish".to_string(),
        "git".to_string(),
        "helix".to_string(),
    ];
    if markers.has_bun_lock {
        packages.push("bun".to_string());
    } else if markers.has_package_json {
        packages.push("nodejs".to_string());
    }
    if markers.has_cargo_toml {
        packages.extend(["cargo".to_string(), "rustc".to_string()]);
    }
    if markers.has_pyproject {
        packages.push("python".to_string());
    }
    if markers.has_mise_toml {
        packages.push("mise".to_string());
    }
    if markers.has_flox_toml {
        packages.push("flox".to_string());
    }
    if markers.has_helm_chart {
        packages.push("helm".to_string());
    }
    dedup_preserve_order(&packages)
}

pub fn infer_guix_packages(markers: &ProjectMarkers) -> Vec<String> {
    let mut packages = vec![
        "fish".to_string(),
        "git".to_string(),
        "helix".to_string(),
        "zellij".to_string(),
        "jj".to_string(),
        "gh".to_string(),
        "fzf".to_string(),
        "ripgrep".to_string(),
        "fd".to_string(),
        "bat".to_string(),
    ];
    if markers.has_bun_lock {
        packages.extend(["node".to_string(), "bun".to_string()]);
    } else if markers.has_package_json {
        packages.push("node".to_string());
    }
    if markers.has_cargo_toml {
        packages.extend(["rust".to_string(), "cargo".to_string()]);
    }
    if markers.has_pyproject {
        packages.push("python".to_string());
    }
    if markers.has_helm_chart {
        packages.push("helm".to_string());
    }
    dedup_preserve_order(&packages)
}

fn dedup_preserve_order(items: &[String]) -> Vec<String> {
    let mut seen = HashSet::new();
    items
        .iter()
        .filter(|s| seen.insert((*s).clone()))
        .cloned()
        .collect()
}

pub fn infer_run_command(root: &Path) -> Option<InferredRunCommand> {
    let markers = detect_project_markers(root);
    if markers.has_mise_toml {
        if let Some(cmd) = infer_mise_run_command(root) {
            return Some(cmd);
        }
    }
    if markers.has_package_json {
        if let Some(cmd) = infer_package_json_run_command(root, markers.has_bun_lock) {
            return Some(cmd);
        }
    }
    if markers.has_cargo_toml {
        if let Some(cmd) = infer_cargo_run_command(root) {
            return Some(cmd);
        }
    }
    if markers.has_pyproject {
        if let Some(cmd) = infer_pyproject_run_command(root) {
            return Some(cmd);
        }
    }
    None
}

fn infer_mise_run_command(root: &Path) -> Option<InferredRunCommand> {
    let content = std::fs::read_to_string(root.join("mise.toml")).ok()?;
    let payload: toml::Value = toml::from_str(&content).ok()?;
    let tasks = payload.get("tasks")?.as_table()?;
    for task_name in ["start", "dev", "serve"] {
        if let Some(task) = tasks.get(task_name) {
            if let Some(run) = task.get("run").and_then(|v| v.as_str()) {
                if !run.trim().is_empty() {
                    return Some(InferredRunCommand {
                        command: vec![
                            "bash".to_string(),
                            "-lc".to_string(),
                            format!("mise trust && mise run {task_name}"),
                        ],
                        reasons: vec![
                            "mise.toml detected".to_string(),
                            format!("mise task \"{task_name}\" detected"),
                        ],
                    });
                }
            }
        }
    }
    None
}

fn infer_package_json_run_command(root: &Path, prefer_bun: bool) -> Option<InferredRunCommand> {
    let content = std::fs::read_to_string(root.join("package.json")).ok()?;
    let payload: serde_json::Value = serde_json::from_str(&content).ok()?;
    let scripts = payload.get("scripts")?.as_object()?;
    let runner = if prefer_bun { "bun" } else { "npm" };
    let mut reasons = vec![];
    if prefer_bun {
        reasons.push("bun lockfile detected".to_string());
    } else {
        reasons.push("package.json detected".to_string());
    }
    for script_name in ["dev", "start", "serve"] {
        if let Some(script) = scripts.get(script_name).and_then(|v| v.as_str()) {
            if !script.trim().is_empty() {
                reasons.push(format!("package.json script \"{script_name}\" detected"));
                return Some(InferredRunCommand {
                    command: vec![
                        runner.to_string(),
                        "run".to_string(),
                        script_name.to_string(),
                    ],
                    reasons,
                });
            }
        }
    }
    None
}

fn infer_cargo_run_command(root: &Path) -> Option<InferredRunCommand> {
    let content = std::fs::read_to_string(root.join("Cargo.toml")).ok()?;
    let payload: toml::Value = toml::from_str(&content).ok()?;
    let package_name = payload
        .get("package")
        .and_then(|p| p.get("name"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    if root.join("src/main.rs").is_file() {
        let mut reasons = vec![
            "Cargo.toml detected".to_string(),
            "src/main.rs detected".to_string(),
        ];
        if let Some(ref name) = package_name {
            reasons.push(format!("cargo package \"{name}\" detected"));
        }
        return Some(InferredRunCommand {
            command: vec!["cargo".to_string(), "run".to_string()],
            reasons,
        });
    }
    if let Some(bins) = payload.get("bin").and_then(|v| v.as_array()) {
        if bins.len() == 1 {
            if let Some(bin_name) = bins[0].get("name").and_then(|v| v.as_str()) {
                return Some(InferredRunCommand {
                    command: vec![
                        "cargo".to_string(),
                        "run".to_string(),
                        "--bin".to_string(),
                        bin_name.to_string(),
                    ],
                    reasons: vec![
                        "Cargo.toml detected".to_string(),
                        format!("cargo bin \"{bin_name}\" detected"),
                    ],
                });
            }
        }
    }
    None
}

fn infer_pyproject_run_command(root: &Path) -> Option<InferredRunCommand> {
    let content = std::fs::read_to_string(root.join("pyproject.toml")).ok()?;
    let payload: toml::Value = toml::from_str(&content).ok()?;

    if let Some(project) = payload.get("project").and_then(|v| v.as_table()) {
        if let Some(scripts) = project.get("scripts").and_then(|v| v.as_table()) {
            if scripts.len() == 1 {
                if let Some(script_name) = scripts.keys().next() {
                    if !script_name.is_empty() {
                        return Some(InferredRunCommand {
                            command: vec![
                                "uv".to_string(),
                                "run".to_string(),
                                script_name.clone(),
                            ],
                            reasons: vec![
                                "standalone Python project detected".to_string(),
                                format!("project.scripts entry \"{script_name}\" detected"),
                            ],
                        });
                    }
                }
            }
        }
        if let Some(project_name) = project.get("name").and_then(|v| v.as_str()) {
            let module_name = project_name.replace('-', "_");
            if root.join(&module_name).is_dir() || root.join("src").join(&module_name).is_dir() {
                return Some(InferredRunCommand {
                    command: vec![
                        "uv".to_string(),
                        "run".to_string(),
                        "python".to_string(),
                        "-m".to_string(),
                        module_name.clone(),
                    ],
                    reasons: vec![
                        "standalone Python project detected".to_string(),
                        format!("Python module \"{module_name}\" detected"),
                    ],
                });
            }
        }
    }

    if let Some(tool) = payload.get("tool").and_then(|v| v.as_table()) {
        if let Some(poetry) = tool.get("poetry").and_then(|v| v.as_table()) {
            if let Some(scripts) = poetry.get("scripts").and_then(|v| v.as_table()) {
                if scripts.len() == 1 {
                    if let Some(script_name) = scripts.keys().next() {
                        if !script_name.is_empty() {
                            return Some(InferredRunCommand {
                                command: vec![
                                    "poetry".to_string(),
                                    "run".to_string(),
                                    script_name.clone(),
                                ],
                                reasons: vec!["Poetry script entry detected".to_string()],
                            });
                        }
                    }
                }
            }
        }
    }

    None
}
