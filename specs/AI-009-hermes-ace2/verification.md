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
- **`OAUTH_UPDATE_EMAIL_ON_LOGIN=true`** (review fix, 2026-10-07): v0.11.4 matches an OIDC account by its subject and keeps its first email unless this is on (`utils/oauth.py`), so a moved email would strand the account as `undeclared`. Provision `changed=2` (env file, container), then `changed=0`. `make auth-review ENV=prod` afterwards: `breakglass` and `manu` admin OK. That measures that the setting landed and that logins still work, not that a moved email is adopted: no account's email has moved, so the setting was not exercised, and the same review passes without it. A collision with another account's address is logged and keeps the old email (v0.11.4 `utils/oauth.py`, read, not exercised).
- **Monitor**: `make monitoring-apply` created `services-ai-open-webui`; its first beat was UP, `200 - OK`, with no notification attached (`on-demand` is muted). The same apply deleted the hand-made `Leaving Denver` monitor, absent from the seed: it is now declared (`services-leaving-denver`), re-created by a second apply (`1 create, 0 delete`) and UP. The defect is #2078.

### PR 3a (`feat/ai009-hermes`), staging ace2, 2026-10-06

- **Provision**: first run `changed=9` (key, data dir, env, config, compose, the two pulls, the start), then `changed=0` after the read-only config fix below. Runs 5 and 6, after the sandbox network change: `changed=2`, then `ok=72 changed=0`.
- **API**: `GET /v1/models` on `127.0.0.1:8642` with the generated key answers 200 within the role's retries.
- **Deny list, through the running gateway**: `docker exec -u hermes hermes-kubelab hermes approvals test --env-type docker --json` returns `user-deny` for one command of each of the 5 rules and `allow` for all 7 allowed commands, at every provision. Before the role, the 20 example commands were run through the pinned image's evaluator with the globs: 20/20 as declared. With a config the image could not load (a data dir its user could not write), the same evaluator logged `Failed to load approval config`, carried on, and returned `allow` for every one of them.
- **R3, the Hermes half: passed.** `hermes -z` asked the gateway to run `uname -a; id; cat /etc/os-release; hostname` through its terminal tool. The output came from a `python:3.13.16-trixie` container (Debian 13, not ace2's Ubuntu) that the gateway had started on the agent's daemon: `uid=0` inside, `hermes-kubelab` (999) on the host. That container held `Memory=1073741824` and `NanoCpus=1000000000`, received 4 environment variables, all from the image (none from the gateway), and its mounts resolved to real paths under `/var/lib/hermes-kubelab/data`, which proves the same-path mount works for Docker-out-of-Docker. Rootless Docker stays; Podman is not needed. The sandbox gets no Docker socket. On 2026-10-07 the running sandbox (`hermes-300e165d`, after `docker_network: false`) had 13 bind mounts, each one under `/var/lib/hermes-kubelab/data` (its `home` and `workspace` read-write, attachments, images, skills and caches read-only), and `NetworkMode=none`. Neither `/var/run/docker.sock` nor `/run/user/<uid>/docker.sock` was among them. So a command in the sandbox cannot reach the gateway's daemon, and so cannot reach the gateway's environment either.
- **The image takes `config.yaml`**: after the first start, `$HERMES_HOME/config.yaml` was `534287:534287 640` (the image's user through the subuid map), and a migration may rewrite it. The config is now rendered beside the data dir and mounted read-only over that path; the gateway logs `[config-migrate] ERROR: Read-only file system` and continues.
- **R7, the sandbox's tailnet reach**: from the agent's daemon, before the change, a container's TCP connects to the VPS's `:22` and `:6443`, ace1's `:6443`, the Beelink's `:3000` and ace2's `:3080` all opened; `1.1.1.1:443` opened; ace1's LAN address timed out. After `docker_network: false`, the sandbox Hermes started was `NetworkMode=none` and `connect_ex` to the VPS's `:22` returned 101 (network unreachable).

### PR 3b-1 (`feat/ai009-hermes-egress`), ace2, 2026-10-07

- **Before**: from a busybox container of the agent's daemon, `nc -z` to the VPS's tailnet `:443` and to its public `:443` both returned 0.
- **Rule**: table `inet agent_egress`, `meta skuid 999 ct original ip daddr 100.64.0.0/10 reject` and the same for `fd7a:115c:a1e0::/48`, loaded by `agent-stack-egress.service`, which `user@999.service` requires (`systemctl list-dependencies --reverse`).
- **The DNAT gap** (lesson-527): with a plain `daddr` rule, every tailnet destination was refused except ace2's own Open WebUI at `100.64.0.5:3080`, which the system daemon DNATs before the filter hook. With `ct original`, it is refused too.
- **After**, `connect_ex` from the gateway container `hermes-kubelab`: the VPS's `:22`, `:443` and `:6443`, ace1's `:6443`, the Beelink's `:443`, ace2's `:3080` and MagicDNS `:53` all return 11 (timeout: slirp4netns does not relay the ICMP reject). The VPS's public `:443` returns 0. `api.nan.builders` resolves through the public resolvers. The Hermes API answers 200 on `127.0.0.1:8642`.
- **Provision**: `changed=6` then `changed=0` (prod config), then `changed=2` for the NAT fix, `changed=0`, and `changed=0` with `ENV=staging`: the two render the same role. The three probes run at every provision; the one on ace2's own published port runs only when Open WebUI is configured.
- **Fail closed, measured**: `systemctl stop agent-stack-egress` left `user@999` and the rule both `inactive`, with no `agent_egress` table. `systemctl start user@999` brought the rule back (`active`, 2 rules) and the gateway with it: the Hermes API answered 200 about 10 s later, with no provision. The next provision reported `changed=0`.
- **DNS**: the gateway was recreated with `HostConfig.Dns=[1.1.1.1 8.8.8.8]`, and a lookup took 0.02 s.

### PR 3b-2 (`feat/ai009-hermes-sidecar`), prod Headscale, ace2, 2026-10-07

- **Registration**: the first provision minted a single-use key with `--tags tag:hermes` under the `agents` user (id 4), and `tailscale/tailscale:v1.102.5` registered on Headscale 0.28.0 on its first try. `headscale nodes list` shows node 68, `hermes-kubelab`, `100.64.0.16`, tags `tag:hermes`, user `tagged-devices`. Headscale lists every tagged node under that pseudo-user, never under the user that minted the key.
- **The uid rule does not break it.** The sidecar runs on the agent's daemon, so its traffic is uid 999's. It still reaches `Running`, because control, DERP and WireGuard endpoints all use public or LAN addresses, and `vpn.kubelab.live` resolves to the VPS's public address.
- **ACL, read from the sidecar** with `tailscale nc`: the VPS's `:443` connected (rc 0). The VPS's `:22` and `:6443`, and ace2's `:3080` and `:22`, never answered (killed at 6 s). The sidecar uses 20 MiB of its 128 MiB.
- **Idempotence**: `changed=7` to register, then `changed=1`, then `changed=0`. The `changed=1` was Compose recreating the sidecar after the env file was emptied. An env file's content is in Compose's hash, which the role's comment had said it was not. The role now recreates the sidecar in the run that registers it. The steady state then gave `changed=0` again.
- **The mint gate** asks the running sidecar (`BackendState == Running`), no longer its state file. tailscaled writes that file at its first start, before any login, so a failed first registration would never have been retried (PR-Agent). The steady state was measured: the key is not minted, and the run gives `changed=0`. **Not yet measured live**: a registering run with the same-run recreate, and the re-login of a sidecar that reports `NeedsLogin`. Both need the node logged out or removed first, which waits on the operator.
- **Stale tagged record found**: `hermes-nan` (node 22, `tag:hermes`, last seen 2026-07-22) still holds the tag with a key that never expires. Added to #1573.

### PR 5a (`feat/ai009-webui-rag`), NaN, ace2, 2026-10-07

- **NaN answers Open WebUI's own client.** v0.11.4 embeds and reranks with `requests` (`retrieval/utils.py`, `retrieval/models/external.py`). Its default UA, `python-requests/2.34.2`, measured from inside the `open-webui` container, got 200 from NaN. The 403 (Cloudflare `error code: 1010`) found for R5 was Python urllib's UA, not this one.
- **Shapes**: `/v1/models` lists `qwen3-embedding` and `rerank`. A batch of 16 inputs returns 16 vectors. `/v1/rerank` returns `results[].index` and `relevance_score`, the shape `ExternalReranker` parses.
- **R5, the width**: one `qwen3-embedding` call from inside the container, `requests` UA, returned 4096 values without `dimensions` and 1024 with `dimensions: 1024`, both 200. NaN honours the parameter, which a move to pgvector (2000-dimension index limit) would need. v0.11.4 sends no `dimensions`, so the vectors Open WebUI stores are 4096 wide. Chroma, the default store, takes any width. No `file` or `knowledge` rows existed before the switch, so no collection was embedded by the local MiniLM (384 wide), which a query would have failed on.
- **The reranker needs hybrid search.** v0.11.4 calls it only when `rag.enable_hybrid_search` is on (`query_collection`, `retrieval/utils.py:714`). A config with the external reranker but no `ENABLE_RAG_HYBRID_SEARCH` would never call it. The spec's PR 5 line did not list that variable.
- **Live**: provision `changed=2`, then `changed=0`. Inside the running container, with its own env, v0.11.4's `generate_openai_batch_embeddings` returned 2×4096 and `ExternalReranker.predict` scored "the sky is blue" 0.8883 and "grass is green" 0.0001 for "what colour is the sky". Memory went from 654.7 MiB to 639.2 MiB after the restart: no local model was loaded at start (`get_ef` returns `None` when the engine is set).
- **Not yet measured**: an upload and a question through the UI with a citation (spec AC9, last PR 5 line). It needs a signed-in user, and the only local account is break-glass, whose every use pages the operator.
- **Query text in logs**: `ExternalReranker` logs each query at INFO, and v0.11.4 has only `GLOBAL_LOG_LEVEL` to change that. The text stays in ace2's local Docker logs; no shipper reads them.
- **Found, ticketed**: v0.11.4 runs with `CORS_ALLOW_ORIGIN=*` and `allow_credentials=True` (it logs a warning at every start). #2109.

### PR 4a (`feat/ai009-vault-zone-hook`), ace2, 2026-10-07

- **Installed**: the first provision installed `/usr/local/libexec/agent-stack/vault-hooks/pre-commit` (`changed=2`, the directory and the hook), and the next run gave `changed=0`. Read back on ace2: both are `root 755`, so the agent's user cannot rewrite its own guard.
- **Behaviour** is measured by `tests/test_hermes_vault_hook.py` against a real git repository, not on ace2: the clone it guards does not exist until the vault token lands (R2). Wiring `core.hooksPath` into that clone is part of the clone's own task.
- **What it is not**: a guard against mistakes, not against the agent. `git commit --no-verify` skips it. The boundary that holds is the token's scope on the forge.

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- 2026-10-03, PR 1b (operator): tiers are `admins` → admin, `users` → user, anyone else refused; break-glass is a local `breakglass` account with the login form on for it alone; `ENABLE_PERSISTENT_CONFIG=false`, so the env file is the configuration of record.
- 2026-10-03, PR 1b: the OIDC pair was minted on 2026-10-02, before ace2 is in `backup.sources`, which reverses AC7's order. Merging PR 1b is safe; provisioning Open WebUI for real use still waits for PR 6, because nothing it would hold is backed up until then.
- 2026-10-03, PR 1b: access tiers in `make auth-review` and the Uptime Kuma monitor move to PR 1c. Both need the service running.
- 2026-10-04 (operator): Open WebUI was provisioned for use before PR 6, on the condition that its chats are disposable until ace2 is in `backup.sources`.
- 2026-10-04, R1 for Open WebUI (operator): it shares PR-Agent's NaN key, `apps.services.automation.pr_agent.nan_api_key`, read from prod's vault by the playbook, with no second copy. The cost is a shared rate limit: chat traffic and PR reviews draw on the same per-key quota. Hermes (PR 3) still needs its own R1 answer: share the same key, or mint a second one.
- 2026-10-05, R1 for Hermes (operator): it shares the same key. ADR-068 D7's routing discipline applies: `cron.model` and `delegation.model` are `apps.services.ai.hermes_kubelab.models.unmetered` (`qwen3.6`), and a test fails if either changes.
- 2026-10-06, PR 3a: the sandbox image is `python:3.13.16-trixie`, not Hermes's default `nikolaik/python-nodejs:python3.11-nodejs20`, because that image is rebuilt daily under the same tag and cannot be pinned by tag (Renovate's coverage test reads tags only).
- 2026-10-06, PR 3a: `approvals.mode: manual` prompts for nothing the sandbox runs, because v2026.9.24 skips command guards on an isolated docker backend. The deny list is the guard, and the provision proves it on the running gateway. AC3's drill is re-scoped in `tasks.md`.
- 2026-10-06, PR 3a: the sandbox has no network until PR 3b gives it its own tailnet identity, because Docker's egress from ace2 reaches the tailnet as ace2 (measured above), which R7 assumed it did not.
- 2026-10-07, PR 3b (operator): the agent's tailnet egress is closed on the host by uid, not by moving the gateway into the sidecar's namespace. A `TS_USERSPACE=true` sidecar has no TUN device, so a container sharing its namespace still reaches `100.64.0.0/10` through slirp4netns as ace2; only the sidecar's SOCKS5/HTTP proxy carries `tag:hermes`. The sidecar stays userspace (PR 3b-2), and a job that needs a tailnet destination goes through its proxy. Hermes's containers resolve through public resolvers only, since MagicDNS is inside the refused range.
- 2026-10-07, PR 3b-2: the sidecar's state is a bind mount beside the data directory, not a named volume. The provision reads it to decide whether to mint a key, and the gateway's container cannot see the node key. Its preauth key lives in its own env file, emptied once the node is registered, so the gateway never receives it. Whether a job uses the proxy, and how, is left to PR 3c.
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
