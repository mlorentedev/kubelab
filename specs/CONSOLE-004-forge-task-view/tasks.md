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

- [x] ✓ 2026-10-22 UI is served from the `apps/api` binary (ADR-057 D2). Corrected 2026-11-04: Authelia did not front `api.kubelab.live`, whose rule is `bypass`; the console got a host of its own instead. The ADR corrections to A2 and A8 are in #2623. Amended 2026-11-05 by ADR-074 D1: the backend stays in `apps/api`, and the frontend becomes `apps/console`, so the page served from the binary is transitional
- [x] ✓ 2026-10-22 Label set lives at `infra.forge.labels` (ADR-036: read by more than one component), shared with CONSOLE-006 (#2588), with an `area_repos` map and `fallback: knowledge`
- [x] ✓ 2026-10-22 GitHub is read with a GitHub App installation token (its own rate pool, not shared with a user PAT); the ceiling is 1000 calls per hour, a conservative start to tighten after measurement
- [x] ✓ 2026-10-22 Reconcile runs every 10 minutes per source and the alert fires when a source has not been read for 20 minutes. The period and the bound are one decision: `as_of` only advances on a successful read, so a bound shorter than the period would fire every cycle
- [x] ✓ 2026-10-22 End-to-end bound is 60 seconds from a forge event to the queue, generous and to be tightened after measurement. The e2e command must drive the webhook path, since reconcile would hide a missed webhook inside that window

## Implementation

> Slices are PR-sized and ship in this order: read queue (1, 2), writes (3), operations (4, 5), end to end (6). Each slice is a draft PR until reviewers have run.

### 1. Read model and adapters

- [x] [P] [AC1] Contract tests for one read-adapter interface against recorded GitHub and Gitea responses ✓ 2026-10-22 (#2635)
  - [x] ✓ 2026-10-22 Reader interface, unreachable-source error and the contract runner, with the recorded GitHub fixture (#2635)
  - [x] ✓ 2026-10-22 Gitea fixture (shape recorded from the live forge, values neutralised by hand) run through the same contract
  - [x] ✓ 2026-10-22 Pin the request in the contract: path and query are asserted per forge, mutation-proven (PR-Agent finding on #2635)
  - [x] ✓ 2026-10-22 Forge-neutral contract: expected items and counts are parameters (PR-Agent finding on #2635)
- [x] [AC1] Atlas migration in the `infra.postgres` tenant: items, event table, per-source `as_of` and reachability ✓ 2026-11-02 (#2933)
  - [x] ✓ 2026-11-02 Migration (#2933); the API connects as its own `api` tenant (#2932), decided by the operator over ADR-051 D2's owner role
- [x] [AC1] Implement the Gitea and GitHub adapters to make the contract tests pass ✓ 2026-11-12
  - [x] ✓ 2026-10-22 GitHub adapter: pagination, `since`, token only when set and never sent to another host (#2635)
  - [x] ✓ 2026-10-22 Gitea adapter: issues and pull requests are two listings, either failing fails the read
  - [x] ✓ 2026-11-01 A `read:issue` credential for the Gitea reader of its own: `issue_reader_token`, a third token on the reviewer's account (no new account), minted by `beelink_services` provisioning from `token_scopes.issue_reader`, catalogued, rotatable with `make gitea-rotate-token TOKEN=issue_reader`. No expiry is recorded because Gitea's token API has no expiry field (as `bot_token`). The token exists only after `make provision NODE=bee ENV=prod TAGS=gitea` runs
  - [x] ✓ 2026-11-01 [AC4] Deliver `issue_reader_token` to the API: `FORGE_GITEA_TOKEN` in `api-secrets` (optional, since staging has no Gitea token and the API starts without it), read by `config.Forge`, with `tests/test_forge_credentials_delivery.py` pinning that no credential lands in a ConfigMap. No NetworkPolicy is needed: NET-002 is ingress-only and the API is the caller, so egress is not restricted
  - [x] ✓ 2026-11-12 [AC4] Measure the grant: the first live read of an issue list with `type=pulls` confirms `read:issue` alone suffices; a 403 widens `token_scopes.issue_reader` deliberately, with `ISSUE_READER_SCOPES`. Measured in staging (#3267, the mint step below): its token holds `read:issue` only, and all five Gitea sources read reachable. `ListItems` reads `type=issues` then `type=pulls` and fails the whole read if either fails, so the pulls listing answered 200 under that grant
  - [x] ✓ 2026-11-01 [AC4] The webhook receiver's host passes Gitea's `ALLOWED_HOST_LIST` without widening it: #2887 pinned Gitea's container to public resolvers (lesson-682), so the receiver needs a name that resolves to a public address. That also means Gitea cannot resolve `*.staging.kubelab.live`, so a Gitea webhook never reaches staging, and AC5's probe must account for it
- [x] [AC1] Regression test: a source that is down renders unreachable with its last read time, never empty ✓ 2026-11-06
- [ ] [P] [AC4] Webhook receiver: reject an invalid HMAC, store the event before projecting it
  - [x] ✓ 2026-10-22 Signature verification for both forges, GitHub `sha256=` prefix and Gitea bare hex (#2636)
  - [x] ✓ 2026-11-02 Receiver endpoint and the event store: `POST /api/forge/webhooks/:forge`, HMAC before any write, a redelivery is a no-op. Until the webhook secrets reached prod, every delivery was refused
  - [x] ✓ 2026-11-02 Projection: every 10 seconds, the `forge_source` row first because of the foreign key, item and delivery mark in one transaction, and a late older delivery does not overwrite a newer read (PR-Agent finding on #2933)
  - [x] ✓ 2026-11-03 Deliver `FORGE_GITHUB_WEBHOOK_SECRET` and `FORGE_GITEA_WEBHOOK_SECRET` through SOPS and `SECRET_CATALOG`, prod only: staging is VPN-only, so no forge reaches it
  - [ ] Register the two webhooks as code
    - [x] ✓ 2026-11-05 GitHub: the App's own hook, `make forge-github-hook` (plan; `APPLY=1` writes, `SECRET=1` resends after a rotation). The events and the Active toggle are the operator's settings step, which the command checks (lesson-714)
    - [ ] Gitea: the sources now name each declared Gitea repository, so `repository_settings.webhooks` (one hook per declared repository) matches them; what remains is declaring the hook to the API there
- [x] ✓ 2026-11-02 [AC4] Test: the same delivery twice projects once (`TestSameDeliveryProjectsOnce`, against Postgres)
- [x] ✓ 2026-11-02 [AC4] Periodic reconcile per source every 10 minutes under the hourly call ceiling, with a guard test that counts calls. The ceiling is per forge since 2026-11-09, when the Gitea reader was wired (see the sources task below)
- [ ] [AC1] Queue endpoint with the inbox reason (author, requested reviewer, failing CI, waiting on me). `GET /console/queue` serves the open items without reasons since 2026-11-04; the reasons need the operator's login per forge and check-run reads
  - [x] ✓ 2026-11-04 The queue lists declared sources only, so a repository removed from `infra.forge.sources` leaves the view, and an item deleted upstream goes on the next full rebuild (PR-Agent finding on #3001)
- [ ] [AC1] The sources cover every repository of the operator's forges (Gitea and the personal GitHub account; no organisation), and a repository created later appears with no new declaration. The declaration stays the receiver's gate: an owner's wildcard (`github:mlorentedev/*`) is bound to that owner, so an App installation widened to another owner still stores nothing
  - [x] ✓ 2026-11-09 GitHub: the 24 repositories that carry `add-to-project.yml`, held sorted and well-formed by `tests/test_forge_sources.py`
  - [x] ✓ 2026-11-09 Gitea: the reconcile wires a Gitea reader, behind its own call ceiling, when `infra.forge.gitea_url` is set (prod: the in-cluster `gitea` Service; staging: none). The sources name every repository under `apps.services.core.gitea.organizations` and only those, held equal by `tests/test_forge_sources.py`
  - [x] ✓ 2026-11-09 Discovery in the `forge` package: `forge:owner/*` parses; `Catalog` lists each wildcard through the App installation (`GET /installation/repositories`, no forks, no archived), keeps the last good listing when one fails, and only a successful listing retires a repository; the receiver admits an owner's wildcard on the same terms
  - [x] ✓ 2026-11-09 The reconcile and the console queue read one `Catalog`, seeded from `forge_source` at start, over readers built once (a forge's listing and reads share its ceiling); `infra.forge.sources` declares `github:mlorentedev/*` in place of the named list, and `tests/test_forge_sources.py` holds GitHub to the personal account. Operating notes: `docs/runbooks/forge-console-operations.md`

### 2. Access and UI

- [x] [AC3] The console on its own host behind Authelia (`console.kubelab.live`, see "The console" in `proposal.md`); the api serves `/console` only for that host ✓ 2026-11-04
- [ ] [AC3] Authelia in front of the write routes; 401 without a credential
- [ ] [AC3] Machine token in SOPS and `SECRET_CATALOG`, accepted on the create write only; test that every other route refuses it
- [x] [AC1] Queue page, read-only, with each source's freshness visible ✓ 2026-11-04
- [ ] [AC1] Inbox screen with the reasons, once the queue endpoint carries them

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
  - [x] ✓ 2026-11-02 Covered: the prod dump is `pg_dumpall`, so the `api` database is in it without a change
  - [ ] Rehearse one restore
- [x] [AC7] Test that the read model rebuilds from the forges alone ✓ 2026-11-06
- [x] ✓ 2026-11-01 [AC4] [AC7] Create the GitHub App for the read adapter, store its credential in SOPS with a catalog entry (App `kubelab-console`, App ID 5573076, installed on `mlorentedev/kubelab` only as installation 177667607; Issues, Pull requests and Metadata read-only, webhooks off; private key at `apps.services.core.github_app.private_key` in `common.enc.yaml`; GitHub App keys carry no expiry, so the catalog entry is `Expiry.NEVER`)
- [x] ✓ 2026-11-01 [AC4] Deliver the App ID, installation ID and private key to the API: the two IDs at `infra.forge.github.*` reach the ConfigMap as `INFRA_FORGE_GITHUB_APP_ID` and `INFRA_FORGE_GITHUB_INSTALLATION_ID`; the key reaches `api-secrets` as `FORGE_GITHUB_PRIVATE_KEY`
- [x] ✓ 2026-11-02 [AC4] Mint an installation token from the App ID, installation ID and key, then read once to measure the App's grant
  - [x] ✓ 2026-11-02 `forge.AppTokens`: RS256 JWT with the standard library, exchanged at `/app/installations/{id}/access_tokens`, cached until five minutes before expiry; `GitHub.Tokens` takes it per read, and a failed mint is a `SourceError`
  - [x] ✓ 2026-11-02 Read once with the deployed image: on staging at `sha-75346a3` the first full read returned 2936 items, and each of the four counts (issues and pull requests, open and closed) equals GitHub's search count. The pod used 11 MiB. The App's grant needs nothing more
- [ ] [AC7] Runbook: rebuild, restore, rotate tokens; token expiry dates in the SOPS catalog
- [x] ✓ 2026-11-12 [AC1] Staging reads Gitea before prod does (#3267): its own token `kubelab-issue-reader-staging` in staging's SOPS, a `gitea` Service with no route to the Beelink's tailnet address, `infra.forge.gitea_url` in `staging.yaml`
  - [x] ✓ 2026-11-12 Code, tests and the rotation path (`store_env`), three mutations red
  - [x] ✓ 2026-11-12 Mint (`make provision NODE=bee ENV=prod TAGS=gitea`, `changed=0` on the rerun), recorded by #3331, `make apply-secrets ENV=staging`: no `no reader for this forge` since the API restarted, all five Gitea sources reachable with a fresh `as_of`, and `personal/resume` serves 76 issues against a Gitea page of 50
- [ ] A8 usage counter (ADR-066 A8, ADR-074 sequence step 2), table `console_usage` keyed by identity and UTC day, written on `GET /console/` only: one daily row per operator identity read from `Remote-User`, in its own table outside the rebuildable projection and covered by the backup. It ships with the first prod promote of the console or right after it: A8's 14 days run from the day the console is live in prod (`console.kubelab.live`, api 1.4.0), and a day of use that was not recorded cannot be replayed
  - [x] ✓ 2026-11-12 Shipped (#3334) and live in prod with api 1.8.0 (#3351): prod Loki shows the `console_usage` migration applied at 07:03Z
  - [ ] Read back one row for an operator identity and today's UTC day after a visit to `console.kubelab.live/console/`; a table that exists is not a write path that runs
- [ ] Read side of A8: a command that reports the longest run of days in any 14 consecutive with a `console_usage` row, so the gate below is read from the counter and not from memory
- [ ] Hand over to the Vikunja retirement (#2587) only when both of its gates hold: parity, meaning the narrow writes of section 3 have shipped, and the operator has opened the console on at least 5 of 14 consecutive days, read from the counter. Until then Vikunja keeps running as the fallback A8 reverts to

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
