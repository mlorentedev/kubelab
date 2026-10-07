---
tags: [spec, verification, templates]
created: "2026-09-30"
---

# Verification - AI-009-hermes-ace2

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Live measurements

### PR 1 (`feat/ai009-agent-stack`), staging ace2, 2026-10-01

- **Unconfigured path** (no OIDC secret in prod SOPS): `make provision NODE=ace2 ENV=staging TAGS=agent_stack` twice: `changed=2` (directory, session key), then `changed=0`. Open WebUI not started; the play names the missing key.
- **Configured path**, with `EXTRA='agent_stack_webui_oidc_client_secret=<placeholder>'` so the deploy block runs before the real client exists (OIDC cannot succeed with it and the login form is off, so no account can be created). First pass `changed=7`, health check green after ~6 retries; second pass `changed=0`.
- **AC4 bind**: `http://100.64.0.5:3080/health` → 200; `http://172.16.1.5:3080/health` → no listener.
- **AC8**: Glances container API, 3 min after start, idle: cgroup usage 1489 MiB, of which 591 MiB is reclaimable page cache, so a working set of 897 MiB against the 1536 MiB limit. Node available memory 10073 of 11739 MiB. Open WebUI loads its local embedding model at start; PR 5's `RAG_EMBEDDING_ENGINE=openai` should lower this, and AC8 is re-measured then.
- **Teardown**: provision again without the placeholder: the container is taken down and `compose-webui.yml` and `webui.env` are removed (`changed=3`); next pass `changed=0`; port 3080 has no listener.

### PR 2 (`feat/ai009-agent-user`), staging ace2, 2026-10-01

- **AC1**: `make provision NODE=ace2 ENV=staging TAGS=agent_stack` first pass `changed=6` (packages, user, home mode, subuid and subgid, linger, setup tool). The next three passes `changed=0`, and `CHECK=1` `changed=0 failed=0`.
- **AC2, daemon half of R3**: the role's asserts pass on every run. `docker info` through `unix:///run/user/<uid>/docker.sock` reports `name=rootless`. A `busybox` container started with `--memory 64m --cpus 0.5` reads back `67108864` from `memory.max` and `50000 100000` from `cpu.max`, so the user's cgroup has the memory and cpu controllers with no `user@.service` drop-in. The Hermes half of R3 is still open, and PR 3's first live step settles it.
- **AC2, isolation**: as `hermes-kubelab`, `test -r` fails on the dev user's `~/.config/gh/hosts.yml`, `~/.ssh` and `~/.kube`, and on `/var/run/docker.sock`. The dev user's home is mode `750`. `sudo -l -U hermes-kubelab` reads "is not allowed to run sudo".
- **Subordinate ids**: `hermes-kubelab:524288:65536` in both files, next to `manu:100000:65536`. The first pass's overlap assert looped over nothing (a folded YAML scalar kept `'\n'` literal, lesson-494). It now runs against `manu`'s line, after a positive control that requires the agent's own line.

### PR 1b (#2058), prod Authelia, ace2, 2026-10-04

- **AC4, provision**: `make provision NODE=ace2 ENV=staging TAGS=agent_stack` after Argo CD synced `e9def69a` to prod and Authelia restarted on the new config. First pass `changed=4`, rc 0; second pass `changed=0`.
- **Break-glass**: the role's post-start check reads `breakglass@kubelab.live signs in as admin` on every pass.
- **First OIDC login** (operator, from the tailnet): sign-in through Authelia succeeded, so Authelia accepts the client's `client_secret_basic`; a mismatched method fails `invalid_client`. The operator, in `admins`, landed as admin (Admin Panel present), so `groups` reached Open WebUI through UserInfo, the premise of `OAUTH_USERNAME_CLAIM=preferred_username`.
- **No models**: `ENABLE_OPENAI_API` renders false with no NaN key in the vault, so the model list is empty. Settled by R1 below.
- **Models, after R1** (`feat/ai009-webui-nan-key`): provision `changed=2` (env file, container), then `changed=0`. `GET /api/models` through a break-glass session lists 14: the 13 NaN models (chat, embedding, rerank, speech and image) plus Open WebUI's built-in `arena-model`.

