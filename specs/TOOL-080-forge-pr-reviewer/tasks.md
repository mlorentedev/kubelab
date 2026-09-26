---
tags: [spec, tasks]
created: "2026-09-23"
---

# Tasks - TOOL-080-forge-pr-reviewer

> TDD order. One task = one focused commit. `[P]` = no dependency on another unchecked task. `[AC<n>]` = serves that acceptance criterion.
> Design gate: nothing below `## PR 2` starts until Manu approves the proposal in the spec PR.

## PR 1 — this spec

- [ ] `proposal.md`, `tasks.md`, `verification.md`, `features.json` (every feature `pending`)
- [ ] Manu approves the design

## PR 2 — reviewer identity, and the ADR-062 D1 amendment it shares with AUTH-007 #1781 (Manu, 2026-09-24: this PR writes it)

- [x] [AC5] Measure first, record in `verification.md`. Does a read-team member's `write:issue` token post a PR comment on the forge? What else does the PR-Agent Gitea provider call (`/user`, repo settings)? The scopes come from this measurement.
      Measured 2026-09-24 in a local Gitea 1.25.5 lab (`scope-lab.py`): `write:issue` + `read:repository`, no `read:user`. The live check with the real identity is AC1, in PR 4.
- [x] [AC5] Failing tests: `test_gitea_token_scopes.py` covers the reviewer grant and requirement, `test_gitea_machine_identity.py` / `test_ansible_identity_ssot.py` cover the new identity row, and `ROTATABLE_TOKENS` gets a reviewer entry.
      Written as `test_gitea_token_scopes.py::test_the_reviewer_grant_is_exactly_the_measured_requirement` (equality, not superset) and a new `test_gitea_reviewer_identity.py`, which covers the row, the playbook, the catalog, the mint and record tasks, the compose env, and the bootstrap script's behaviour. Each was red first.
- [x] [AC5] `apps.auth.identities.reviewer` (`mentor`) and `token_scopes.reviewer` in `common.yaml`. Account block in `gitea-bootstrap.sh` (`prohibit_login=false`). Mint and record tasks gated on `apps.services.core.gitea.reviewer_token`.
- [x] [AC6] `SECRET_CATALOG` entry for `reviewer_token` (EXTERNAL, `Expiry.NEVER`, prod), modelled on `bot_token`.
- [x] [AC5] Reconciler: a read team per declared org with the reviewer as member (`ensure_team` generalised beyond one member and one permission).
      `TeamGrant` (`WRITE_TEAM`, `READ_TEAM`). The read team is converged in both directions, and membership is part of its plan (`tests/test_gitea_review_team.py`, red first).
- [x] The ADR-062 D1 amendment: what "login prohibited" means for a machine account, AUTH-007's owner-level pusher (#1781), and this reviewer.
- [ ] Live, **after #1828 and #1832 merge** (Manu, 2026-09-24: not from the branch, so no real token sits in SOPS on an unmerged branch): `make provision NODE=bee ENV=prod TAGS=gitea`, then `make gitea-reconcile ENV=prod APPLY=1`, re-run shows no changes, and `GET /users/<reviewer>/repos` is empty.

## PR 3 — a list of webhooks in the reconciler

- [x] [P] [AC7] Failing tests: `gitea.webhooks` holds a list and matches by URL, each hook reads its own secret key, the singular `gitea.webhook` still loads, and n8n stays first and pinned to prod.
      Written as `load_webhooks`'s loader tests (`test_gitea_repo_reconcile.py`, "webhooks: the list" section): position/pin, per-hook `secret_key`, the singular-block fallback, an empty list refused, a missing `secret_key` refused, a missing field refused, and a duplicate URL refused. Each was red (`ImportError`/`AttributeError`, then a real assertion) before `HookDeclaration`/`load_webhooks` existed.
- [x] [P] [AC7] Failing tests for per-hook event matching. The PR-Agent hook is created with `[pull_request_only, pull_request_sync]` and compared for set equality against the stored `[pull_request, pull_request_sync]`. A live surplus such as `pull_request_comment` is drift to correct, and a second run converges. n8n keeps its superset rule.
      Written against `webhook_changes` directly (equality-mode tests, same file) plus one end-to-end test in `test_gitea_repo_execute.py` (`test_the_equality_mode_hook_converges_a_live_surplus_in_one_write`) through a fake that models Gitea's `pull_request_only` -> `pull_request` rename. Confirmed red for the right reason by temporarily removing the alias and re-running (see build report).
- [x] [AC7] Implement `load_webhooks` and per-hook `ensure_webhook` in `gitea_repos.py`, and read each secret in `services.py`.
      `plan_reconcile`/`execute` now take `declared_webhooks: Sequence[HookDeclaration]` (was one `WebhookSpec`); `repos_to_hook` is `repos x declared_webhooks`, flattened. `services.py` resolves each hook's `secret_key` via `gitea_actions_secrets.sops_value`, keyed by URL.
