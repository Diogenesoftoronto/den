use den_cli::assets::{locate_or_materialize_assets, materialize_assets_into};
use std::path::PathBuf;
use std::process::Command;
use std::sync::{Mutex, OnceLock};
use std::{env, fs};

fn env_lock() -> &'static Mutex<()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
}

fn lock_env() -> std::sync::MutexGuard<'static, ()> {
    match env_lock().lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    }
}

fn temp_dir(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("den-cli-test-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    dir
}

#[test]
fn asset_root_env_override_is_used_when_valid() {
    let _guard = lock_env();
    let root = temp_dir("asset-root-override");
    fs::create_dir_all(root.join("dhall")).unwrap();
    fs::create_dir_all(root.join("scripts")).unwrap();
    fs::create_dir_all(root.join("guix")).unwrap();
    fs::write(root.join("dhall").join("Types.dhall"), "let x = 1").unwrap();
    fs::write(
        root.join("scripts").join("generate-from-dhall.sh"),
        "#!/usr/bin/env bash\n",
    )
    .unwrap();
    fs::write(root.join("guix").join("manifest.scm"), ";; test").unwrap();

    let prev_root = env::var_os("DEN_ASSET_ROOT");
    let prev_cache = env::var_os("DEN_ASSET_CACHE_DIR");
    env::set_var("DEN_ASSET_ROOT", &root);
    env::set_var("DEN_ASSET_CACHE_DIR", temp_dir("unused-cache"));

    let located = locate_or_materialize_assets().unwrap();
    assert_eq!(located.root, root);

    match prev_root {
        Some(v) => env::set_var("DEN_ASSET_ROOT", v),
        None => env::remove_var("DEN_ASSET_ROOT"),
    }
    match prev_cache {
        Some(v) => env::set_var("DEN_ASSET_CACHE_DIR", v),
        None => env::remove_var("DEN_ASSET_CACHE_DIR"),
    }
}

#[test]
fn bundled_assets_materialize_into_cache_dir() {
    let _guard = lock_env();
    let cache = temp_dir("materialized-cache");
    let located = materialize_assets_into(&cache).unwrap();
    assert_eq!(located.root, cache);
    assert!(located.dhall_dir.join("Types.dhall").is_file());
    assert!(located.scripts_dir.join("generate-from-dhall.sh").is_file());
    assert!(located.guix_dir.join("manifest.scm").is_file());
}

fn help_output(args: &[&str]) -> String {
    let output = Command::new(env!("CARGO_BIN_EXE_den"))
        .args(args)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8_lossy(&output.stdout).to_string()
}

fn command_output(args: &[&str], extra_path_prefix: Option<&PathBuf>) -> std::process::Output {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_den"));
    cmd.args(args);
    if let Some(prefix) = extra_path_prefix {
        let existing =
            env::split_paths(&env::var_os("PATH").unwrap_or_default()).collect::<Vec<_>>();
        let mut paths = vec![prefix.clone()];
        paths.extend(existing);
        cmd.env("PATH", env::join_paths(paths).unwrap());
    }
    cmd.output().unwrap()
}

#[test]
fn setup_help_exposes_documented_flags() {
    let output = help_output(&["setup", "--help"]);
    assert!(output.contains("--force"));
    assert!(output.contains("--print"));
}

#[test]
fn deploy_help_exposes_documented_flags() {
    let output = help_output(&["deploy", "--help"]);
    assert!(output.contains("--no-run"));
    assert!(output.contains("--runtime"));
    assert!(output.contains("--name"));
}

#[test]
fn domain_help_exposes_runtime_and_mode_flags() {
    let output = help_output(&["domain", "--help"]);
    assert!(output.contains("--runtime"));
    assert!(output.contains("--mode"));
    assert!(output.contains("--proxied"));
}

#[test]
fn doctor_help_exposes_install_check_flags() {
    let output = help_output(&["doctor", "--help"]);
    assert!(output.contains("--json"));
    assert!(output.contains("--verify-auth"));
}

#[test]
fn doctor_json_succeeds_when_binary_directory_is_on_path() {
    let exe = PathBuf::from(env!("CARGO_BIN_EXE_den"));
    let bin_dir = exe.parent().unwrap().to_path_buf();
    let output = command_output(&["doctor", "--json"], Some(&bin_dir));
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    let payload: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(payload.get("ok").and_then(|v| v.as_bool()), Some(true));
    assert!(payload.get("checks").and_then(|v| v.as_array()).is_some());
}
