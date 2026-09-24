---
id: "TOOL-080-forge-pr-reviewer"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-09-23"
issue: "mlorentedev/kubelab#1823"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, gitea, review, pr-agent]
template_version: "1.0"
---

# TOOL-080-forge-pr-reviewer

## Why

<!-- from issue #1823: The Gitea forge has no automated reviewer, and PR-Agent's Gitea provider already works against it -->

Nothing reviews pull requests on the Gitea forge. On GitHub, reviews came from the Codex and CodeRabbit Apps and from `.github/workflows/pr-agent.yml`. None of them runs on `gitea.kubelab.live`. All ten `personal/resume` pull requests opened there have no review, so every merge has to be disclosed as unreviewed. Each repository that moves under ADR-065 loses its reviewer the same way.

A read-only probe on 2026-09-24 settled whether PR-Agent could fill the gap. It was the same 0.45.0 release this repository pins, with `CONFIG__GIT_PROVIDER=gitea`, the NaN backend and publishing off. Against https://gitea.kubelab.live/personal/resume/pulls/270 it read the diff and produced a complete Reviewer Guide (#1823).

## What

PR-Agent runs in the prod cluster as a **Gitea webhook server**. The decision is Manu's, taken 2026-09-24: deploy it as a Deployment in the cluster, not as a compose service or a job in each repository.

When a pull request is opened, reopened or pushed to on any repository the forge reconciler declares, PR-Agent posts a review comment. Four properties matter:

- **Authorship.** The comment is authored by a dedicated reviewer account, so a triage tells reviewer output apart by author.
- **One comment per PR.** A push edits the review in place (`persistent_comment`) instead of adding a new one.
- **No per-repository cost.** No repository needs a secret or a workflow to be reviewed. Being declared to the reconciler is enough.
- **Detected silence.** A pull request that goes too long without a review raises an alert. A lost webhook leaves no red check, so the silence has to be detected.

The components:

1. **Server.** Image `pragent/pr-agent:0.45.0-gitea_app`. Its default command is gunicorn with UvicornWorker on `:3000`, and it serves `POST /api/v1/gitea_webhooks` (`pr_agent/servers/gitea_app.py`). The image tag is declared in `common.yaml` and mirrored by `make sync-k8s-images`, the same path as n8n.
2. **Configuration**, through a hashed `configMapGenerator`. Most values carry over the contract `pr-agent.yml` already uses:
   - `CONFIG__GIT_PROVIDER=gitea`
   - `GITEA__URL=https://gitea.kubelab.live`
   - `OPENAI__API_BASE=https://api.nan.builders/v1`
   - `CONFIG__MODEL=openai/mimo-v2.5`, with `CONFIG__FALLBACK_MODELS=["openai/deepseek-v4-flash"]`
   - `CONFIG__CUSTOM_MODEL_MAX_TOKENS=200000`
   - `CONFIG__PUBLISH_OUTPUT_PROGRESS=false`

   Three settings are set on purpose, because the upstream defaults differ:
   - `GITEA__PR_COMMANDS=["/review"]`. Upstream's default includes `/describe`, which rewrites the PR's title and body, and `/improve`. `pr-agent.yml` turns both off on GitHub.
   - `GITEA__HANDLE_PUSH_TRIGGER=true` with `GITEA__PUSH_COMMANDS=["/review"]`. Upstream ignores `synchronized` unless this is set, so a push would otherwise go unreviewed.
   - `PR_REVIEWER__PERSISTENT_COMMENT=true`.

   A repository's own `.pr_agent.toml` on its default branch still applies (`apply_repo_settings`). That is where per-repository instructions live.
