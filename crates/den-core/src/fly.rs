//! Fly CLI command builders.
//!
//! Port of the `fly_*` family in `src/den_cli/core.py`. Command builders
//! return `Vec<String>` argv. The `resolve_flyctl_command` function searches
//! PATH and falls back to `~/.fly/bin/flyctl`.

use std::env;
use std::path::PathBuf;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum FlyError {
    #[error("flyctl executable not found")]
    NotFound,
}

pub fn resolve_flyctl_command() -> Result<Vec<String>, FlyError> {
    for candidate in ["flyctl", "fly"] {
        if let Ok(path) = which::which(candidate) {
            return Ok(vec![path.to_string_lossy().to_string()]);
        }
    }
    if let Ok(home) = env::var("HOME") {
        let fallback = PathBuf::from(home).join(".fly/bin/flyctl");
        if fallback.is_file() {
            return Ok(vec![fallback.to_string_lossy().to_string()]);
        }
    }
    Err(FlyError::NotFound)
}

pub fn fly_certs_add_command(app_name: &str, hostname: &str) -> Result<Vec<String>, FlyError> {
    let mut cmd = resolve_flyctl_command()?;
    cmd.extend([
        "certs".to_string(),
        "add".to_string(),
        hostname.to_string(),
        "--app".to_string(),
        app_name.to_string(),
        "--json".to_string(),
    ]);
    Ok(cmd)
}

pub fn fly_certs_check_command(app_name: &str, hostname: &str) -> Result<Vec<String>, FlyError> {
    let mut cmd = resolve_flyctl_command()?;
    cmd.extend([
        "certs".to_string(),
        "check".to_string(),
        hostname.to_string(),
        "--app".to_string(),
        app_name.to_string(),
        "--json".to_string(),
    ]);
    Ok(cmd)
}

pub fn fly_certs_setup_command(app_name: &str, hostname: &str) -> Result<Vec<String>, FlyError> {
    let mut cmd = resolve_flyctl_command()?;
    cmd.extend([
        "certs".to_string(),
        "setup".to_string(),
        hostname.to_string(),
        "--app".to_string(),
        app_name.to_string(),
        "--json".to_string(),
    ]);
    Ok(cmd)
}