### PR 1c (`feat/ai009-webui-access-review`), prod, 2026-10-06

- **Access-review shape, from the v0.11.4 source**: every request loads the user from the database (`utils/auth.py:455`), only `user` and `admin` are verified roles (`utils/auth.py:567`), and `POST /api/v1/users/{id}/update` edits an OAuth account's role. So the review edits the role and reads it back (`fixed`), Gitea's shape; the session revocation Grafana needs (`bounded`) is not required.
- **`make auth-review ENV=prod`** (read-only), rc 0: Open WebUI lists `breakglass` admin OK and `manu` admin OK. `operator` has no Open WebUI account yet (it has never signed in). Every other app as before. Every Open WebUI account already matched its tier, so the `APPLY=1` edit-and-read-back path is covered by `tests/test_access_review.py` against the v0.11.4 API shape, not yet by a live correction of a drifted account.
- **Probes through the SSOT** (review fix, 2026-10-07): `make provision NODE=ace2 ENV=staging TAGS=agent_stack` with both probes built from `scheme`, `default_port` and `health_path`: `ok=60 changed=0 failed=0`, the health probe answered and the break-glass account signed in as admin.
- **`OAUTH_UPDATE_EMAIL_ON_LOGIN=true`** (review fix, 2026-10-07): v0.11.4 matches an OIDC account by its subject and keeps its first email unless this is on (`utils/oauth.py`), so a moved email would strand the account as `undeclared`. Provision `changed=2` (env file, container), then `changed=0`. `make auth-review ENV=prod` afterwards: `breakglass` and `manu` admin OK.
- **Monitor**: `make monitoring-apply` created `services-ai-open-webui`; its first beat was UP, `200 - OK`, with no notification attached (`on-demand` is muted). The same apply deleted the hand-made `Leaving Denver` monitor, absent from the seed: it is now declared (`services-leaving-denver`), re-created by a second apply (`1 create, 0 delete`) and UP. The defect is #2078.

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- 2026-10-03, PR 1b (operator): tiers are `admins` → admin, `users` → user, anyone else refused; break-glass is a local `breakglass` account with the login form on for it alone; `ENABLE_PERSISTENT_CONFIG=false`, so the env file is the configuration of record.
- 2026-10-03, PR 1b: the OIDC pair was minted on 2026-10-02, before ace2 is in `backup.sources`, which reverses AC7's order. Merging PR 1b is safe; provisioning Open WebUI for real use still waits for PR 6, because nothing it would hold is backed up until then.
- 2026-10-03, PR 1b: access tiers in `make auth-review` and the Uptime Kuma monitor move to PR 1c. Both need the service running.
- 2026-10-04 (operator): Open WebUI was provisioned for use before PR 6, on the condition that its chats are disposable until ace2 is in `backup.sources`.
- 2026-10-04, R1 for Open WebUI (operator): it shares PR-Agent's NaN key, `apps.services.automation.pr_agent.nan_api_key`, read from prod's vault by the playbook, with no second copy. The cost is a shared rate limit: chat traffic and PR reviews draw on the same per-key quota. Hermes (PR 3) still needs its own R1 answer: share the same key, or mint a second one.
- 2026-10-06, PR 1c (operator): the declared viewer tier is `pending`, Open WebUI's no-access role, so a demotion out of `users` removes access instead of leaving a `user`.
- 2026-10-06, PR 1c: the role's post-start probe and the monitor read `apps.services.ai.open_webui.health_path`, and `tests/test_hub_monitors.py` ties the monitor URL to the SSOT, so AI-010 (#2069) cannot move the address without moving the monitor.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/AI-009-hermes-ace2/` -> `specs/archive/AI-009-hermes-ace2/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
