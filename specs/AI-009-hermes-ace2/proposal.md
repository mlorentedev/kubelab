---
id: "AI-009-hermes-ace2"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-09-30"
issue: "mlorentedev/kubelab#1933"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# AI-009: hermes-kubelab and Open WebUI on ace2

## Why

<!-- from issue #1933: AI-009: Centralized Agentic & Knowledge Hub on ace2 (Hermes, Open WebUI, Vault & GDrive MCP) -->

The Hermes agent that ran on NaN is retired. Its jobs (vault apply and capture, curation, digests) and its chat have had no home since 2026-08-23. [ADR-068](../../docs/adr/adr-068-ace2-operator-agent-tooling.md) decided where they go: an instance named `hermes-kubelab`, Open WebUI and an MCP bridge on ace2, on-demand, under the posture ADR-058 D3 requires for an autonomous agent. This spec turns the eight decisions of ADR-068 into IaC that can be provisioned, re-run with `changed=0`, and verified by command.

## What

After this spec, `make provision NODE=ace2 ENV=staging` produces:

1. **An agent runtime the agent cannot escape to the host.**
   - A Unix user `hermes-kubelab` with no sudo and no access to the dev user's home, which holds the staging credentials ADR-058 D3 allows (`gh`, the Gitea SSH key, kubeconfigs).
   - A rootless Docker daemon owned by that user. The Hermes gateway and its `terminal.backend: docker` sandbox both run on it, so the socket Hermes drives is not root on ace2.
2. **`hermes-kubelab`, the agent** (ADR-068 D2-D4).
   - The `nousresearch/hermes-agent` image, pinned by version in `common.yaml`, running `gateway run`.
   - `config.yaml` rendered by Ansible: `approvals.mode: manual`, `timeout: 300`, a `deny:` list carried from `80_agents/hermes-nan/guardrails-denylist.yaml`, `terminal.backend: docker` with `docker_forward_env: []`, `cron.catch_up_missed: true`.
   - The API server on `:8642`, published on `127.0.0.1` only, with `API_SERVER_KEY` from SOPS.
   - A userspace tailscale sidecar that joins the tailnet as its own node carrying `tag:hermes`.
   - Its own vault clone, written only under `80_agents/hermes-kubelab/`, enforced by a pre-commit hook. The systemd unit's `ExecStartPre` removes a stale `.git/index.lock` only when no git process runs, then runs `git pull --ff-only`.
   - Slack `#agent-fleet` as its channel, which is also where approval prompts arrive.
3. **Open WebUI** (ADR-068 D5).
   - On the system Docker daemon, bound to ace2's Tailscale address only.
   - Its own OIDC client in `apps.services.security.authelia.oidc_clients`, against prod Authelia.
   - Two backends: Hermes's API, and NaN's models.
   - SQLite in WAL mode on a volume.
   - Native RAG only for uploads and Drive documents, with NaN's `qwen3-embedding` and `rerank`.
4. **An MCP bridge** (ADR-068 D6). An `mcpo`-class stdio-to-HTTP bridge serves Open WebUI two read-only tools: the vault and Google Drive.
5. **Backup** (ADR-068 D8). ace2 joins `backup.sources` with the Hermes state and the Open WebUI volume, so `node_backup` ships them to R2.

Every image is pinned in `common.yaml`, and every credential is a `SECRET_CATALOG` entry delivered by the role.

## Out of scope

- Indexing the vault in Open WebUI. The vault reaches chat only through the read-only MCP tool until #299, #395 and #396 build `/v1/knowledge/search` (ADR-043, ADR-068 D5).
- A public route, a Cloudflare record or TLS for Open WebUI. There is no IngressRoute and no `dev.kubelab.live` path (ADR-068 D5); R8 records why it is plain HTTP over the tailnet.
- A second Hermes on NaN (ADR-068 O4 trigger), and any always-on agent.
- Tokens beyond the four of ADR-068 D3 (vault GitHub token, inference key, Slack bot token, Drive read-only OAuth). A Gitea, Grafana or `toolkit-mcp` token is a later change, made when a job needs it.
- Fixing the `dev_node` role's convergence. That is #1300, a prerequisite tracked on its own ticket (task 0).

## Risks / open questions