3. **Secrets**, one K8s Secret produced by `make apply-secrets` from three new SOPS keys. All three are required, none optional:

   | SOPS key | Env var | Kind |
   |---|---|---|
   | `apps.services.automation.pr_agent.nan_api_key` | `OPENAI__KEY` | EXTERNAL. A copy of the Bitwarden `NAN_API_KEY` (Manu, 2026-09-24) |
   | `apps.services.automation.pr_agent.webhook_secret` | `GITEA__WEBHOOK_SECRET` | RANDOM_HEX |
   | `apps.services.core.gitea.reviewer_token` | `GITEA__PERSONAL_ACCESS_TOKEN` | EXTERNAL, minted by Ansible |
4. **Reviewer identity.** A new row in `apps.auth.identities`. It gets:
   - an account created by `gitea-bootstrap.sh`, with `prohibit_login=false`, because `true` kills API tokens;
   - a token minted by Ansible, gated on its SOPS key being absent, the same as `bot_token`. Its scopes are declared under `token_scopes` and tied to a requirement by `tests/test_gitea_token_scopes.py`;
   - membership in a **read** team in each declared organization;
   - an entry in `ROTATABLE_TOKENS`.

   It gets no write access to code, and it owns nothing.
5. **Webhook.** The per-repository reconciler learns a list of hooks (`gitea.webhooks`), matched by URL as today, with the n8n hook as the first entry. The second entry is `https://pr-agent.kubelab.live/api/v1/gitea_webhooks`, with events `[pull_request]` and the PR-Agent secret. Each hook reads its own secret, and the list stays backward-compatible with the singular key until the migration lands.
6. **Ingress.** An IngressRoute on `Host(pr-agent.kubelab.live) && Path(/api/v1/gitea_webhooks)`, on the `websecure` entry point with Let's Encrypt.
   - Middlewares: `secure-headers`, `rate-limit`, `crowdsec-bouncer`. There is no `authelia`: the HMAC signature is the authentication, as with n8n's `/webhook/`.
   - DNS gets a row in `infra/terraform/dns/services.json` with no `target`. That is the same public-IP path `n8n.kubelab.live` already uses successfully under Gitea's default `ALLOWED_HOST_LIST`.
7. **Detector.** A CronJob in the r2-backup-watcher style lists open pull requests on the declared repositories. For each one whose head commit is older than N minutes and has no reviewer-authored comment updated after it, it emits one JSON line. A Grafana rule on that line pages through `apprise-log`.

## Out of scope

