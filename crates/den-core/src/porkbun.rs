//! Sesame config loading and Porkbun API client.
//!
//! Port of `_load_porkbun_creds`, `_porkbun_api`, `porkbun_add_url_forward`,
//! `porkbun_upsert_dns_records`, and `discover_porkbun_domains_from_sesame_config`
//! from `src/den_cli/core.py`. These functions perform actual I/O (HTTP, config
//! file reads) and require tokio runtime.

use crate::{resolve_custom_domain, DomainProvider, DnsRecord, DomainError};
use serde::Deserialize;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum PorkbunError {
    #[error("sesame config not found at {0}")]
    ConfigNotFound(String),
    #[error("sesame config is missing default_profile or profiles")]
    ConfigMissingProfile,
    #[error("sesame config profile {0:?} not found")]
    ConfigProfileNotFound(String),
    #[error("sesame config is missing api_key or secret_api_key")]
    ConfigMissingCredentials,
    #[error("Porkbun API error: {0}")]
    ApiError(String),
    #[error("request failed: {0}")]
    RequestFailed(#[from] reqwest::Error),
    #[error("invalid response: {0}")]
    InvalidResponse(String),
    #[error("domain resolution failed")]
    DomainResolution(#[from] DomainError),
}

#[derive(Debug, Clone)]
pub struct PorkbunCreds {
    pub api_key: String,
    pub secret_api_key: String,
    pub base_url: String,
}

#[derive(Debug, Deserialize)]
struct SesameConfig {
    default_profile: Option<String>,
    profiles: Option<HashMap<String, SesameProfile>>,
}

#[derive(Debug, Deserialize)]
struct SesameProfile {
    api_key: Option<String>,
    secret_api_key: Option<String>,
    base_url: Option<String>,
}

pub fn load_porkbun_creds(config_path: Option<&Path>) -> Result<PorkbunCreds, PorkbunError> {
    let path = config_path
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| {
            dirs_home_dir()
                .unwrap_or_else(|| PathBuf::from("/"))
                .join(".config/sesame/config.toml")
        });

    if !path.exists() {
        return Err(PorkbunError::ConfigNotFound(path.to_string_lossy().to_string()));
    }

    let content = std::fs::read_to_string(&path)
        .map_err(|e| PorkbunError::ConfigNotFound(format!("{}: {e}", path.display())))?;
    let config: SesameConfig = toml::from_str(&content)
        .map_err(|e| PorkbunError::InvalidResponse(format!("config parse: {e}")))?;

    let profile_name = config
        .default_profile
        .ok_or(PorkbunError::ConfigMissingProfile)?;
    let profiles = config
        .profiles
        .ok_or(PorkbunError::ConfigMissingProfile)?;
    let profile = profiles
        .get(&profile_name)
        .ok_or_else(|| PorkbunError::ConfigProfileNotFound(profile_name.clone()))?;

    let api_key = profile
        .api_key
        .clone()
        .ok_or(PorkbunError::ConfigMissingCredentials)?;
    let secret_api_key = profile
        .secret_api_key
        .clone()
        .ok_or(PorkbunError::ConfigMissingCredentials)?;
    let base_url = profile
        .base_url
        .clone()
        .unwrap_or_else(|| "https://api.porkbun.com/api/json/v3".to_string());

    Ok(PorkbunCreds {
        api_key,
        secret_api_key,
        base_url,
    })
}

fn dirs_home_dir() -> Option<PathBuf> {
    std::env::var("HOME").ok().map(PathBuf::from)
}

async fn porkbun_api(
    client: &reqwest::Client,
    base_url: &str,
    path: &str,
    api_key: &str,
    secret_api_key: &str,
    extra: Option<&HashMap<String, serde_json::Value>>,
) -> Result<serde_json::Value, PorkbunError> {
    let mut payload: HashMap<String, serde_json::Value> = HashMap::new();
    payload.insert(
        "apikey".to_string(),
        serde_json::Value::String(api_key.to_string()),
    );
    payload.insert(
        "secretapikey".to_string(),
        serde_json::Value::String(secret_api_key.to_string()),
    );
    if let Some(extra_map) = extra {
        for (k, v) in extra_map {
            payload.insert(k.clone(), v.clone());
        }
    }

    let url = format!(
        "{}/{}",
        base_url.trim_end_matches('/'),
        path.trim_start_matches('/')
    );
    let resp = client
        .post(&url)
        .json(&payload)
        .timeout(std::time::Duration::from_secs(30))
        .send()
        .await?;

    let body: serde_json::Value = resp.json().await?;
    let obj = body
        .as_object()
        .ok_or_else(|| PorkbunError::InvalidResponse("not a JSON object".to_string()))?;

    if obj.get("status").and_then(|v| v.as_str()) != Some("SUCCESS") {
        let msg = obj
            .get("message")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown error");
        return Err(PorkbunError::ApiError(msg.to_string()));
    }
    Ok(body)
}

pub async fn porkbun_add_url_forward(
    client: &reqwest::Client,
    custom_domain: &str,
    target_url: &str,
    owned_domains: &[String],
    config_path: Option<&Path>,
) -> Result<(), PorkbunError> {
    let mut provider_domains = HashMap::new();
    provider_domains.insert(DomainProvider::Sesame, owned_domains.to_vec());
    let m = resolve_custom_domain(custom_domain, &provider_domains)?;

    let creds = load_porkbun_creds(config_path)?;
    let subdomain = m.subdomain.unwrap_or_default();

    let mut extra = HashMap::new();
    extra.insert(
        "subdomain".to_string(),
        serde_json::Value::String(subdomain),
    );
    extra.insert(
        "location".to_string(),
        serde_json::Value::String(target_url.to_string()),
    );
    extra.insert(
        "type".to_string(),
        serde_json::Value::String("permanent".to_string()),
    );
    extra.insert(
        "includePath".to_string(),
        serde_json::Value::String("yes".to_string()),
    );
    extra.insert(
        "wildcard".to_string(),
        serde_json::Value::String("no".to_string()),
    );

    porkbun_api(
        client,
        &creds.base_url,
        &format!("domain/addUrlForward/{}", m.zone),
        &creds.api_key,
        &creds.secret_api_key,
        Some(&extra),
    )
    .await?;
    Ok(())
}

pub async fn porkbun_upsert_dns_records(
    client: &reqwest::Client,
    zone: &str,
    records: &[DnsRecord],
    config_path: Option<&Path>,
) -> Result<Vec<(String, DnsRecord)>, PorkbunError> {
    let creds = load_porkbun_creds(config_path)?;
    let mut applied: Vec<(String, DnsRecord)> = Vec::new();

    for record in records {
        let subdomain = if record.name == "@" || record.name.is_empty() {
            None
        } else {
            Some(record.name.as_str())
        };
        let subdomain_path = subdomain.unwrap_or("");

        let retrieve_path = format!(
            "dns/retrieveByNameType/{}/{}/{}",
            zone, record.record_type, subdomain_path
        );
        let retrieve_result = porkbun_api(
            client,
            &creds.base_url,
            &retrieve_path,
            &creds.api_key,
            &creds.secret_api_key,
            None,
        )
        .await?;

        let existing = retrieve_result.get("records").and_then(|v| v.as_array());
        let has_records = existing.map_or(false, |arr| !arr.is_empty());

        if has_records {
            let edit_path = format!(
                "dns/editByNameType/{}/{}/{}",
                zone, record.record_type, subdomain_path
            );
            let mut extra = HashMap::new();
            extra.insert(
                "content".to_string(),
                serde_json::Value::String(record.content.clone()),
            );
            extra.insert(
                "ttl".to_string(),
                serde_json::Value::String("300".to_string()),
            );
            porkbun_api(
                client,
                &creds.base_url,
                &edit_path,
                &creds.api_key,
                &creds.secret_api_key,
                Some(&extra),
            )
            .await?;
            applied.push(("updated".to_string(), record.clone()));
        } else {
            let mut extra = HashMap::new();
            extra.insert(
                "name".to_string(),
                serde_json::Value::String(subdomain_path.to_string()),
            );
            extra.insert(
                "type".to_string(),
                serde_json::Value::String(record.record_type.clone()),
            );
            extra.insert(
                "content".to_string(),
                serde_json::Value::String(record.content.clone()),
            );
            extra.insert(
                "ttl".to_string(),
                serde_json::Value::String("300".to_string()),
            );
            porkbun_api(
                client,
                &creds.base_url,
                &format!("dns/create/{zone}"),
                &creds.api_key,
                &creds.secret_api_key,
                Some(&extra),
            )
            .await?;
            applied.push(("created".to_string(), record.clone()));
        }
    }
    Ok(applied)
}

pub async fn discover_porkbun_domains_from_sesame_config(
    client: &reqwest::Client,
    config_path: Option<&Path>,
) -> Result<Vec<String>, PorkbunError> {
    let creds = match load_porkbun_creds(config_path) {
        Ok(c) => c,
        Err(_) => return Ok(vec![]),
    };

    let mut extra = HashMap::new();
    extra.insert(
        "start".to_string(),
        serde_json::Value::Number(0.into()),
    );
    extra.insert(
        "includeLabels".to_string(),
        serde_json::Value::String("yes".to_string()),
    );

    let result = match porkbun_api(
        client,
        &creds.base_url,
        "domain/listAll",
        &creds.api_key,
        &creds.secret_api_key,
        Some(&extra),
    )
    .await
    {
        Ok(r) => r,
        Err(_) => return Ok(vec![]),
    };

    let domains_arr = match result.get("domains").and_then(|v| v.as_array()) {
        Some(arr) => arr,
        None => return Ok(vec![]),
    };

    let mut domains: Vec<String> = Vec::new();
    for row in domains_arr {
        if let Some(domain) = row.get("domain").and_then(|v| v.as_str()) {
            if !domain.is_empty() {
                domains.push(domain.to_string());
            }
        }
    }
    Ok(domains)
}
