# Self-Hosted Runtime

This document describes how `den` can reduce dependence on proprietary runtime providers while keeping the current CLI workflows intact.

The aim is not to replicate every provider feature immediately. The aim is to define an open runtime path that covers the workflows users actually need:

- create a den
- sync a repository
- expose a service
- attach a domain
- reconnect later
- preserve or restore useful state

## Why

Today the canonical Rust CLI can drive runtime providers that we do not control.

That creates three concrete risks:

- provider outages or auth failures break otherwise-correct `den` workflows
- lifecycle semantics are inherited from third-party CLIs
- persistence, ingress, and pricing become policy decisions outside the project

An open runtime path reduces those risks and makes `den` a real environment tool rather than a thin provider wrapper.

## Design Principles

- Rust remains canonical.
- The runtime contract should be smaller than any one provider API.
- Self-hosted does not need full parity immediately to be useful.
- Compute, ingress, and persistence should stay swappable.
- Telemetry must remain optional and local-first.

## Runtime Contract

`den` should target a provider abstraction based on the operations the CLI already exposes.

Required operations:

- `create(name, backend, resources) -> runtime_handle`
- `destroy(name)`
- `status(name) -> runtime_status`
- `sync(name, project_path)`
- `exec(name, argv)`
- `public_url(name) -> Option<Url>`
- `attach_domain(name, host, mode, options)`

Strongly preferred operations:

- `logs(name)`
- `redeploy(name)`
- `resume(name)`

Longer-term operations:

- `snapshot(name) -> snapshot_ref`
- `restore(name, snapshot_ref)`
- `volume_export(name)`

The key point is that `den` should dispatch through a runtime interface instead of scattering Sprite or Railway assumptions across the workflow code.

## Recommended First Open Stack

The first serious self-hosted runtime should optimize for compatibility and operability.

Recommended stack:

- compute: Firecracker or KVM-backed microVMs
- image/build: OCI images or Nix/Guix-produced root filesystems
- persistence: writable volumes plus S3-compatible object storage for exports and snapshots
- ingress: self-hosted `zrok`
- control plane: a small `den` runtime service or local agent

This is a better first target than jumping directly to unikernels because development environments need:

- arbitrary Linux userspace
- mutable filesystems
- shell access
- broad toolchain compatibility
- predictable process behavior

Those constraints fit microVMs well.

## Where Unikraft Fits

`Unikraft` is still worth pursuing, but it should be treated as a later runtime substrate, not the first universal replacement for general-purpose dens.

It is a good candidate for:

- service-oriented dens
- specialized agents
- narrow workloads with fast boot requirements
- public applications with constrained dependency sets

It is a weaker first target for:

- interactive shell-heavy development sessions
- broad language toolchains
- long-lived mutable workspaces

The pragmatic sequencing is:

- build `runtime=selfhosted` first on microVMs
- treat `runtime=unikraft` as an experimental provider once the interface is stable

## Storage Model

Storage should separate three concerns:

- immutable environment assets
- mutable workspace state
- exported snapshots

Recommended model:

1. Immutable base image
   - produced from Nix, Guix, or OCI inputs
   - content-addressed

2. Mutable workspace volume
   - writable filesystem for repo contents, caches, and editor state

3. Snapshot and export artifacts
   - stored in S3-compatible object storage
   - used for backup, migration, and optional restore

This gives `den` a useful persistence model without requiring vendor-native checkpoint and restore on the first release.

## Networking Model

`zrok` is a strong fit for ingress and sharing.

Use it for:

- public HTTP exposure
- private shares
- stable externally reachable endpoints

Do not treat `zrok` as the runtime scheduler. It handles ingress, not workload lifecycle.

The self-hosted runtime still needs its own answers for:

- workload placement
- health
- exec access
- logs
- service discovery

## Domain Model

The current Rust CLI already has a useful domain abstraction:

- ownership-based provider selection
- DNS attachment vs forward mode
- Cloudflare and sesame/Porkbun support

The self-hosted runtime should preserve that interface.

Expected behavior:

- `den domain myapp den.example.com --runtime selfhosted`
- resolve domain ownership the same way current providers do
- attach DNS directly if the runtime exposes a stable public endpoint
- otherwise require explicit forward mode

That keeps custom-domain behavior consistent across providers.

## Telemetry Posture

Removing infrastructure dependency should not introduce surveillance dependency.

Telemetry for self-hosted runtime work should follow these rules:

- disabled by default
- explicitly opt-in
- functional with no network access
- local event log first
- redacted, coarse-grained, and non-blocking if export is ever added

Useful event classes, if enabled:

- selected runtime provider
- create, sync, deploy success or failure
- duration buckets
- auth check outcome class
- snapshot success or failure

Events that should not be collected:

- repository contents
- shell history
- command arguments that may contain secrets
- domain values unless the user explicitly opts into diagnostic export

See also [telemetry.md](/home/diogenes/Projects/den/docs/telemetry.md).

## Rollout Plan

### Phase 1: Provider Interface

- define a runtime trait or equivalent abstraction in Rust
- route existing Sprite and Railway logic through it

Exit criteria:

- `spawn`, `deploy`, `status`, `destroy`, `redeploy`, and `domain` dispatch through one shared interface

### Phase 2: Self-Hosted MVP

- implement `runtime=selfhosted`
- provision a microVM or container on infrastructure we control
- support repo sync
- support public URLs through `zrok`
- support `status`, `destroy`, and `logs`

Exit criteria:

- a user can deploy a simple web app or static site without Sprite or Railway

### Phase 3: Durable Workspace

- add writable volumes
- support reconnecting to existing dens
- add export and import of workspace state

Exit criteria:

- a user can treat the self-hosted runtime as a durable workstation

### Phase 4: Snapshot and Restore

- add snapshot metadata and restore workflows
- back exports with S3-compatible object storage

Exit criteria:

- a den can be recreated from a known snapshot with bounded data loss

### Phase 5: Experimental Unikraft Track

- add a distinct `runtime=unikraft`
- document workload constraints clearly
- focus on service workloads before shell-heavy interactive sessions

Exit criteria:

- selected workloads can run faster or cheaper than the generic self-hosted path

## Non-Goals

- exact behavioral emulation of Sprite internals
- mandatory checkpoint and restore in the first self-hosted release
- replacing every current provider before the self-hosted path becomes useful
- centralized telemetry as part of the MVP

## Immediate Next Steps

1. Define the runtime interface in `den-core`.
2. Move existing providers behind that interface.
3. Add `selfhosted` as a recognized runtime value before wiring behavior.
4. Build an MVP provider around microVMs plus `zrok`.
5. Keep Unikraft on a separate experimental track until interactive workflow constraints are clear.