- **Slash commands** (`/review`, `/ask` and the rest in comments). The upstream Gitea server runs any comment starting with `/` from any author (`handle_comment_event`). It has no equivalent of the OWNER/MEMBER/COLLABORATOR gate `pr-agent.yml` applies on GitHub, and OAuth auto-registration is on. So the hook subscribes to `pull_request` only. A follow-up can add `issue_comment` behind an author filter.
- **A review check or merge gate.** The forge has no branch protection (TOOL-063 #1633), and `review-attestation.yml` depends on `workflow_run`, which is unmeasured on Gitea 1.25.
- **Porting `dotf pr triage-queue` to the forge** (mlorentedev/dotfiles#1622).
- **Staging.** The Gitea route and the singleton-forge hooks exist in prod only.
- **Keeping one NaN credential across Bitwarden and SOPS.** Manu accepted the copy. See Risks.

## Risks / open questions

- **Two copies of one credential.** `NAN_API_KEY` rotates every 90 days in Bitwarden (dotfiles `secrets/registry.yaml`), and the SOPS copy does not follow on its own. Mitigation: the catalog entry's `rotate_note` names the one-line re-copy, `dotf secrets run --only NAN_API_KEY -- sh -c 'printf %s "$NAN_API_KEY" | toolkit secrets set apps.services.automation.pr_agent.nan_api_key --env prod --stdin'`, and the registry comment gains `k8s:kubelab/pr-agent` as a consumer. If the copies drift, NaN returns 401 and the detector catches the silence. That is the backstop, not the fix.
- **Upstream accepts unsigned requests when `webhook_secret` is empty** (`get_body`). The Secret key is required, so the pod cannot start without it, and a test asserts the manifest's `secretKeyRef` has no `optional: true`. An AC measures that an unsigned POST is refused.
- **NaN concurrency.** NaN allows 5 concurrent requests, shared across every consumer (#1203). gunicorn starts 2–4 workers depending on the CPU limit, and each can run several background reviews. Five rebased PRs at once (measured on resume, 2026-09-24) would be five concurrent calls. The fallback model absorbs a 429. Pinning `workers` via a small gunicorn config override is decided in the manifests PR, after one burst has been measured.
- **To measure in the identity PR:** whether a read-team member with a `write:issue` token can comment on a pull request, and whether PR-Agent's Gitea provider needs any other scope (for example `read:user` for `/user`). Scopes are declared from the measurement, not guessed.
- **To measure in the manifests PR:** whether the image runs as non-root with a read-only root filesystem plus an `emptyDir` on `/tmp`. The image declares no user, so it runs as root. If it works, `securityContext` gets `runAsNonRoot`; if not, the reason is recorded in the manifest.
- **The reviewer is a third machine identity.** AUTH-007 (#1781) is already amending ADR-062 D1 for a second machine class. This spec extends the same amendment, rather than starting a parallel one, and lands after or together with it.
- **Cross-repository refs.** PR-Agent on GitHub reads `resume#N` in a kubelab PR as kubelab#N. On the forge each PR reviews only itself, so this does not apply. Forge issues in this spec are linked by full URL anyway.

## Acceptance criteria

1. **AC1:** A pull request opened on `personal/resume` gets a `PR Reviewer Guide` comment authored by the reviewer account within 10 minutes. By effect, on a real PR.
2. **AC2:** A push to that open pull request updates the same comment rather than adding a second one. `persistent_comment`, by effect.
3. **AC3:** A POST to the webhook endpoint with no `X-Gitea-Signature`, or a wrong one, is refused with 400 or 401 and produces no review. By effect. A committed test asserts the Secret key is required.
4. **AC4:** Reviewing never edits the PR: after AC1 the title and body are byte-identical, and `PR_COMMANDS` and `PUSH_COMMANDS` are exactly `["/review"]`. Asserted by a committed test on the rendered ConfigMap, and by effect.
5. **AC5:** The reviewer token's scopes equal what the measurement required, and `write:repository` is not among them. Its account owns no repository and holds read access only. Tied grant-to-requirement by `tests/test_gitea_token_scopes.py`, plus a live `GET /users/<reviewer>/repos` that returns empty.
6. **AC6:** All three SOPS keys are in `SECRET_CATALOG` and mapped. The orphan audit stays green, and `apply-secrets` fails closed when any of them is missing. Committed tests.
7. **AC7:** After `make gitea-reconcile ENV=prod APPLY=1`, every declared repository carries both hooks, and a second run reports no changes. By effect.
8. **AC8:** A pull request with no reviewer comment after N minutes produces an alert. By effect, with the server scaled to 0 and a test PR opened.

## References

- Issue: mlorentedev/kubelab#1823, which includes the probe method and output.
- `.github/workflows/pr-agent.yml` and `.pr_agent.toml`: the GitHub-side contract, carried over as env vars.
- `infra/k8s/base/services/n8n.yaml` and `overlays/prod/patches.yaml:132-149`: the webhook receiver and route to copy.
- `toolkit/features/gitea_repos.py:254-376, 814-865`: the singular `WebhookSpec` this extends.
- `infra/ansible/roles/beelink_services/tasks/main.yml:332-374` and `files/gitea-bootstrap.sh:194-250`: the machine-account mint to mirror.
- Related: ADR-065 (forge organization), ADR-066 D4 (webhook signatures), #503 (signed repository webhooks), #1781 (AUTH-007), #1306 (the healthy-but-silent class), TOOL-021 (reviewer capacity), TOOL-062 (Actions secrets).