Items marked **BLOCKING** must be resolved before the PR that depends on them is merged. None blocks PR 1.

- **R1, operator, BLOCKING for PR 3: the inference key.** ADR-068 D7. The operator checks in the NaN console whether a second key can be minted.
  - If yes, it becomes `apps.services.ai.hermes_kubelab.nan_api_key` in `SECRET_CATALOG`.
  - If no, the shared-key path of D7 applies, and the key's single home is decided in its own ticket first.
- **R2, operator, BLOCKING for PR 3 and PR 4: three more credentials.**
  - A Slack bot token for `#agent-fleet`.
  - A GitHub fine-grained token scoped to the vault repository, contents read and write.
  - A Google OAuth client with the `drive.readonly` scope.
  The role ships with a "not configured" path for each (`default('')`, the `dev_node` idiom), so the stack provisions without them and the affected feature reports itself disabled.
- **R3, measured in PR 2, not blocking: the Hermes Docker backend on a rootless socket.** Upstream documents the Docker terminal backend, not a rootless daemon under it. PR 2's first task runs the sandbox through the rootless socket and records the result. If it fails, the fallback is Podman's Docker-compatible socket, also rootless. A rootful socket is not a fallback, because it breaks ADR-068 D2.
- **R4, decided here: Open WebUI and the bridge run on the system daemon, not the agent's.** ADR-068 D1 says "one Compose stack". Taken literally, the agent's rootless daemon would also run Open WebUI. The agent could then `docker exec` into it and read every chat, the OIDC client secret and the NaN key. So the agent's daemon runs only the agent: the gateway, its sandbox and its tailscale sidecar. Open WebUI and the bridge run on the system daemon, like every other node service. They are two Compose projects owned by one role. That is a refinement of D1, recorded in `verification.md` and on the ADR at archive.
- **R5, measured in PR 5, not blocking: the embedding dimension.** `qwen3-embedding` returns 4096 dimensions. Open WebUI's default vector store is Chroma, which has no 2000-dimension index limit. pgvector, which has one, is not used here. PR 5 records whether NaN honours a `dimensions` parameter, for the day the store moves to pgvector.
- **R6, coordination: BACKUP-057 (#1920) changes the backup layout to one R2 bucket per node.** If it lands first, ace2 needs its own bucket and token. Its spec derives them from `backup.sources`, so ace2 follows the declaration. If this lands first, ace2 is migrated with the other nodes. PR 6 checks which state master is in before it starts.
- **R7: the `tag:hermes` destinations.** Today's grant is `vps:443`, written for a NaN pod reaching Gitea and Ollama. PR 3 runs the jobs with the existing rule and records each refused destination. The rule changes only for a destination a job needs, and each addition names the job. Internet destinations (NaN, GitHub, Slack, Google) go out through Docker's normal egress, not through the tailnet, so they need no ACL row.

- **R8, decided here: Open WebUI is served over plain HTTP on the tailnet, at ace2's MagicDNS name.** The transport is WireGuard, so the traffic is encrypted end to end between tailnet nodes. Authelia accepts an `http` redirect URI for any host (its client docs allow `http` or `https`, with no loopback rule). The redirect URI is `http://<ace2 MagicDNS name>:<port>/oauth/oidc/callback`, so it does not change when the address does.
  - The alternative is TLS on ace2: the `pihole.kubelab.live` pattern (OPS-022), a DNS-only Cloudflare record to a Tailscale address. It was rejected for this node. That pattern terminates TLS in staging Traefik on ace1, which is O2's dependency. Terminating on ace2 instead needs a DNS-01 Cloudflare token on the node that hosts the agent: a credential that can edit the zone, on the box with the largest attack surface.
  - Reopen when a browser feature Open WebUI needs requires a secure context (microphone input, clipboard), or when the chat leaves the tailnet.
  - **Cost found while planning PR 1:** `toolkit/features/oidc_clients.py:112` renders every redirect as `https://{host}{path}`, so R8 needs an optional `redirect.scheme` and a port in the SSOT. `tests/test_break_glass.py` derives which services need a break-glass entry from each client's redirect host. A host that no route serves has to be handled explicitly there, not left to fall through.

## Acceptance criteria

- [ ] **AC1. The node converges.** Two consecutive `make provision NODE=ace2 ENV=staging` runs: the second reports `changed=0` for every task of the new role, shown with the per-task result lines.
- [ ] **AC2. The agent cannot reach the host or the dev user's credentials.**
  - `sudo -l -U hermes-kubelab` lists no rule.
  - As `hermes-kubelab`, reading the dev user's `~/.config/gh/hosts.yml`, Gitea key and `~/.kube` fails with `Permission denied`.
  - `docker info` on the agent's socket reports `rootless`.
  - A test fails if the role's template can render a rootful socket path into the gateway's service.
- [ ] **AC3. Approval fails closed.**
  - A test renders `config.yaml` and asserts `approvals.mode: manual`, `timeout: 300`, the deny list, `terminal.backend: docker` and `docker_forward_env: []`.
  - It also fails if any input can render `approvals.mode: off`.
  - Live: a command that needs approval and gets no answer is denied after 300 s. The Hermes log line is the evidence.
- [ ] **AC4. Open WebUI is reachable on the tailnet only, behind prod Authelia.**
  - `ss -tlnp` on ace2 shows its port bound to the Tailscale address only.
  - From the workstation over the tailnet, `http://<ace2 MagicDNS name>:<port>` redirects to `auth.kubelab.live`, and the callback returns to the same name.
  - After login, both backends list models.
  - `tests/test_oidc_clients.py` passes with the new client.
- [ ] **AC5. The agent's network identity is its own.**
  - `headscale nodes list` shows a `hermes-kubelab` node with `tag:hermes`, distinct from `ace2`.
  - A test asserts the policy grants `tag:hermes` no destination on ace2's address, and no `:22`, `:6443` or `vps:8080`.
- [ ] **AC6. The agent writes only its own vault zone.**
  - A test runs the pre-commit hook against a commit touching `80_agents/hermes-kubelab/` (accepted) and one touching `10_projects/` (refused).
  - Live: a scheduled job's commit lands in the vault repository under that path.
- [ ] **AC7. State is backed up.** `make backup-node NODE=ace2 ENV=staging` ships a snapshot whose `restic ls` lists the Hermes state directory and the Open WebUI database.
- [ ] **AC8. The dev node keeps its room.**
  - Every service in both Compose projects declares a memory limit of at most 1.5 GB, asserted by a test.
  - With the stack running and idle, `free -m` on ace2 reports at least 4 GB available.
- [ ] **AC9. Chat retrieval runs on NaN, and the store is ours.**
  - Uploading a document to Open WebUI and asking about it returns an answer citing it.
  - The embedding and rerank calls go to `api.nan.builders`, shown in the Open WebUI log.
  - The vector data sits in the Open WebUI volume.
- [ ] **AC10. Credentials come from SOPS and stay out of reach.**
  - Every token the stack uses is a `SECRET_CATALOG` entry and passes `make secrets-audit ENV=staging`.
  - None is readable by the dev user. The rendered env files are mode `0600`, owned by the consuming user.

## References

- Bitácora: #1933 (this spec), #1300 (prerequisite), #1920 (BACKUP-057, R6), #1272 (unattended delivery on the dev node)
- ADRs: [ADR-068](../../docs/adr/adr-068-ace2-operator-agent-tooling.md) (the decision), [ADR-058](../../docs/adr/adr-058-ace2-dev-node.md) D3, [ADR-041](../../docs/adr/adr-041-agent-fleet-vpn-segmentation.md), [ADR-043](../../docs/adr/adr-043-unified-knowledge-memory-plane.md), [ADR-062](../../docs/adr/adr-062-platform-identity-model.md), [ADR-044](../../docs/adr/adr-044-unified-notification-routing-fabric.md)
- Vault: `80_agents/hermes-nan/` (cronjobs, guardrails, backup policy), `10_projects/kubelab/30-architecture/agent-host-reference-audit.md`
- Upstream: github.com/nousresearch/hermes-agent `website/docs/user-guide/docker.md` (image `nousresearch/hermes-agent`, data at `/opt/data`, UID 10000), `user-guide/messaging/open-webui.md` (`API_SERVER_ENABLED`, `API_SERVER_KEY`, `API_SERVER_HOST`, port 8642)