- [x] [AC7] Declare the PR-Agent hook (`events: [pull_request_only, pull_request_sync]`). It stays `active: false` until PR 4 is live, so no delivery goes to a host that does not answer yet.
      In `infra/config/values/common.yaml`, second entry of `gitea.webhooks`, `event_comparison: equality`, `secret_key: apps.services.automation.pr_agent.webhook_secret`.
- [x] [AC6] `SECRET_CATALOG` entry for `webhook_secret` (RANDOM_HEX, length 32, prod only), modelled on n8n's `forge_webhook_secret`, and the value generated into `prod.enc.yaml` (Manu, 2026-09-26: moved from PR 4 into this PR).
      Catalog entry added in `secrets_manager.py` under a new "PR-Agent" section, next to N8N's. Value generated as `secrets.token_hex(32)` and piped over stdin into `toolkit secrets set apps.services.automation.pr_agent.webhook_secret --env prod --stdin`, never printed. Verified present (64 hex characters) without reading the value out, and the `prod.enc.yaml` diff adds that one key plus SOPS's `mac` and `lastmodified`. No dotfiles registry entry needed: unlike `nan_api_key` (EXTERNAL, copied from Bitwarden), this is RANDOM_HEX and has no external counterpart to register.

## PR 4 — the server in the cluster

- [ ] [P] [AC6] Failing test: catalog and mapping for `nan_api_key`, and required keys only (no `optional: true` on any `secretKeyRef`). `webhook_secret`'s catalog entry and value moved into PR 3 (Manu, 2026-09-26).
- [ ] [P] [AC4] Failing test: the rendered prod ConfigMap has `GITEA__PR_COMMANDS` and `GITEA__PUSH_COMMANDS` equal to `["/review"]`, `GITEA__HANDLE_PUSH_TRIGGER=true`, and no `GITEA__REPO_SETTING`, which would let a PR's head rewrite the reviewer's config. It also has `PR_REVIEWER__FINAL_UPDATE_MESSAGE=false`, both `PR_REVIEWER__ENABLE_REVIEW_LABELS_*=false`, and `CONFIG__REPO_CONTEXT_FROM_DEFAULT_BRANCH=true` (the 2026-09-24 lab).
- [ ] [AC6] SOPS: copy `nan_api_key` from Bitwarden through a pipe (`dotf secrets run --only NAN_API_KEY -- sh -c 'printf %s "$NAN_API_KEY" | toolkit secrets set … --stdin'`), never through argv or stdout. Add `rotate_note` naming that re-copy, and add `k8s:kubelab/pr-agent` to the dotfiles registry consumers.
- [ ] [AC1] `pr-agent.yaml` in the prod overlay: Deployment (limits, `enableServiceLinks: false`, standard labels), ClusterIP Service, IngressRoute (`secure-headers`, `rate-limit`, `crowdsec-bouncer`), and `configMapGenerator`. Image in `common.yaml` plus `make sync-k8s-images`, with Renovate coverage.
- [ ] Measure non-root. If it works, set `runAsNonRoot`, `readOnlyRootFilesystem` and an `emptyDir` on `/tmp`. If not, record why in the manifest.
- [ ] DNS row `pr-agent` in `infra/terraform/dns/services.json`, with no `target`.
- [ ] Live: `make apply-secrets ENV=prod`, Argo sync, flip the hook to `active: true`, reconcile.
- [ ] [AC1] [AC2] Write `tests/infra/test_pr_agent_review_live.py`, marked like the other `tests/infra/*_live.py` tests. Given the PR number recorded in `verification.md`, it asserts exactly one reviewer-authored `PR Reviewer Guide` comment on that PR, and that its `updated_at` is later than the latest push.
- [ ] [AC1] [AC2] [AC4] By effect: open a test PR on `personal/resume`, push once, and record the comment id, its author, and that the title and body are unchanged.
- [ ] [AC3] By effect: an unsigned POST and a wrongly signed POST are both refused.
- [ ] Measure a burst (at least 3 PRs at once). Decide whether to pin gunicorn `workers`.

## PR 5 — the silence detector

- [ ] [AC8] Failing tests for the watcher's selection logic. Silence is measured from the PR's creation or its latest `pull_push` timeline event, never from the head commit's date. Cases: an old-dated head on a fresh push must not page, a future-dated head must still page after N minutes, and a reviewer comment updated after the event clears it.
- [ ] [AC8] CronJob (r2-backup-watcher pattern) emitting one JSON line per unreviewed PR, and a Grafana rule on it through `apprise-log`. Register it in the `grafana-alerting` generator.
- [ ] [AC8] By effect: scale the server to 0, open a PR, and see the alert fire.

## Closing

- [ ] Every AC has a committed test or a by-effect record in `verification.md`
- [ ] `features.json`: the harness sets `passing`, never the agent
- [ ] Independent adversarial review before archive
- [ ] Knowledge: lesson(s) in `docs/lessons/`. Update [[reference-gitea-forge]] in the resume memory ("no reviewer on the forge" becomes a pointer to this)
