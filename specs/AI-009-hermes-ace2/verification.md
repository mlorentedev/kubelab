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
- **The mint gate** asks the running sidecar (`BackendState == Running`), no longer its state file. tailscaled writes that file at its first start, before any login, so a failed first registration would never have been retried (PR-Agent). The steady state was measured: the key is not minted, and the run gives `changed=0`. **Not yet measured live**: a registering run with the same-run recreate, and the re-login of a sidecar that reports `NeedsLogin`. Both need the node logged out or removed first, which waits on the operator. `TS_AUTH_ONCE` does not block the re-login: at the pinned v1.102.5, containerboot runs `tailscale up` with the key whenever tailscaled starts in `NeedsLogin`, state or no state (`cmd/containerboot/main.go`, `authLoop`). It reads the key only at start, so the role recreates the sidecar when a new key is rendered, and `tests/test_hermes_sidecar.py` pins that.
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
- **What it is not**: a guard against mistakes, not against the agent. `git commit --no-verify` skips it. What holds against the agent has to be the vault token's own scope, decided with R2.

### Vault sync, PR 4b (`feat/ai009-vault-sync`), ace2 and the vault remote, 2026-10-08

- **Provision**: `make provision NODE=ace2 ENV=prod TAGS=agent_stack` from the branch: `changed=10` (the sync units, token, clone directory, timer, the Hermes config, the gateway recreate, the old sandboxes removed, and node_maintenance's script and timer, which were behind master and now run under the `agent_stack` tag too). The next run: `changed=0`. The deny list read back with `--env-type local`: every rule refused its command, every allowed command passed.
- **Unit**: `Result=success`, exit 0; timer armed every 15 min. `/opt/agent-stack/vault-token` is `root root -rw-------`. The clone's `.git/config` holds no `credential` line (0 matches).
- **Mounts** (a container on the agent's daemon with the sandbox's exact arguments: Hermes's cap set, `--network=none`, `no-new-privileges`, and the two `-v` strings from the rendered config, which Hermes passes verbatim): it runs as uid 0 in its namespace; a write under `/vault/80_agents/hermes-kubelab/` succeeds and lands on ace2 as `hermes-kubelab:hermes-kubelab 644`; `touch /vault/10_projects/probe` and `touch /vault/.git/probe` fail with `Read-only file system`. Docker's nested read-only parent and writable child hold under rootless.
- **Push**: the next sync pushed the probe as `bfc90b28`, author `hermes-kubelab <hermes-kubelab@ace2>`, one file, under the zone. The sandbox then removed it and the sync pushed the deletion as `457acf70`. The zone's directory stayed on ace2, as the sandbox's mount point.
- **Failure page**: `make maintain-notify-test NODE=ace2 ENV=prod EXTRA='notify_test_unit=hermes-kubelab-vault-sync.service'` started the notifier with the sync unit as its instance, as `OnFailure=kubelab-notify@%n.service` does: `Result=success, ExecMainStatus=0`, so prod n8n answered 2xx and the message was sent.
- **From master after the merge** (af2fdc99, #2130): `make provision NODE=ace2 ENV=prod TAGS=agent_stack` gave `changed=1`, the sync script replaced by the review's fix (a lock is held only by a git whose working directory is the clone), and the role's run of the sync succeeded. The next run: `changed=0`.
- **Not yet measured**: a commit from a scheduled job (needs the seeded zone).

### AC4, Hermes behind Open WebUI (`feat/ai009-webui-hermes`), ace2, 2026-10-08

- **Listener**: `ss -ltnp` shows `172.30.250.1:8642` held by `rootlesskit` (pid 1129), in the host's namespace.
- **ufw is the control**: the provision's probe from a container on `docker0` was refused, and the kernel logged `[UFW BLOCK] IN=docker0 ... SRC=172.17.0.2 DST=172.30.250.1 ... DPT=8642 ... SYN`. The probe on `open-webui` connected through `172.30.250.1 8642/tcp on br-open-webui ALLOW 172.30.250.0/24`. The API read-back answered first, so the refusal cannot come from a dead listener (lesson-542).
- **Backend**: from inside `open-webui`, with its own env, `GET http://172.30.250.1:8642/v1/models` with the second key lists `hermes-agent`. Open WebUI's old `agent-stack-webui_default` network was already gone after the recreate.
- **Boot order**: `agent-stack-hermes-bind.service` enabled, `WantedBy=user@999.service`. The reboot itself is the AC11 drill.
- **Provision**: three runs from the branch, `changed=7` (the network, the recreate, the ufw rule), then `changed=2` (the boot unit, added after the first measurement), then `changed=0`.
- **Tier** (operator, browser, 2026-10-08): the model's visibility matches the decision, listed for an admin and absent for a `users` login.

### Power-cycle drill (AC11), ace2, 2026-10-08

The operator rebooted ace2 remotely with the stack running, after both peer sessions confirmed they were not using it. Booted at 04:16:27 CEST. Every read below is read-only.

- **Order**: `agent-stack-hermes-bind.service` logged `172.30.250.1 is up on br-open-webui after 0s` and exited at monotonic 13.52 s. `user@999.service` went active at 13.70 s, after it. `Result=success`.
- **Units**: `agent-stack-egress`, `agent-stack-webui`, `agent-stack-hermes-bind` and `user@999` are active. `systemctl --failed` is empty. The vault sync ran 2 min after boot with `Result=success`, exit 0, and the next run is armed. The `node-backup-*` timers are armed.
- **Ports**: `rootlesskit` holds `172.30.250.1:8642` and `dockerd` holds `100.64.0.5:3080`. `open-webui` is `healthy`, and `hermes-kubelab` is up on `172.30.250.1:8642->8642/tcp`.
- **Backend**: from inside `open-webui`, with its own env, `/v1/models` lists `hermes-agent`, and one chat completion answered.
- **Clone**: `git fsck` on `/var/lib/hermes-kubelab/vault` as the agent's user: exit 0, no output.
- **Databases**: `PRAGMA integrity_check` opened read-only (`mode=ro`) returns `ok` for Open WebUI's `webui.db` and for Hermes's `state.db`, `shared-state.db`, `kanban.db`, `response_store.db`, `runs_idempotency.db` and `cron/executions.db`.

### Public endpoint (#2142, #2135), prod, 2026-10-08

Rolled out after the merge in the order the PR stated, with one break. The first provision from master failed: `provision-ace2.yml` still read the renamed `break_glass.open_webui`. Until #2145 ran from its branch (`changed=2`, the env file and Open WebUI's recreate), SSO was refused. DNS was applied from the main checkout: the plan showed one create. The create timed out at 30 s but landed, so the record was untainted rather than replaced (lesson-543). The plan then read `No changes`.

- **Route**: `https://chat.kubelab.live/` answers 200 with a verified certificate. The prod e2e suite, filtered to Open WebUI (`-k open_webui`): 5 passed.
- **Password form**: `POST /api/v1/auths/signin` on the public name answers 403.
- **OIDC**: `/oauth/oidc/login` redirects to Authelia with `redirect_uri=https://chat.kubelab.live/oauth/oidc/callback`. Authelia answers with its login flow (`flow=openid_connect`), not a redirect error.
- **CORS**: `Origin: https://chat.kubelab.live` and `Origin: http://ace2.kubelab.internal:3080` are each echoed in `access-control-allow-origin`, and a foreign origin gets none. So Open WebUI parses the two `;`-separated origins.
- **In the e2e suite since #2150**: the three controls above are `tests/e2e/test_open_webui_public.py`, run by `make test-e2e ENV=prod`. The refusal is asserted with ace2 off; the OIDC and CORS tests skip then. Each assertion was mutated and went red.
- **Not yet run**: an interactive login off the tailnet with the tier check, the error page with ace2 off, and `make break-glass SVC=open-webui` (every use pages the operator channel). All three are the operator's.

### AC8, interim, ace2, 2026-10-07

Measured with the stack idle (load 0.04), before PR 4 and PR 5 add the vault clone and the MCP bridge. AC8 is measured again at closing. `free -m`: 1787 MiB used of 11739, 9951 available, no swap used. `docker stats --no-stream`: `open-webui` 654.7 MiB of 1.5 GiB, `hermes-kubelab` 209.2 MiB of 1.5 GiB, `hermes-kubelab-tailscale` 19.0 MiB of 128 MiB, `glances` 107.1 MiB of 256 MiB.

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

- 2026-10-08, PR 4b (operator): the agent writes files and the host commits and pushes (ADR-068 D4 amendment). The token is root's, handed to the sync unit by systemd. The zone's commits carry the identity `hermes-kubelab`, declared in `common.yaml`.
- 2026-10-08, PR 4b: the notifier pairing guard was relaxed from equal tags to the directional rule its hazards need (a consumer's tags within the notifier's, node_maintenance equal to it, every notifier tag selecting a consumer). Equality would have made `TAGS=maintenance` deploy the agent stack.

- 2026-10-08, **open for the operator, blocks PR 3c (AC4)**: tasks.md names `http://host.docker.internal:8642/v1` as Hermes's address for Open WebUI, and that cannot work. Measured on ace2: rootlesskit listens on `127.0.0.1:8642`, and `host.docker.internal` is the host's bridge address, never its loopback. Every way through widens the API past loopback, which `compose-hermes.yml.j2` and `test_the_api_is_published_on_loopback_only` declare as the posture: (a) publish on `docker0` (172.17.0.1) with `host-gateway` in Open WebUI, reachable from every container on the system daemon, and racing `docker.service` for the address at boot; (b) publish on the gateway of Open WebUI's own compose network, a subnet fixed in the SSOT, reachable from that network and still from any container the host routes; (c) a transport that is not a TCP port, such as a unix socket shared into Open WebUI's container. The API key guards all three. A second decision sits behind it: which Open WebUI tier may drive the agent (ADR-062 tiers, Open WebUI's per-model access).

- 2026-10-08, **operator decision, closes the AC4 entry above**: Open WebUI reaches Hermes on the host's address in Open WebUI's own compose network, a bridge whose name, subnet and gateway are declared in `networking.nodes.ace2`. A ufw rule admits that subnet, on that bridge, to that address and port, and nothing else. This rests on one claim to measure first: the agent's daemon publishes through rootlesskit's userspace listener in the host's network namespace, so its traffic crosses INPUT, where ufw applies, unlike the system daemon's DNAT. If a container on another bridge connects, the design stops and goes back to the operator. Unix socket: rejected, neither side supports it (Hermes v2026.9.24 binds only `web.TCPSite`, `gateway/platforms/tcp_site.py:29-57`; Open WebUI v0.11.4 builds its sessions on `aiohttp.TCPConnector`, `utils/session_pool.py:70`). Tier: admins only, by granting nothing. Open WebUI shows a model with no record to admins alone and refuses chat to it for everyone else (`utils/models.py:572-575`, `utils/access_control/__init__.py:361-410`), and `admins` maps to its admin role (`OAUTH_ADMIN_ROLES=admins`).
- 2026-10-08, **operator decision**: Open WebUI gets a public endpoint behind Authelia, so it is usable like a hosted chat from any device. Routed by prod Traefik on the VPS, which is always on, over the tailnet to ace2. ace2 stays on-demand (it is the operator's development node), and the endpoint answers with the error page while it is off. Login is Authelia OIDC alone, with no ForwardAuth on top. This amends ADR-068 D5, which kept it tailnet-only. The name is proposed as `chat.kubelab.live` and is to be confirmed when that PR starts.
- 2026-10-08, **open for the operator, blocks PR 3c (AC3, AC10)**: the Slack tokens are stored and catalogued, but Hermes v2026.9.24 denies every Slack user unless `SLACK_ALLOWED_USERS` lists their member ID (`gateway/authz_mixin.py`, `_principal_authorized`; with no allowlist an unknown DM gets a pairing code, which is state, not IaC). The home channel is an ID too (`SLACK_HOME_CHANNEL`; `SLACK_HOME_CHANNEL_NAME` only labels it). Neither ID is written anywhere in the repo, and reading them with the prod bot token from a workstation would be an uncodified use of a production credential. The operator supplies: (a) the member ID of each Slack user allowed to drive the agent (Profile > Copy member ID), (b) the ID of `#agent-fleet` (channel details, bottom). Both are plaintext and go in `common.yaml`. The AC3 drill then needs the operator in Slack.

- 2026-10-09, AC9 PR 1 (`feat/ai009-vault-mirror`): the bridge's vault is a root-owned mirror in `/opt/agent-stack/vault-mirror` (history in `git/`, notes in `tree/`, so the bridge mounts notes only), refreshed from the remote by `agent-stack-vault-mirror.{service,timer}` at the sync's interval with the sync's token (`LoadCredential`). The unit runs as root with the agent's home in `InaccessiblePaths`, so "never the agent's clone" holds by construction. Live on ace2 from the branch: the first provision failed its own read-back, which looked for the agent's zone, absent from the remote until something is written there; the read-back now checks that a commit was checked out (`git ls-tree HEAD` non-empty). Then `changed=1` (the timer), then `changed=0`. Two decisions for PR 2, derived and not the operator's: the bridge image is built on ace2 (compose `build:`, `FROM` the digest-pinned mcpo `git-788ff92`, v0.0.20, since mcpo publishes no version tags; `npm ci` from a committed lockfile), because runtime `npx` fetches unpinned dependencies at every start and the CI image pipeline is ADR-046's for our own apps; and the tool connection carries no `access_grants`, which Open WebUI v0.11.4 reads as admin-only (`has_connection_access`), the posture already decided for the Hermes model.

- 2026-10-10, AC9 PR 2 (`feat/ai009-vault-bridge`): the MCP bridge is live on ace2. mcpo (`main@sha256:1e82c955...`, the same digest as `git-788ff92`, v0.0.20; `main` so Dependabot can bump the digest) runs `@modelcontextprotocol/server-filesystem@2026.8.31` from a committed lockfile over `vault-mirror/tree` mounted read-only at `/vault`, in Open WebUI's Compose project and on its network, with no published port, a read-only root filesystem, uid 65534, `cap_drop: ALL` and `no-new-privileges`. Open WebUI gets it through `TOOL_SERVER_CONNECTIONS` (bearer, no `access_grants`, so admins only). mcpo reads its key only from `--api-key`, so a launcher passes it in-process (lesson-546). Measured by the provision from inside Open WebUI's container, with the key Open WebUI holds: 401 without the key, 10 read tools in the spec and no writer, `list_directory /vault` 200 and non-empty, and the break-glass admin's `GET /api/v1/tools/` lists `server:vault`. Memory 84 MiB of 256m. The key is on no cmdline, and the only host processes as uid 65534 are the bridge's two. Provision from the branch `changed=7`, then `changed=0`; a dry run `failed=0`. The dry run found that every generated key's read failed on a node that never had the key (the `openssl` is skipped), the session and Hermes keys included; all three now tolerate it, pinned by `test_every_generated_key_survives_a_fresh_nodes_dry_run`.
- 2026-10-10, **finding, ticketed as #2161 (SEC-028)**: the agent's egress table refuses the tailnet only, so the agent's user reaches Open WebUI's network by container address: Open WebUI's backend 200, the bridge 401. The fix has a trap (Hermes's replies leave from the agent's user towards that subnet's gateway) and is its own PR.

- 2026-10-10, #2161 (SEC-028), derived and reversible: the agent's user is refused every private range for connections it opens: `networking.trusted_cidrs` (RFC 1918 and the tailnet), the IPv6 tailnet prefix, and Docker's address pool (`docker_address_pool_base`, public space until #2136). Nothing in R7 or ADR-068 names a LAN destination a job needs; the operator would revisit this only for one that does. `ct state new`, because Hermes answers Open WebUI from the agent's uid towards the bridge gateway (lesson-548). Live on ace2 from the branch: `changed=2`, then `changed=0`. The provision proves the LAN address and Open WebUI's container address refused to a container of the agent's daemon, each first proven open as root. By hand, as the agent's user on the host, refused: Open WebUI `172.30.250.3:8080`, the bridge `.2:8000`, rpi4 `:80`, Beelink `:22`, ace2 `172.16.1.5:22` and `172.17.0.1:22`; open: `1.1.1.1:443`. Open WebUI still reaches Hermes, the sidecar is `Running` as `tag:hermes` (its peers had no direct LAN path before the rule: all relayed), and the vault sync ran `Result=success`. Not covered: IPv6 link-local (`fe80::/10`) to LAN neighbours from the agent's host processes; the rootless daemon's containers have no IPv6 (slirp4netns runs without it), and ace2 has no global IPv6 besides the tailnet.

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
