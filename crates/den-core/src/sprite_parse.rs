//! Sprite URL parsing and checkpoint discovery.
//!
//! Port of `SpriteUrlInfo`, `parse_sprite_url`, `parse_sprite_url_info`,
//! `find_checkpoint_version_in_api_output`, `find_checkpoint_version_in_list_output`
//! from `src/den_cli/core.py`. All functions are pure string/JSON transforms.

use serde_json::Value;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SpriteUrlInfo {
    pub url: Option<String>,
    pub auth: Option<String>,
}

pub fn parse_sprite_url(output: &str) -> Option<String> {
    parse_sprite_url_info(output).url
}

pub fn parse_sprite_url_info(output: &str) -> SpriteUrlInfo {
    let mut url = None;
    let mut auth = None;
    for line in output.lines() {
        if let Some(rest) = line.strip_prefix("URL:") {
            let candidate: &str = rest.trim();
            if !candidate.is_empty()
                && candidate.contains("://")
                && candidate.contains('.')
            {
                url = Some(candidate.to_string());
            }
        } else if let Some(rest) = line.strip_prefix("Auth:") {
            let val: &str = rest.trim();
            auth = if val.is_empty() { None } else { Some(val.to_string()) };
        }
    }
    SpriteUrlInfo { url, auth }
}

pub fn find_checkpoint_version_in_api_output(output: &str, comment: &str) -> Option<String> {
    let payload: Value = serde_json::from_str(output).ok()?;
    for record in iter_checkpoint_records(&payload) {
        let record_comment = record.get("comment").and_then(|v| v.as_str());
        if record_comment != Some(comment) {
            continue;
        }
        for key in ["id", "version", "version_id", "checkpoint_id"] {
            if let Some(value) = record.get(key).and_then(|v| v.as_str()) {
                if !value.is_empty() {
                    return Some(value.to_string());
                }
            }
        }
    }
    None
}

fn iter_checkpoint_records(payload: &Value) -> Vec<&Value> {
    let mut records = Vec::new();
    collect_checkpoint_records(payload, &mut records);
    records
}

fn collect_checkpoint_records<'a>(payload: &'a Value, records: &mut Vec<&'a Value>) {
    match payload {
        Value::Object(map) => {
            records.push(payload);
            for key in ["checkpoints", "items", "data", "results"] {
                if let Some(nested) = map.get(key) {
                    if let Some(arr) = nested.as_array() {
                        for entry in arr {
                            collect_checkpoint_records(entry, records);
                        }
                    }
                }
            }
        }
        Value::Array(arr) => {
            for entry in arr {
                if entry.is_object() {
                    collect_checkpoint_records(entry, records);
                }
            }
        }
        _ => {}
    }
}

pub fn find_checkpoint_version_in_list_output(output: &str, comment: &str) -> Option<String> {
    for line in output.lines() {
        let stripped: &str = line.trim();
        if !stripped.contains(comment) {
            continue;
        }
        if let Some(first) = stripped.split_whitespace().next() {
            return Some(first.to_string());
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_sprite_url_extracts_url() {
        let output = "URL: https://my-den.example.com\nAuth: google";
        assert_eq!(
            parse_sprite_url(output),
            Some("https://my-den.example.com".to_string())
        );
    }

    #[test]
    fn parse_sprite_url_info_extracts_both() {
        let output = "URL: https://my-den.example.com\nAuth: google";
        let info = parse_sprite_url_info(output);
        assert_eq!(info.url, Some("https://my-den.example.com".to_string()));
        assert_eq!(info.auth, Some("google".to_string()));
    }

    #[test]
    fn parse_sprite_url_info_no_auth() {
        let output = "URL: https://my-den.example.com\nAuth:";
        let info = parse_sprite_url_info(output);
        assert_eq!(info.url, Some("https://my-den.example.com".to_string()));
        assert_eq!(info.auth, None);
    }

    #[test]
    fn parse_sprite_url_info_empty() {
        let info = parse_sprite_url_info("no url here");
        assert!(info.url.is_none());
        assert!(info.auth.is_none());
    }

    #[test]
    fn find_checkpoint_in_api_output() {
        let output = r#"{"checkpoints": [{"comment": "den-redeploy:my-den:abc", "id": "cp-123"}]}"#;
        assert_eq!(
            find_checkpoint_version_in_api_output(output, "den-redeploy:my-den:abc"),
            Some("cp-123".to_string())
        );
    }

    #[test]
    fn find_checkpoint_in_api_output_no_match() {
        let output = r#"{"checkpoints": [{"comment": "other", "id": "cp-123"}]}"#;
        assert_eq!(
            find_checkpoint_version_in_api_output(output, "den-redeploy:my-den:abc"),
            None
        );
    }

    #[test]
    fn find_checkpoint_in_api_output_invalid_json() {
        assert_eq!(
            find_checkpoint_version_in_api_output("not json", "any"),
            None
        );
    }

    #[test]
    fn find_checkpoint_in_list_output() {
        let output = "cp-456  2024-01-15  den-redeploy:my-den:abc";
        assert_eq!(
            find_checkpoint_version_in_list_output(output, "den-redeploy:my-den:abc"),
            Some("cp-456".to_string())
        );
    }

    #[test]
    fn find_checkpoint_in_list_output_no_match() {
        let output = "cp-456  2024-01-15  other-comment";
        assert_eq!(
            find_checkpoint_version_in_list_output(output, "den-redeploy:my-den:abc"),
            None
        );
    }
}
