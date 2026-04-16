# Telemetry

This document describes a telemetry posture for `den`. It is a design constraint, not an implementation commitment.

## Position

- Telemetry should be disabled by default.
- Any future telemetry should be explicitly opt-in.
- `den` should remain fully usable with telemetry disabled.
- Local logs and deterministic command output matter more than product analytics.

## Goals

- Understand which workflows are failing most often.
- Detect install and environment breakage that `den doctor` can surface.
- Measure command latency and external dependency failure rates.
- Improve workflow design without collecting repository contents or command payloads.

## Non-goals

- No collection of source code.
- No collection of command arguments that may contain secrets or private paths.
- No keystroke/session replay.
- No default network egress for telemetry.

## Safe Event Model

If telemetry is implemented later, events should be coarse and structured:

- command name
- high-level outcome: success or failure
- duration bucket
- runtime provider: sprite or railway
- backend: nix or guix when known
- error class: auth, missing_dependency, parse_error, network, timeout
- `den doctor` summary counts

Events should not include:

- repository path
- custom domain values
- command override payloads
- environment variable values
- file contents
- stdout or stderr bodies

## Local-First Approach

Before any remote telemetry exists, `den` should prefer local observability:

- `den doctor` for install/runtime checks
- structured command errors
- optional local debug logs behind an explicit env var

If remote telemetry is ever added, a local log sink should exist first so the same event schema can be inspected without network transport.

## Consent Model

Recommended controls:

- `DEN_TELEMETRY=0|1`
- `den telemetry status`
- `den telemetry enable`
- `den telemetry disable`

The default should be equivalent to `DEN_TELEMETRY=0`.

## Identity

If opt-in telemetry is added, identity should be minimal:

- generate a random local installation ID
- store it on disk
- allow rotation and deletion
- never derive identity from repo contents, usernames, or provider account names

## Transport Constraints

Any future transport should:

- batch events
- retry conservatively
- drop on failure rather than blocking commands
- use HTTPS
- have a documented endpoint and schema

## Rollout Guardrails

Telemetry should only ship if all of the following are true:

- documented in the repo
- disabled by default
- easy to inspect locally
- easy to disable permanently
- covered by tests for redaction and opt-in behavior

## Near-Term Recommendation

Do not implement remote telemetry yet.

The right immediate investment is:

1. keep improving `den doctor`
2. add more structured local diagnostics
3. stabilize the canonical Rust workflows

That gives most of the operational value without introducing a privacy or trust regression.
