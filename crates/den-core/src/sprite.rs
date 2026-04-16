//! Sprite CLI command builders.
//!
//! Port of the `sprite_*_command` family in `src/den_cli/core.py`. Each
//! builder returns an owned `Vec<String>` argv — no shell interpolation,
//! no I/O. These are the functions exercised by the Hypothesis suite and
//! re-exercised by the proptest suite in `tests/core_properties.rs`.

use crate::names::{normalize_den_name, sprite_org};

pub fn sprite_command(args: &[&str], sprite_name: Option<&str>) -> Vec<String> {
    let mut cmd: Vec<String> = vec!["sprite".to_string()];
    if let Some(org) = sprite_org() {
        cmd.push("-o".to_string());
        cmd.push(org);
    }
    if let Some(name) = sprite_name {
        cmd.push("-s".to_string());
        cmd.push(normalize_den_name(name));
    }
    cmd.extend(args.iter().map(|s| s.to_string()));
    cmd
}

pub fn sprite_exec_command(name: &str, command: &[String]) -> Vec<String> {
    let mut base: Vec<&str> = vec!["exec", "--"];
    let refs: Vec<&str> = command.iter().map(String::as_str).collect();
    base.extend(refs);
    sprite_command(&base, Some(name))
}

pub fn sprite_tty_exec_command(name: &str, command: &[String]) -> Vec<String> {
    let mut base: Vec<&str> = vec!["exec", "--tty", "--"];
    let refs: Vec<&str> = command.iter().map(String::as_str).collect();
    base.extend(refs);
    sprite_command(&base, Some(name))
}

pub fn sprite_use_command(name: &str) -> Vec<String> {
    let mut cmd: Vec<String> = vec!["sprite".to_string()];
    if let Some(org) = sprite_org() {
        cmd.push("-o".to_string());
        cmd.push(org);
    }
    cmd.push("use".to_string());
    cmd.push(normalize_den_name(name));
    cmd
}

pub fn sprite_logs_command(name: &str, selector: Option<&str>, list_only: bool) -> Vec<String> {
    if list_only {
        return sprite_command(&["sessions", "list"], Some(name));
    }
    match selector {
        Some(sel) => sprite_command(&["attach", sel], Some(name)),
        None => sprite_command(&["attach"], Some(name)),
    }
}

pub fn sprite_checkpoint_create_command(name: &str, comment: &str) -> Vec<String> {
    sprite_command(&["checkpoint", "create", "--comment", comment], Some(name))
}

pub fn sprite_restore_command(name: &str, version_id: &str) -> Vec<String> {
    sprite_command(&["restore", version_id], Some(name))
}

pub fn make_sprite_redeploy_comment(name: &str, nonce: &str) -> String {
    format!("den-redeploy:{}:{}", normalize_den_name(name), nonce)
}
