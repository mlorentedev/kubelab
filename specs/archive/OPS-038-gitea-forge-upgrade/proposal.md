---
id: "OPS-038-gitea-forge-upgrade"
type: spec
status: archived # draft | implementing | verifying | archived
created: "2026-10-16"
issue: "mlorentedev/kubelab#2375"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "Owner authorized 2026-10-17: #2375 forge CI throughput; WIP exception granted in conversation (18 active, limit 10, 2026-10-16)"
---

# OPS-038: Upgrade the Gitea forge so superseded CI runs are cancelled

## Why

<!-- from issue #2375: Forge CI: superseded runs are not cancelled and one runner with capacity 2 serves every repo -->

Workflow `concurrency` with `cancel-in-progress` is not implemented in the Gitea we run (1.25.5): it arrived in 1.26.0 (go-gitea/gitea#32751, refused for backport to 1.25 because it changes the DB schema). So a push that supersedes a running forge job leaves the old run holding one of the runner's two slots, and every forge repo queues behind it. The runner bump planned in OPS-034 (#2063) cannot fix this alone, because the missing piece is on the server. The forge is a singleton holding private repositories, `gitea.db` and the SSH host keys, so the upgrade is rehearsed on a restored copy before it touches the live node.

## What

After this work the forge runs a Gitea release that honours workflow `concurrency`, upgraded through the IaC path (`common.yaml` image pin, `provision-bee`), after a rehearsal on the newest R2 snapshot. A second push to the same branch cancels the first run, including a run already executing on the runner.

Target: **1.27.3**, not 28.1.0 and not 1.26.x. Reasons, from the release notes (research 2026-10-16, sources in the PR):

- 1.26.x has `concurrency`, but its first patch releases fixed groups leaking across branches (1.26.1) and a deadlock (1.26.2), and 1.26.3 has a regression. The correct "Cancelling" state for running jobs (needs a Gitea Runner >= 2.0.0) arrives in 1.27.0, and its stuck states are fixed in 1.27.1 and 1.27.2.
- 1.27.3 carries the fix that stops an unapproved fork-PR run from cancelling a trusted run in the same group (GHSA-4j4g-m7mr-hp5j).
- 28.x adds config changes this forge does not need for its goal: `[server] DOMAIN` ignored in favour of `ROOT_URL`, self-registration off unless set explicitly, 400-day run retention by default, a new egress model for migrations and mirrors, and WebSocket headers required at the proxy. They are a separate, later upgrade with their own rehearsal.
- #39461 (28.0.0) fixes `cancel-in-progress: false` ordering; this work uses `true`. #39702 (a reusable workflow stuck in "Cancelling") applies only to `workflow_call` callers, to be confirmed absent from forge workflows.

Two minors are skipped (1.25 to 1.27). The upgrade guide states no rule against it and migrations run in order at startup; the rehearsal is what proves it on our data.

## Out of scope

- The second runner and the capacity reserve (#2375 options 2 and 3). They go in their own PR after this one.
- The runner upgrade (OPS-034, #2063). This work only records whether act_runner 0.2.13 still connects to the new server, and sequences OPS-034 if it does not.
- Gitea 28.x.
- Adding `concurrency` blocks to forge workflows, unless the measurement in AC8 shows none exists; that is then a small follow-up PR.

## Risks / open questions

- Migrations are not reversible. The only rollback is the pre-upgrade backup, so a fresh `make backup-node` and a green `make backup-drill-gitea` come before the live step.
- Whether act_runner 0.2.13 still connects to a 1.27 server is not stated by the release notes (the runner 2.0.0 notes only say it stays wire-compatible). The rehearsal answers it; if it fails, OPS-034 lands first.
- The CSRF mechanism changed in 1.26 (cookie replaced by header checks). It may affect the Authelia OIDC callback; AC4 covers it.
- `PUBLIC_URL_DETECTION` default changed in 1.26 and its effect on an existing install is not stated; pin it explicitly in the templated `app.ini`.
- The forge reviewer image `pragent/pr-agent:0.45.0-gitea_app` has not been checked against the new API. A silent break fails `review-attestation` on every forge PR.
- Downtime window: the live step stops Gitea. Peers using the API (dotfiles `dotf forge`, TOOL-030) are told the window beforehand.

## Acceptance criteria

- [ ] AC1. `make backup-drill-gitea ENV=prod`, run with the candidate image pinned in `common.yaml`, passes: the 1.27.3 image starts on the restored snapshot (migrations complete) and its API answers.
- [ ] AC2. Against that restored copy, `gitea doctor check --all` reports no error and the templated `app.ini` has no deprecated key; `PUBLIC_URL_DETECTION` is set explicitly.
- [ ] AC3. The `dotf forge` contract works against the restored copy: `POST /api/v1/repos/{o}/{r}/issues/{N}/comments` with `Authorization: token` answers 2xx with `html_url`, and issue create/edit and pull create/comment/edit on the same v1 API behave as before.
- [ ] AC4. Login through Authelia OIDC completes on the restored copy, and `gitea-bootstrap.sh`'s `update-oauth --id N` still applies.
- [ ] AC5. `PATCH /repos/{o}/{r}` with `has_pull_requests: true` still applies the six merge settings (the `ensure_settings` read-back in `gitea_repos.py`), and the PR-Agent app (`pragent/pr-agent:0.45.0-gitea_app`) is shown to work against the new server or is updated in the same change.
- [ ] AC6. Runner registration through `gitea actions generate-runner-token` works, and act_runner 0.2.13 connects to the new server; if not, OPS-034 is sequenced first and the PR says so.
- [ ] AC7. The live upgrade is applied with `make provision NODE=bee ENV=prod TAGS=gitea` and a re-run reports `changed=0`; a fresh `make backup-node NODE=bee ENV=prod` was taken immediately before.
- [ ] AC8. Measured live: two pushes in quick succession to one branch, the second run cancels the first, including when the first is already running on the runner. The result is recorded on #2375.
- [ ] AC9. A runbook, `docs/runbooks/gitea-upgrade.md`, records the rehearsal, the rollback (restore the snapshot) and the downtime window, and a lesson captures what the rehearsal found.

## References

- Bitácora board: #2375 (see the `issue:` frontmatter field)
- Related: OPS-034 (#2063, runner upgrade), BACKUP-040 (`gitea_drill.py`, the restore drill used as the rehearsal), dotfiles#2649 and #2635 (`dotf forge`, API consumers)
- Gitea release notes: blog.gitea.com release posts for 1.26.0, 1.26.1, 1.26.2, 1.27.0 to 1.27.3, 28.0.0; upgrade guide at docs.gitea.com/installation/upgrade-from-gitea
