//! Railway CLI command builders and JSON parsers.
//!
//! Port of the `railway_*` family in `src/den_cli/core.py`. Command builders
//! return `Vec<String>` argv. JSON parsers accept `serde_json::Value` and
//! return typed structs.

use serde_json::Value;
use std::env;
use std::path::PathBuf;
use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RailwayProjectSummary {
    pub name: String,
    pub project_id: Option<String>,
    pub workspace_name: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RailwayServiceStatusSummary {
    pub name: String,
    pub service_id: Option<String>,
    pub instance_id: Option<String>,
    pub latest_deployment_id: Option<String>,
    pub latest_deployment_status: Option<String>,
    pub deployment_stopped: Option<bool>,
}

#[derive(Debug, Error)]
pub enum RailwayError {
    #[error("railway executable not found")]
    NotFound,
}

pub fn resolve_railway_command() -> Result<Vec<String>, RailwayError> {
    if let Ok(path) = which::which("railway") {
        return Ok(vec![path.to_string_lossy().to_string()]);
    }
    if let Ok(home) = env::var("HOME") {
        let fallback = PathBuf::from(home)
            .join(".local/share/mise/installs/railway/4.37.2/railway");
        if fallback.is_file() {
            return Ok(vec![fallback.to_string_lossy().to_string()]);
        }
    }
    Err(RailwayError::NotFound)
}

pub fn railway_status_command() -> Result<Vec<String>, RailwayError> {
    let mut cmd = resolve_railway_command()?;
    cmd.extend(["status".to_string(), "--json".to_string()]);
    Ok(cmd)
}

pub fn railway_list_command() -> Result<Vec<String>, RailwayError> {
    let mut cmd = resolve_railway_command()?;
    cmd.extend(["list".to_string(), "--json".to_string()]);
    Ok(cmd)
}

pub fn railway_delete_command(
    project: &str,
    yes: bool,
    json_output: bool,
) -> Result<Vec<String>, RailwayError> {
    let mut cmd = resolve_railway_command()?;
    cmd.extend([
        "delete".to_string(),
        "-p".to_string(),
        project.to_string(),
    ]);
    if yes {
        cmd.push("-y".to_string());
    }
    if json_output {
        cmd.push("--json".to_string());
    }
    Ok(cmd)
}

pub fn railway_redeploy_command() -> Result<Vec<String>, RailwayError> {
    let mut cmd = resolve_railway_command()?;
    cmd.extend(["redeploy".to_string(), "-y".to_string(), "--json".to_string()]);
    Ok(cmd)
}

pub fn railway_domain_attach_command(
    service: &str,
    domain: &str,
    port: Option<u16>,
) -> Result<Vec<String>, RailwayError> {
    let mut cmd = resolve_railway_command()?;
    cmd.extend([
        "domain".to_string(),
        domain.to_string(),
        "--service".to_string(),
        service.to_string(),
        "--json".to_string(),
    ]);
    if let Some(p) = port {
        cmd.extend(["--port".to_string(), p.to_string()]);
    }
    Ok(cmd)
}

pub fn parse_railway_projects(payload: &Value) -> Result<Vec<RailwayProjectSummary>, String> {
    let arr = payload
        .as_array()
        .ok_or("Railway list response was not a JSON array")?;
    let mut projects = Vec::new();
    for row in arr {
        let name = match row.get("name").and_then(|v| v.as_str()) {
            Some(n) if !n.is_empty() => n,
            _ => continue,
        };
        let project_id = row
            .get("id")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(|s| s.to_string());
        let workspace_name = row
            .get("workspace")
            .and_then(|w| w.get("name"))
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(|s| s.to_string());
        projects.push(RailwayProjectSummary {
            name: name.to_string(),
            project_id,
            workspace_name,
        });
    }
    Ok(projects)
}

pub fn extract_railway_linked_project_name(payload: &Value) -> Option<String> {
    if let Some(project) = payload.get("project").and_then(|v| v.as_object()) {
        if let Some(name) = project.get("name").and_then(|v| v.as_str()) {
            if !name.is_empty() {
                return Some(name.to_string());
            }
        }
    }
    let has_shape = payload.get("environments").is_some()
        || payload.get("services").is_some()
        || payload.get("workspace").is_some();
    if has_shape {
        if let Some(name) = payload.get("name").and_then(|v| v.as_str()) {
            if !name.is_empty() {
                return Some(name.to_string());
            }
        }
    }
    None
}

pub fn parse_railway_service_statuses(payload: &Value) -> Vec<RailwayServiceStatusSummary> {
    let environments = match payload.get("environments") {
        Some(v) => v,
        None => return vec![],
    };
    let edges = match environments.get("edges").and_then(|v| v.as_array()) {
        Some(v) => v,
        None => return vec![],
    };

    let mut services = Vec::new();
    for env_edge in edges {
        let node = match env_edge.get("node") {
            Some(n) => n,
            None => continue,
        };
        let instances = match node.get("serviceInstances") {
            Some(v) => v,
            None => continue,
        };
        let inst_edges = match instances.get("edges").and_then(|v| v.as_array()) {
            Some(v) => v,
            None => continue,
        };

        for inst_edge in inst_edges {
            let inst_node = match inst_edge.get("node") {
                Some(n) => n,
                None => continue,
            };
            let name = match inst_node
                .get("serviceName")
                .and_then(|v| v.as_str())
            {
                Some(n) if !n.is_empty() => n.to_string(),
                _ => continue,
            };
            let service_id = inst_node
                .get("serviceId")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(|s| s.to_string());
            let instance_id = inst_node
                .get("id")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(|s| s.to_string());

            let (dep_id, dep_status, dep_stopped) =
                match inst_node.get("latestDeployment").and_then(|d| {
                    let id = d
                        .get("id")
                        .and_then(|v| v.as_str())
                        .filter(|s| !s.is_empty())
                        .map(|s| s.to_string());
                    let status = d
                        .get("status")
                        .and_then(|v| v.as_str())
                        .filter(|s| !s.is_empty())
                        .map(|s| s.to_string());
                    let stopped = d.get("deploymentStopped").and_then(|v| v.as_bool());
                    Some((id, status, stopped))
                }) {
                    Some(tuple) => tuple,
                    None => (None, None, None),
                };

            services.push(RailwayServiceStatusSummary {
                name,
                service_id,
                instance_id,
                latest_deployment_id: dep_id,
                latest_deployment_status: dep_status,
                deployment_stopped: dep_stopped,
            });
        }
    }
    services
}
