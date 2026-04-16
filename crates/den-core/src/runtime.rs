//! Runtime provider enum and CLI resolver helpers.
//!
//! Port of `RuntimeProvider` from `src/den_cli/core.py` and
//! `resolve_sesame_command` which resolves the sesame CLI binary.

use std::env;
use std::path::PathBuf;
use thiserror::Error;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuntimeProvider {
    Sprite,
    Railway,
}

impl std::fmt::Display for RuntimeProvider {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RuntimeProvider::Sprite => write!(f, "sprite"),
            RuntimeProvider::Railway => write!(f, "railway"),
        }
    }
}

#[cfg(feature = "cli")]
impl clap::ValueEnum for RuntimeProvider {
    fn value_variants<'a>() -> &'a [Self] {
        &[RuntimeProvider::Sprite, RuntimeProvider::Railway]
    }
    fn to_possible_value(&self) -> Option<clap::builder::PossibleValue> {
        match self {
            RuntimeProvider::Sprite => Some(clap::builder::PossibleValue::new("sprite")),
            RuntimeProvider::Railway => Some(clap::builder::PossibleValue::new("railway")),
        }
    }
}

#[derive(Debug, Error)]
pub enum SesameError {
    #[error("sesame executable not found")]
    NotFound,
}

pub fn resolve_sesame_command() -> Result<Vec<String>, SesameError> {
    if let Ok(env_bin) = env::var("DEN_SESAME_BIN") {
        let trimmed = env_bin.trim();
        if !trimmed.is_empty() && PathBuf::from(trimmed).exists() {
            return Ok(vec![trimmed.to_string()]);
        }
    }
    if let Ok(path) = which::which("sesame") {
        return Ok(vec![path.to_string_lossy().to_string()]);
    }
    if let Ok(home) = env::var("HOME") {
        for candidate in [
            PathBuf::from(&home).join("sesame/target/release/sesame"),
            PathBuf::from(&home).join("sesame/target/debug/sesame"),
        ] {
            if candidate.exists() {
                return Ok(vec![candidate.to_string_lossy().to_string()]);
            }
        }
    }
    Err(SesameError::NotFound)
}
