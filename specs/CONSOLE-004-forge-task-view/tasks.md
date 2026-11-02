---
tags: [spec, tasks, templates]
created: "2026-10-21"
---

# Tasks - CONSOLE-004-forge-task-view

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [ ] Branch created from master: `feat/CONSOLE-004-forge-task-view`
- [ ] `proposal.md` is complete and acceptance criteria are testable
- [ ] No open questions left in `proposal.md` "Risks / open questions"

## Decisions before code

- [x] ✓ 2026-10-22 UI is served from the `apps/api` binary (ADR-057 D2; Authelia already fronts the route). The ADR corrections to A2 and A8 are in #2623
- [x] ✓ 2026-10-22 Label set lives at `infra.forge.labels` (ADR-036: read by more than one component), shared with CONSOLE-006 (#2588), with an `area_repos` map and `fallback: knowledge`
- [x] ✓ 2026-10-22 GitHub is read with a GitHub App installation token (its own rate pool, not shared with a user PAT); the ceiling is 1000 calls per hour, a conservative start to tighten after measurement
- [x] ✓ 2026-10-22 Reconcile runs every 10 minutes per source and the alert fires when a source has not been read for 20 minutes. The period and the bound are one decision: `as_of` only advances on a successful read, so a bound shorter than the period would fire every cycle
- [x] ✓ 2026-10-22 End-to-end bound is 60 seconds from a forge event to the queue, generous and to be tightened after measurement. The e2e command must drive the webhook path, since reconcile would hide a missed webhook inside that window

## Implementation

> Slices are PR-sized and ship in this order: read queue (1, 2), writes (3), operations (4, 5), end to end (6). Each slice is a draft PR until reviewers have run.

### 1. Read model and adapters

- [ ] [P] [AC1] Contract tests for one read-adapter interface against recorded GitHub and Gitea responses
  - [x] ✓ 2026-10-22 Reader interface, unreachable-source error and the contract runner, with the recorded GitHub fixture (#2635)
  - [x] ✓ 2026-10-22 Gitea fixture (shape recorded from the live forge, values neutralised by hand) run through the same contract
  - [x] ✓ 2026-10-22 Pin the request in the contract: path and query are asserted per forge, mutation-proven (PR-Agent finding on #2635)
  - [x] ✓ 2026-10-22 Forge-neutral contract: expected items and counts are parameters (PR-Agent finding on #2635)
- [ ] [AC1] Atlas migration in the `infra.postgres` tenant: items, event table, per-source `as_of` and reachability
- [ ] [AC1] Implement the Gitea and GitHub adapters to make the contract tests pass
  - [x] ✓ 2026-10-22 GitHub adapter: pagination, `since`, token only when set and never sent to another host (#2635)
  - [x] ✓ 2026-10-22 Gitea adapter: issues and pull requests are two listings, either failing fails the read
  - [x] ✓ 2026-11-01 A `read:issue` credential for the Gitea reader of its own: `issue_reader_token`, a third token on the reviewer's account (no new account), minted by `beelink_services` provisioning from `token_scopes.issue_reader`, catalogued, rotatable with `make gitea-rotate-token TOKEN=issue_reader`. No expiry is recorded because Gitea's token API has no expiry field (as `bot_token`). The token exists only after `make provision NODE=bee ENV=prod TAGS=gitea` runs
  - [x] ✓ 2026-11-01 [AC4] Deliver `issue_reader_token` to the API: `FORGE_GITEA_TOKEN` in `api-secrets` (optional, since staging has no Gitea token and the API starts without it), read by `config.Forge`, with `tests/test_forge_credentials_delivery.py` pinning that no credential lands in a ConfigMap. No NetworkPolicy is needed: NET-002 is ingress-only and the API is the caller, so egress is not restricted
  - [ ] [AC4] Measure the grant: the first live read of an issue list with `type=pulls` confirms `read:issue` alone suffices; a 403 widens `token_scopes.issue_reader` deliberately, with `ISSUE_READER_SCOPES`
  - [ ] [AC4] The webhook receiver's host must pass Gitea's `ALLOWED_HOST_LIST`: Gitea 1.27.3 refuses to deliver to a host that resolves to a Tailscale address (100.64.0.2), as the PR-Agent hook found (lane `fix-gitea-webhook-allowed-host`). Decide the receiver's address against that list before the receiver is built
- [ ] [AC1] Regression test: a source that is down renders unreachable with its last read time, never empty
- [ ] [P] [AC4] Webhook receiver: reject an invalid HMAC, store the event before projecting it
  - [x] ✓ 2026-10-22 Signature verification for both forges, GitHub `sha256=` prefix and Gitea bare hex (#2636)
  - [ ] Receiver endpoint and the event store
- [ ] [AC4] Test: the same delivery twice projects once
- [ ] [AC4] Periodic reconcile per source every 10 minutes under the hourly call ceiling, with a guard test that counts calls
- [ ] [AC1] Queue endpoint with the inbox reason (author, requested reviewer, failing CI, waiting on me)

### 2. Access and UI

- [ ] [AC3] Authelia in front of the route; 401 without a credential
- [ ] [AC3] Machine token in SOPS and `SECRET_CATALOG`, accepted on the create write only; test that every other route refuses it
- [ ] [AC1] Queue page, with each source's freshness visible

### 3. Narrow writes

- [ ] [AC2] Outbox with an idempotency key; a write is pending until the forge confirms
- [ ] [AC2] Create (repository chosen by `area:`, `knowledge` fallback), label, assign, close and reopen
- [ ] [AC2] Test that no merge, review or reviewer-request route exists
- [ ] [AC2] Audit row for every write

### 4. Observability

- [ ] [P] [AC6] Structured log events for freshness, webhook failures, reconcile duration and outbox depth, through Vector to Loki
- [ ] [AC6] Read-only Postgres role on a counts-only view, a Grafana datasource, and the dashboard (throughput, queue age, time to first review, time with a red CI, items by status, priority and area)
- [ ] [AC6] The datasource credential reaches Grafana through a Secret (`secureJsonData`, read from env or file), never the plain `grafana-datasources` ConfigMap, and a change to it restarts Grafana (generated name or explicit restart)
- [ ] [AC6] Grafana alert for a source not read within the declared bound
- [ ] [AC6] NetworkPolicy rule for Grafana to Postgres (NET-002) and the dashboard shown with no private titles

### 5. Operations

- [ ] [P] [AC7] Declare the read model in the Postgres backup coverage and rehearse one restore
- [ ] [AC7] Test that the read model rebuilds from the forges alone
- [x] ✓ 2026-11-01 [AC4] [AC7] Create the GitHub App for the read adapter, store its credential in SOPS with a catalog entry (App `kubelab-console`, App ID 5573076, installed on `mlorentedev/kubelab` only as installation 177667607; Issues, Pull requests and Metadata read-only, webhooks off; private key at `apps.services.core.github_app.private_key` in `common.enc.yaml`; GitHub App keys carry no expiry, so the catalog entry is `Expiry.NEVER`)
- [x] ✓ 2026-11-01 [AC4] Deliver the App ID, installation ID and private key to the API: the two IDs at `infra.forge.github.*` reach the ConfigMap as `INFRA_FORGE_GITHUB_APP_ID` and `INFRA_FORGE_GITHUB_INSTALLATION_ID`; the key reaches `api-secrets` as `FORGE_GITHUB_PRIVATE_KEY`
- [ ] [AC4] Mint an installation token from the App ID, installation ID and key (JWT signed with the key, exchanged at `/app/installations/{id}/access_tokens`, cached until shortly before it expires), then read once to measure the App's grant. Needs the image deployed, so it runs after promotion
- [ ] [AC7] Runbook: rebuild, restore, rotate tokens; token expiry dates in the SOPS catalog

### 6. End to end

- [ ] [AC5] Probe target: an issue opened on Gitea and on GitHub appears in the queue within the bound, and a `status:*` label added from the queue is read back from the forge
- [ ] Hand CONSOLE-007 (#2586) the create write and its token; its own probe covers Slack

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/CONSOLE-004-forge-task-view/features.json`):

```json
[
  {
    "id": "CONSOLE-004-forge-task-view-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
