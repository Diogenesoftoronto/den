//! den-core — pure logic ported from `src/den_cli/core.py`.
//!
//! No I/O lives here beyond filesystem probes in `project` and `runtime`.
//! Every function in this crate is either a pure data transform or a
//! command builder. The only async I/O lives in `sesame::cloudflare::CloudflareClient`.
//!
//! Domain types (DomainProvider, DomainMode, DomainMatch, DnsRecord,
//! DomainError) and domain functions (split_custom_domain,
//! resolve_custom_domain, sesame command builders, Cloudflare builders) are
//! provided by the `sesame` crate, which serves as the DNS SDK.

pub mod dhall;
pub mod fly;
pub mod names;
pub mod project;
pub mod railway;
pub mod runtime;
pub mod sprite;
pub mod sprite_parse;
pub mod tailscale;

#[cfg(feature = "io")]
pub mod porkbun;

pub use names::{normalize_den_name, short_den_name, sprite_org};
pub use sprite::{
    make_sprite_redeploy_comment, sprite_checkpoint_create_command, sprite_command,
    sprite_exec_command, sprite_logs_command, sprite_restore_command, sprite_tty_exec_command,
    sprite_use_command,
};
pub use sprite_parse::{
    find_checkpoint_version_in_api_output, find_checkpoint_version_in_list_output,
    parse_sprite_url, parse_sprite_url_info, SpriteUrlInfo,
};
pub use tailscale::{extract_den_peers, DenPeer};

// Re-export domain types and functions from sesame.
pub use sesame::domain::{
    build_sesame_dns_create_command, build_sesame_dns_edit_command, build_sesame_dns_list_command,
    build_sesame_url_forward_command, resolve_custom_domain, sesame_dns_records_exist,
    sesame_record_subdomain, split_custom_domain, DomainError, DomainMatch, DomainMode,
    DomainProvider, DnsRecord,
};

// Re-export Cloudflare pure functions from sesame.
pub use sesame::cloudflare::{
    build_cloudflare_dns_records, cloudflare_api_token, normalize_dns_name, parse_fly_dns_records,
    parse_railway_dns_records, CloudflareClient, UpsertResult,
};

// Re-export railway types and functions.
pub use railway::{
    extract_railway_linked_project_name, parse_railway_projects, parse_railway_service_statuses,
    railway_delete_command, railway_domain_attach_command, railway_list_command,
    railway_redeploy_command, railway_status_command, resolve_railway_command, RailwayError,
    RailwayProjectSummary, RailwayServiceStatusSummary,
};

// Re-export fly types and functions.
pub use fly::{
    fly_certs_add_command, fly_certs_check_command, fly_certs_setup_command,
    resolve_flyctl_command, FlyError,
};

// Re-export project types and functions.
pub use project::{
    detect_project_markers, infer_backend, infer_den_setup, infer_guix_packages,
    infer_nix_packages, infer_run_command, Backend, InferredDenSetup, InferredRunCommand,
    ProjectMarkers,
};

// Re-export runtime types and functions.
pub use runtime::{resolve_sesame_command, RuntimeProvider, SesameError};

// Re-export dhall rendering.
pub use dhall::render_den_dhall;
