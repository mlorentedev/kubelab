---
tags: [spec, tasks, templates]
created: "2026-10-14"
---

# Tasks - SEC-032-oidc-key-from-sops

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch `fix/oidc-signing-key-from-sops` from master
- [x] `proposal.md` complete; the Compose secret probe measured on the Mac

## Implementation

- [ ] [P] [AC1] Failing test: the dev stack binds no host pem, declares the env-sourced secret, and targets the path the template reads
- [ ] [AC1] Compose: secret replaces the bind mount
- [ ] [P] [AC2] Failing test: `generate_jwks` writes no file
- [ ] [AC2] Drop the pem write from `generate_jwks`, the CLI docstring and `JWKS_FILE_TEMPLATE`
- [ ] [P] [AC3] Failing guard: no host `oidc-jwks.pem` read or write in `toolkit/` or `infra/`
- [ ] [AC3] Drop the dead pem read and the unused `AUTHELIA_OIDC_JWKS_KEY` from `generator_authelia`
- [ ] [AC5] Runbooks fixed; lesson written
- [ ] [AC4] Live: dev stack `validate-config` with no pem; public-key fingerprint equals SOPS's

## Closing

- [ ] Every AC covered by a test or a recorded live run; `features.json` filled
- [ ] `make test-fast` green except the known macOS failures (TOOL-113)
- [ ] `verification.md` filled; draft PR with `## Knowledge`; triage; `## Review triage`
