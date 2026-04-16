//! Den name normalization and Sprite-org resolution.
//!
//! Port of the `normalize_den_name`, `short_den_name`, and `sprite_org`
//! helpers in `src/den_cli/core.py`.

use std::env;

const PREFIX: &str = "den-";

pub fn normalize_den_name(name: &str) -> String {
    if name.starts_with(PREFIX) {
        name.to_string()
    } else {
        format!("{PREFIX}{name}")
    }
}

pub fn short_den_name(name: &str) -> String {
    name.strip_prefix(PREFIX).unwrap_or(name).to_string()
}

pub fn sprite_org() -> Option<String> {
    for key in ["DEN_SPRITE_ORG", "SPRITE_ORG"] {
        if let Ok(value) = env::var(key) {
            let trimmed = value.trim();
            if !trimmed.is_empty() {
                return Some(trimmed.to_string());
            }
        }
    }
    None
}
