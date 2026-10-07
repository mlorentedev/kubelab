---
tags: [spec, tasks]
created: "2026-09-30"
---

# Tasks - AI-009-hermes-ace2

> TDD order. One task is one focused commit. `[P]` means no dependency on an unchecked task; `[AC<n>]` names the criterion the task serves.
>
> Six PRs after the prerequisite. Each one leaves ace2 provisionable and converged. Live steps run against staging ace2 (`make provision NODE=ace2 ENV=staging`); there is no prod leg, because ace2 has no prod identity.

## Setup

- [ ] Spec PR merged (`docs/ai-009-spec`) after ADR-068 (#1967)
- [x] Prerequisite **task 0**: #1300 merged, and a second `make provision NODE=ace2 ENV=staging TAGS=dev_node` reports `changed=0` ✓ 2026-10-01 (#1971; first run `changed=2` from upstream dotfiles commits, second run `ok=57 changed=0`)
- [ ] R1 and R2 answered by the operator before PR 3 and PR 4 merge (R1 answered for Open WebUI 2026-10-04: the PR-Agent key is shared; Hermes still open)

## Implementation

### PR 1 — the role, the agent user, and Open WebUI with NaN models only

New role `infra/ansible/roles/agent_stack/` (accepted with #1976: role name `agent_stack`; the alternative is one role per service, rejected because the two Compose projects share the user, the unit ordering and the backup paths), added to `provision-ace2.yml` after `dev_node` with tags `[agent_stack]`.

- [x] [P] [AC8] `tests/test_agent_stack_role.py`: render both Compose templates with the role defaults and assert every service has `mem_limit` (or `deploy.resources.limits.memory`) ≤ 1.5 GB. Run `make test-infra`. Expected: FAIL, templates absent. ✓ 2026-10-01 (PR 1, #1976)
- [x] [AC8] Add `apps.services.ai.open_webui` (image pinned by version, port, `memory_limit: 1536m`) and `apps.services.ai.hermes_kubelab` (image `nousresearch/hermes-agent:<X.Y.Z>`, `memory_limit: 1536m`, sandbox limits) to `common.yaml`. Template `compose-webui.yml.j2`. Re-run. Expected: PASS for the Open WebUI half. ✓ 2026-10-01 (PR 1, #1976; the Hermes half lands with PR 3)
- [x] [P] [AC4] Test: the Open WebUI port is published on `{{ tailscale_ip }}` only, never bare `<port>:8080` (the `rpi3_services` rule; ufw cannot restrict a published port). ✓ 2026-10-01 (PR 1, #1976)
- [x] [P] Read-only check before writing anything: `grep -ri open-webui infra/ toolkit/` (if AI-003 left a staging manifest, this PR retires it) and `stat -c %a` on the dev user's home (if it is already `0750`, the AC2 test asserts it; `agent_stack` never changes `dev_node`'s surface). ✓ 2026-10-01 (PR 1, #1976)
- [x] [AC4] Renderer: `redirect.scheme` (default `https`) and `redirect.port` (a key path, like `domain`) in `toolkit/features/oidc_clients.py`, tested with a fixture client. Existing clients must render unchanged (the committed `oidc-clients.yml` guard stays green). ✓ 2026-10-01 (PR 1, #1976)
- [x] [AC4] **PR 1b, after the operator mints the secret.** The `open-webui-oidc` client cannot land before its digest exists: `make sync-oidc-hashes` fails on a client with no stored `..._hash`, and `tests/test_oidc_clients.py` compares the committed file with the SSOT. Order: the operator runs a single-key `toolkit secrets set` for `apps.services.security.authelia.oidc_client_secret_open_webui` in `prod.enc.yaml` (never `credentials generate`, which rewrites 19 prod keys) and derives `oidc_client_secret_open_webui_hash` (the key `digest_key()` yields: `-oidc` dropped, `-` → `_`). Then one PR adds the client entry (redirect `http://ace2.kubelab.internal:3080/oauth/oidc/callback` via `scheme`/`port`), both `SECRET_CATALOG` entries (`envs=("prod",)`), the regenerated prod `oidc-clients.yml`, and the break-glass entry `tests/test_break_glass.py` will demand. `token_endpoint_auth_method` is measured at the first login, not assumed: Open WebUI registers through authlib, whose default is `client_secret_basic`. ✓ 2026-10-03 (`feat/ai009-webui-oidc`; the pair was minted 2026-10-02, the client and catalog entries landed with it; prod `validate-config` with the pinned 4.39.15 image accepts the `http` redirect, and a negative control fails on it)
- [x] [AC4] Operator decision before PR 1b: role mapping. `groups` in the scopes does nothing by itself; without `ENABLE_OAUTH_ROLE_MANAGEMENT`, `OAUTH_ROLES_CLAIM=groups` and `OAUTH_ADMIN_ROLES=admins`, the first OIDC login is admin and every later one is `pending`. Authelia sends `groups` in UserInfo, not the ID token (lesson-457), so whether Open WebUI reads it there is a measurement. ✓ 2026-10-03: `admins` → admin, `users` → user, anyone else refused (403), the ADR-062 D2 tiers. Open WebUI v0.11.4 reads UserInfo only when the ID token lacks the email or username claim, so `OAUTH_USERNAME_CLAIM=preferred_username` (never in Authelia's ID token) forces it; the first login measures it.
- [x] [AC4] Operator decision before PR 1b: the break-glass path. With `ENABLE_LOGIN_FORM=false`, Authelia is the only door to Open WebUI. Adding the client also errors before any declaration is read: `toolkit/features/break_glass.py` raises `BreakGlassError` for an OIDC client whose redirect host no IngressRoute serves (`tests/test_break_glass.py` asserts that on purpose). PR 1b teaches it a tailnet-direct dependent (the address is the declared `scheme`/`host`/`port`, reached over the tailnet with no port-forward). A blanket exemption is not the fix. ✓ 2026-10-03: a local `breakglass` account, the Grafana shape (#951). `ENABLE_LOGIN_FORM=false` never closed the password endpoint (lesson-520), so the form stays on for that account only. `break_glass.py` reaches the service at its declared address; `OpenWebUIAdminPassword` rotates it.
- [ ] [AC7] **Backup is a precondition of real use.** The OIDC secret is not minted, so Open WebUI holds no user data, until ace2 is in `backup.sources` with the `open-webui-data` volume (`sqlite` declared, and WAL already set). PR 6 moves ahead of PR 1b and follows BACKUP-057's bucket PR, so ace2 starts on the per-node bucket model instead of being migrated onto it. The cascade it touches: the heartbeat monitor and push token, the repository id after the first ship, the watcher targets, the derived inventory group, the WAL set in `tests/test_sqlite_sources_are_wal.py`, and the hardcoded node lists in `tests/test_backup_sources.py` and `tests/infra/test_backup_coverage.py`.

### Platform integration (lands with the PR that makes each surface true)

Inventoried 2026-10-01 against every surface an existing node-hosted service is registered in.

- [x] Homepage "Shared" row derived from `apps.services.ai.open_webui`, then `make sync-homepage` and `make sync-platform-json` (PR 1).
- [x] Renovate tracks the image through the existing `common.yaml` regex manager, and `tests/test_renovate_image_coverage.py` enforces it (no change needed).
- [x] The boot-race guard (`tests/test_tailscale_bound_ports_survive_boot.py`) sees the role, because its bind variable uses the fleet name `tailscale_ip` (PR 1).
- [x] Docs: `CLAUDE.md`, `docs/architecture/architecture-overview.md`, and an AI section in `docs/architecture/service-catalog.md` (PR 1). The rest of the catalog's drift is #1750.
- [x] Uptime Kuma monitor `services-ai-open-webui` (HTTP `/health` on the tailnet address, tags including `on-demand`), with PR 1c, once the service runs. The untagged on-demand monitors are #1974.
- [x] Access tiers: once the role-mapping decision is made, Open WebUI joins `toolkit/features/access_review.py` `TIERS` so `make auth-review` reads its live privileges. Moved to PR 1c (2026-10-03): the reader needs the live API shape. Corrected in PR 1c (2026-10-06): it is Gitea's shape, not Grafana's. v0.11.4 loads the user from its database on every request and its API edits an OAuth account's role, so the review edits and reads back (`fixed`); the declared viewer tier is `pending` (operator).
- [ ] The read-store guard covers ace2's two SOPS stores: #1975.
- [ ] Runbook `docs/runbooks/hermes-kubelab.md` covers Open WebUI too: start, stop, rotate the OIDC secret, restore the volume (Closing).
- Not applicable, each checked: Grafana alerts (they read in-cluster logs only), Vector/Loki (K3s-only, so node Docker logs have no shipper; the gap is fleet-wide, not specific to this service), e2e expectations (the suite only discovers HTTPS routes, the same as Homepage), DNS (the MagicDNS given-name resolves), release-please (third-party image), Traefik constants.
- [x] [AC4] Open WebUI env: `ENABLE_OLLAMA_API=false`, `OPENAI_API_BASE_URLS` = NaN only in this PR, `ENABLE_OAUTH_SIGNUP`, `OAUTH_PROVIDER_NAME`, `OPENID_PROVIDER_URL=https://auth.kubelab.live/.well-known/openid-configuration`, `ENABLE_LOGIN_FORM=false`. SQLite WAL (`DATABASE_ENABLE_SQLITE_WAL=true`, measure the name against the pinned version). ✓ 2026-10-04 (PR 1 and 1b; verification.md). `ENABLE_LOGIN_FORM` ships `true`, not `false`: the form never closed the password endpoint (lesson-520), so it stays on for the `breakglass` account only
- [x] [AC10] Env file rendered to `/opt/agent-stack/webui.env`, mode `0600`, root-owned; test asserts the mode and that no SOPS value appears in the Compose file itself. ✓ 2026-10-01 (PR 1, #1976)
- [x] [AC1] systemd unit `agent-stack-webui.service` with `wait-for-tailscale-addr.sh` (the `rpi3_services` shape). Every `command:` task carries a truthful `changed_when`. ✓ 2026-10-01 (PR 1, #1976)
- [x] [AC4] [AC1] Live: provision twice; second run `changed=0`; `ss -tlnp` shows the Tailscale bind; OIDC login from the workstation; NaN models listed. Record in `verification.md`. ✓ 2026-10-04 (verification.md, PR 1 and PR 1b)

### PR 2 — the agent user and its rootless daemon

- [x] [AC2] Measure the daemon half of R3 through the role, never by hand: provision ace2, then assert tasks in the role read the result (`docker info` through the user's socket reports `rootless`, one container runs through it). Each read is `changed_when: false` and `check_mode: false`, the rule `tests/test_dev_node_npm_converges.py` enforces for dev_node. The Hermes half (its `terminal.backend: docker` over that socket) needs the image and config, so it is PR 3's first live step, and R3 is not measured until then. If the daemon half fails, switch the tasks below to Podman's rootless socket.
- [x] [P] [AC2] Test: the user is created with no `sudo` group membership and no sudoers drop-in; the dev user's home is mode `0750` or stricter; the gateway's `DOCKER_HOST` renders to the user's rootless socket and never to `/var/run/docker.sock`. Expected: FAIL.
- [x] [AC2] Tasks: user `hermes-kubelab` (system UID, no login shell beyond what rootless Docker needs), `loginctl enable-linger`, `dockerd-rootless-setuptool.sh install` gated on the socket's absence (`creates:`), subuid/subgid ranges, the user's systemd `docker.service` enabled.
- [x] [AC2] [AC1] Live: `sudo -l -U hermes-kubelab`, the three `Permission denied` reads, `docker info` → `rootless`; second provision `changed=0`.

### PR 3 — hermes-kubelab (needs R1 and the Slack half of R2)

- [ ] [P] [AC3] `tests/test_hermes_config.py`: render `hermes-config.yaml.j2` and assert the D2 keys; feed it every role input and assert none yields `approvals.mode: off`; assert the deny list contains every pattern of `files/guardrails-denylist.yaml`. Expected: FAIL.
- [ ] [AC3] Template `hermes-config.yaml.j2`; copy the deny list from `80_agents/hermes-nan/guardrails-denylist.yaml` into `files/` with a header naming its origin.
- [ ] [AC10] `SECRET_CATALOG` entries under `apps.services.ai.hermes_kubelab.*`: `nan_api_key` (or the shared-key path from R1), `api_server_key` (RANDOM), `slack_bot_token`, `github_token`. `.env` rendered into the user's data dir, `0600`, owned by `hermes-kubelab`.
- [ ] [AC2] `compose-hermes.yml.j2` run by the user's daemon: gateway (`gateway run`, `API_SERVER_ENABLED=true`, `API_SERVER_HOST=0.0.0.0` inside the container, published on `127.0.0.1:8642` only), and the tailscale sidecar (`TS_USERSPACE=true`, state in a volume).
- [ ] [P] [AC5] Test on `policy.hujson.j2`: `tag:hermes` destinations contain nothing on ace2's address and no `:22`, `:6443`, `vps:8080`. Expected: PASS today (it guards the future).
- [ ] [AC5] Preauth key for the sidecar created by the playbook on the VPS with `--tags tag:hermes` under the `agents` user (the existing `_headscale_preauth` task shape, not the infra user). Live: `headscale nodes list` shows the node and tag.
- [ ] [AC4] Add Hermes as Open WebUI's second backend (`http://host.docker.internal:8642/v1`, key = `api_server_key`).
- [ ] [AC2] First live step, the Hermes half of R3: one command run through the sandbox on the user's rootless socket. If it fails, PR 2's tasks move to Podman's socket before anything else in this PR.
- [ ] [AC3] Live: one prompt that needs approval, left unanswered; the log shows the denial after 300 s. Record each refused tailnet destination (R7).

### PR 4 — the vault zone and the jobs

- [ ] [P] [AC6] `tests/test_hermes_vault_hook.py`: run `files/pre-commit-zone.sh` in a temporary git repo against a staged change under `80_agents/hermes-kubelab/` (exit 0) and under `10_projects/` (exit 1). Expected: FAIL.
- [ ] [AC6] The hook; the vault clone task (HTTPS with the vault token, `git config core.hooksPath`); the unit's `ExecStartPre` script that removes `.git/index.lock` only when `pgrep -u hermes-kubelab -x git` finds nothing, then `git pull --ff-only`.
- [ ] [AC6] Seed `80_agents/hermes-kubelab/` in the vault from the portable parts of `80_agents/hermes-nan/` (cronjobs adapted to ace2, guardrails, backup policy), through hive, not by the agent.
- [ ] [AC6] Live: one scheduled job's commit lands under the zone.

### PR 5 — the MCP bridge and retrieval (needs the Drive half of R2)

- [ ] [P] [AC9] Test: the bridge service is on the system daemon, bound to the Docker network only (no published port), with a read-only mount of a vault checkout owned by root and refreshed by the unit, never the agent's clone.
- [ ] [AC9] `mcpo` (pinned) with two servers: a filesystem-read MCP over the vault checkout, and a Drive MCP with `drive.readonly`. Open WebUI tool servers point at it.
- [ ] [AC9] Open WebUI RAG env: `RAG_EMBEDDING_ENGINE=openai`, `RAG_OPENAI_API_BASE_URL=https://api.nan.builders/v1`, `RAG_EMBEDDING_MODEL=qwen3-embedding`, `RAG_EXTERNAL_RERANKER_URL=https://api.nan.builders/v1/rerank`, vector store left at the default.
- [ ] [AC9] Measure R5: one embedding call with `dimensions: 1024`; record the returned length.
- [ ] [AC9] Live: upload a document, ask about it, see the citation and the NaN calls in the log.

### PR 6 — backup

- [ ] [AC7] Check R6 (is BACKUP-057 merged?). Add `ace2` to `backup.sources` with the Hermes data dir and the Open WebUI volume (SQLite declared for both so `node_backup` snapshots them consistently). `tests/test_node_backup_role.py` and the derived inventory group follow.
- [ ] [AC7] Live: `make backup-node NODE=ace2 ENV=staging`, then `restic ls latest` shows both paths.

## Closing

- [ ] Every acceptance criterion is covered by a test or a recorded live measurement
- [ ] Every acceptance criterion has a `features.json` entry with a non-vacuous verification command
- [ ] `make test` and `make lint` pass
- [ ] AC8 measured with the stack idle: `free -m` on ace2
- [ ] [AC11] Power-cycle drill once PR 4 lands (the vault clone and both databases exist): reboot ace2 with the stack running, then record unit state, `git fsck` on the clone and `PRAGMA integrity_check` on both databases under `### Power-cycle drill` in `verification.md`
- [ ] `verification.md` filled in, including R4's refinement of ADR-068 D1
- [ ] ADR-068 amended at archive if R3 or R4 changed what it says
- [ ] Runbook `docs/runbooks/hermes-kubelab.md`: start, stop, approve, rotate a token, restore from R2
- [ ] Independent adversarial review before archive
