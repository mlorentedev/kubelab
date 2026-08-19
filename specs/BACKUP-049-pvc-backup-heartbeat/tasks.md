---
tags: [spec, tasks, templates]
created: "2026-08-19"
---

# Tasks - BACKUP-049-pvc-backup-heartbeat

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers**: `[P]` = no dependency on another unchecked task. `[AC<n>]` = helps satisfy acceptance criterion #`<n>` in `proposal.md`.

## Setup

- [x] `proposal.md` is complete and acceptance criteria are testable
- [x] Four design questions resolved and recorded under `## Decisions` (demo
      staging, delivery-failure semantics, HTTP client, monitor key)
- [ ] **Blocked on #1169 (PR #1170).** The token cannot be declared in the SSOT
      until the sync can carry a push monitor. Nothing below starts first.
- [ ] The single remaining open question — which endpoint the pod posts to — is
      resolved by **I1** below, by measurement, before any manifest is written.
      It is deliberately not settled by reading manifests.
- [ ] Branch created from master: `feat/backup-049-pvc-backup-heartbeat`

## Implementation

### I1 — Settle the endpoint by measuring it

- [ ] [P] From inside the prod cluster, probe the in-cluster `uptime-kuma`
      Service (`uptime-kuma.kubelab.svc.cluster.local:3001`) and the public host.
      Record which resolves, which connects, and whether the CrowdSec or
      rate-limit middlewares interfere on the public path. Write the answer and
      the transcript into `proposal.md`, replacing the open question.

### I2 — The credential

- [ ] [P] [AC8] Register `apps.services.observability.uptime_kuma.push_tokens.prod_backup_pvc_heartbeat`
      in `SECRET_CATALOG` with `envs=("prod",)`. Assert the ANSIBLE-033 failure
      mode explicitly: a tuple matching no real env removes the secret from every
      audit, silently, and a backup credential missing from the audit is the worst
      possible thing to be silently absent.
- [ ] [AC8] Generate the token and store it in `common.enc.yaml`. Verify with
      `make secrets-audit` that prod's count rises by exactly one.

### I3 — The monitor

- [ ] [P] [AC5] Write the failing seed test: the entry `prod-backup-pvc-heartbeat`
      exists, is `type: push`, and carries **no** `pushToken`.
- [ ] [AC5] Add the entry to `infra/config/uptime-kuma/monitors.json`. Interval
      per the decision (daily period plus grace; Kuma accepts up to 604800s,
      measured). Tags must exclude every member of `muted_notification_tags`.
- [ ] [AC6] Apply, then assert against the **live** monitor that its
      `notificationIDList` is non-empty. Asserting against the seed would prove
      only that the seed says so.
- [ ] [AC5] Round-trip: `make monitoring-export` then re-apply, and assert the
      live token is unchanged and the plan is `0 create, 0 edit, 0 delete`.

### I4 — The sender

- [ ] [P] [AC7] Write the failing test first: with the endpoint unreachable, the
      backup script's exit status is **0**. This is the decision under test, so it
      gets a test rather than a `|| true` anyone can read past.
- [ ] [AC1] [AC7] Add `curl` to the existing `apk add` line and the heartbeat to
      the success tail of `infra/k8s/overlays/prod/backup.yaml`, after every
      backup step. Reuse the hardening in
      `roles/node_maintenance/templates/kubelab-maintenance-notify.sh.j2`: token
      via `--config -` (never `argv`), `--connect-timeout` / `--max-time`, a
      `--retry` budget that fits inside `activeDeadlineSeconds: 1800`, and the
      delivery failure swallowed per the decision.
- [ ] [AC1] Plumb the token into the pod via `SECRET_DEFINITIONS`. Confirm the
      flattened env var name is valid — this is what #1169's `_` -> `-`
      normalisation exists for.
- [ ] [AC4] Deploy through the pipeline and capture
      `kubectl get cronjob pvc-backup -n kubelab -o json --show-managed-fields`
      before and after. The manager set must be unchanged.

## Verification

- [ ] [AC1] Run `make backup-pvc ENV=prod` and observe the monitor go UP.
      Operator go-ahead required — it mutates prod.
- [ ] [AC2] Inject a failure (an unreadable source path) and observe that **no**
      heartbeat is posted and the monitor stays on its last state.
- [ ] [AC3] Create a scratch push monitor at a 60s interval carrying the same
      notification links, post once, then stop. Observe the DOWN alert **arrive
      in the operator's real channel**. Capture the received notification, not a
      screenshot of the config.
- [ ] [AC3] Delete the scratch monitor and confirm the next `monitoring-apply`
      plans nothing.
- [ ] [AC4] Re-read the field managers after every step above.

## Closing

- [ ] Every acceptance criterion is covered by at least one test or a captured
      transcript in `verification.md`
- [ ] `features.json` entries all carry a non-vacuous `verification` command
- [ ] Type checks pass; lint passes
- [ ] No unrelated changes in the diff — the `mc` runtime download stays out
- [ ] `verification.md` filled in
- [ ] Adversarial review run (`dotf spec review BACKUP-049-pvc-backup-heartbeat`)
      from a session that is not the implementer, before archive
