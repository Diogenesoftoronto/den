//! Tailscale peer extraction.
//!
//! Port of `DenPeer` and `extract_den_peers` from `src/den_cli/core.py`.
//! Pure JSON transform — no I/O.

use serde_json::Value;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DenPeer {
    pub host_name: String,
    pub ip: String,
    pub online: bool,
}

pub fn extract_den_peers(status_payload: &Value) -> Vec<DenPeer> {
    let peers = match status_payload.get("Peer").and_then(|v| v.as_object()) {
        Some(obj) => obj,
        None => return vec![],
    };

    let mut result: Vec<DenPeer> = Vec::new();
    for raw_peer in peers.values() {
        let host_name = match raw_peer.get("HostName").and_then(|v| v.as_str()) {
            Some(name) if name.starts_with("den-") => name.to_string(),
            _ => continue,
        };

        let ip = raw_peer
            .get("TailscaleIPs")
            .and_then(|v| v.as_array())
            .and_then(|arr| arr.first())
            .and_then(|v| v.as_str())
            .unwrap_or("-")
            .to_string();

        let online = raw_peer
            .get("Online")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);

        result.push(DenPeer {
            host_name,
            ip,
            online,
        });
    }

    result.sort_by(|a, b| a.host_name.cmp(&b.host_name));
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn extract_den_peers_empty() {
        assert!(extract_den_peers(&json!({})).is_empty());
    }

    #[test]
    fn extract_den_peers_no_peer_key() {
        assert!(extract_den_peers(&json!({"other": "data"})).is_empty());
    }

    #[test]
    fn extract_den_peers_filters_non_den() {
        let payload = json!({
            "Peer": {
                "peer1": {"HostName": "laptop", "TailscaleIPs": ["10.0.0.1"], "Online": true},
                "peer2": {"HostName": "den-my-env", "TailscaleIPs": ["10.0.0.2"], "Online": true},
            }
        });
        let peers = extract_den_peers(&payload);
        assert_eq!(peers.len(), 1);
        assert_eq!(peers[0].host_name, "den-my-env");
        assert_eq!(peers[0].ip, "10.0.0.2");
    }

    #[test]
    fn extract_den_peers_sorted_by_name() {
        let payload = json!({
            "Peer": {
                "a": {"HostName": "den-zeta", "TailscaleIPs": ["10.0.0.3"], "Online": true},
                "b": {"HostName": "den-alpha", "TailscaleIPs": ["10.0.0.1"], "Online": false},
            }
        });
        let peers = extract_den_peers(&payload);
        assert_eq!(peers.len(), 2);
        assert_eq!(peers[0].host_name, "den-alpha");
        assert_eq!(peers[1].host_name, "den-zeta");
        assert!(!peers[0].online);
    }

    #[test]
    fn extract_den_peers_no_ip_defaults_to_dash() {
        let payload = json!({
            "Peer": {
                "a": {"HostName": "den-offline", "Online": false},
            }
        });
        let peers = extract_den_peers(&payload);
        assert_eq!(peers[0].ip, "-");
    }
}
