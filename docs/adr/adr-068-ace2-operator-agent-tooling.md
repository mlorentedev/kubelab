---
id: "adr-068"
type: adr
status: accepted
owner: manu
date: "2026-09-30"
issue: "kubelab#1933"
tags: [architecture, decision, agents, hermes, open-webui, mcp, ace2, topology, security, knowledge]
depends_on: [adr-028-operational-topology, adr-041-agent-fleet-vpn-segmentation, adr-043-unified-knowledge-memory-plane, adr-058-ace2-dev-node, adr-060-strands-agents-reference-only, adr-062-platform-identity-model, adr-067-product-contract-and-agent-access]
created: "2026-09-30"
---

# ADR-068: ace2 Hosts the Operator's Agent Tooling (Hermes, Open WebUI, MCP)

## Status

Accepted, 2026-09-30. The operator chose this option during an architecture session on kubelab#1933, which is the same precedent as ADR-067. It amends:

- [ADR-058](adr-058-ace2-dev-node.md) D1, and re-reads D5 (which stands) and D3 (which D2 below meets for Hermes, pending the rootless measurement);
- the 2026-08-09 amendment of [ADR-028](adr-028-operational-topology.md);
- [ADR-043](adr-043-unified-knowledge-memory-plane.md): where Open WebUI runs, its RAG policy, and Hermes's vault authority.

It is consistent with [ADR-060](adr-060-strands-agents-reference-only.md) ("no free always-on slot"), because nothing here takes an always-on slot. It does not amend [ADR-042](adr-042-reference-architecture.md) C11b: NaN's model API stays the inference provider for operator tooling.

## Context

The Hermes agent ran on a NaN microVM. That V1 instance was decommissioned on 2026-08-23, and on 2026-09-30 the operator confirmed the agent is retired. NaN's model API is still in use. The operator wants a home for Hermes and a chat UI in their own infrastructure. NaN-hosted agents may coexist later, but nothing should depend on them.

Measured on 2026-09-30 with a read-only `free -m`, because no toolkit target reports node memory:

| Node | Tier | Available RAM | Note |
|---|---|---|---|
| ace2 | on-demand | 11.0 of 11.7 GB | the dev node; 209 GB of disk free |
| ace1 | on-demand | 9.1 of 11.7 GB | K3s staging |
| beelink | on-demand | 6.3 of 7.7 GB | with CI idle; `act_runner` takes up to 4 GB under load |
| VPS | always-on | 4.5 of 7.7 GB | prod K3s server, no swap |
| gcp1 | always-on | 0.49 of 1.96 GB | 571 MB in swap ([#368](https://github.com/mlorentedev/kubelab/issues/368)) |

What Hermes did on NaN (`80_agents/hermes-nan/cronjobs.yaml`): apply and capture against the vault every 4 h, daily curation, a health digest, a 10-minute watchdog, a 03:00 state backup, a quota digest, a weekly curator pair and a nightly session note. All of it reconciles from the vault and is idempotent. The only surface that needed 24/7 uptime was the chat gateway. Nothing in kubelab calls Hermes.

On NaN, Hermes ran with `approvals.mode: off` and a local terminal backend, as root through a patched entrypoint. Its three 2026-06-09 postmortems were sshd outages on the host it was administering.

The reference audit (vault `10_projects/kubelab/30-architecture/agent-host-reference-audit.md`) compared ADR-022 (OpenClaw), hermes-nan as it ran, and the Hermes upstream docs. It found three upstream facts that shape this decision:

- **Missed cron slots catch up once.** After the gateway was down, each missed recurring slot runs one time when it comes back (`cron.catch_up_missed`, default true).
- **The approval channel is native.** `approvals.mode: manual` with `timeout: 300` denies an unanswered prompt, a `deny:` list survives `/yolo`, and `terminal.backend: docker` runs commands outside the host. Approval prompts arrive in the messaging channel.
- **Open WebUI can drive Hermes.** Hermes serves an OpenAI-compatible API on `:8642`, and upstream documents Open WebUI as a client of it.

The constraints this was evaluated against are C1 to C15 in the vault's `10_projects/kubelab/30-architecture/session-protocol.md`. The ones that decided it:

- **C2 (reworded today):** no autonomous agent *identity* may read a SOPS key or a prod kubeconfig.
- **C8:** anything an agent may call at any hour runs on an always-on host.
- **C11:** no new recurring cost.
- **C12:** no dependency on NaN-hosted agents or data.
- **C13:** an agent's shell runs off the host, behind an approval that fails closed.
- **C14:** one writer per vault zone.
- **C15:** an agent authenticates with its own scoped tokens, delivered by IaC.

## Options considered

| Option | Verdict | Reason | Reopen when |
|---|---|---|---|
| **O1. Everything on ace2**: Hermes in a rootless Compose stack under its own user, Open WebUI and an MCP bridge on the system Docker daemon out of the agent's reach, all owned by one Ansible role, on-demand | **Chosen** | Meets every constraint. The RAM is there (11 GB measured), it costs nothing new, and C8 does not apply: Hermes calls other services and nothing calls it | — |
| O2. Hermes on ace2, Open WebUI on ace1 staging K3s (ADR-043 as written) | Rejected | Every master commit reverts a staging deploy ([#1083](https://github.com/mlorentedev/kubelab/issues/1083)). Staging is a shared test bed, which is the wrong place for chat history (singleton state under ADR-061). One tool would need two on-demand hosts powered | #1083 is fixed **and** Open WebUI becomes the primary operator console. Then, per ADR-043, it moves to the prod VPS |
| O3. Hermes gateway on the VPS, the rest on ace2 | Rejected | Breaks C2: the VPS is the prod K3s server, so an agent with a shell there sits on a host holding a prod kubeconfig. ADR-060 also records no free always-on slot | an always-on host that is not prod exists within C11 |
| O4. Hermes on NaN (microVM or Basic Space), Open WebUI on ace2 | Rejected as the primary | Breaks C12. NaN V2 agents are not available to the operator today | NaN V2 agents are available **and** the chat goes unanswered while ace2 is off often enough to matter. Then a NaN instance is a *second* Hermes, never a dependency |
| O5. gcp1, Beelink or RPi3 | Rejected on measurement | gcp1 has 0.49 GB available and is in swap. RPi3 has 1 GB. Beelink's CI load reaches 4 GB | gcp1 grows to 4 GB or more; Beelink loses its runners |

## Decision

### D1. ace2 hosts the operator's agent tooling and stays on-demand

ace2 runs a Hermes instance named **`hermes-kubelab`**, Open WebUI, and the MCP bridge (D5) as one Docker Compose stack. The name follows the `<runtime>-<home>` convention of `hermes-nan`, so the two read apart if they ever coexist (O4). `hermes-nan`'s vault tree stays as the archive of the NaN instance. An Ansible role owns the stack, and systemd units start it after `network-online.target`, `docker.service` and `tailscaled.service`. ace2 stays in the **on-demand** tier.

Nothing always-on may depend on this stack. That is C8 read correctly: C8 constrains services an agent *calls*, not the agent that calls them. Two consequences are accepted:

- **While ace2 is off, the chat does not answer.**
- **Missed jobs run once at power-on** (D2's cron semantics).

ace2 remains the dev node of ADR-058. This stack sits alongside it, and the `dev_node` role stays the SSOT for the developer environment.

Each service has a hard memory limit. The starting point is 1.5 GB per service, so at least 4 GB stays free for interactive coding sessions, verified by measurement during implementation.

### D2. Hermes runs in the posture ADR-058 D3 requires

- **Identity on the host.** `hermes-kubelab` runs under its own Unix user, with no sudo, on a rootless container runtime (rootless Docker or Podman), so the Docker socket it drives is not root on ace2. It cannot read any staging credential that ADR-058 D3 allows on ace2 (C2). Whether Hermes's docker backend works against a rootless socket is not yet measured: the implementation spec measures it before the role is written, with Podman's socket as the fallback. If neither works, this decision reopens rather than falling back to the root socket. Open WebUI and the MCP bridge run on the system daemon instead, because an agent that could reach their containers could read every chat and their credentials.
- **Execution.** `terminal.backend: docker` with `docker_forward_env: []`. Commands run in a sandbox container with CPU and memory limits, never on the host (C13).
- **Approval.** `approvals.mode: manual` with `timeout: 300`, which fails closed. The `deny:` list carries over the patterns in `80_agents/hermes-nan/guardrails-denylist.yaml`. Prompts arrive in the messaging channel, which is the human-approval channel ADR-058 D3 asks for. `approvals.mode: off`, how it ran on NaN, is not allowed.
- **Schedule.** Hermes's in-process cron runs the jobs, with `cron.catch_up_missed: true`. There are no systemd timers for agent jobs. The `ExecStartPre` in the units only removes a stale `.git/index.lock` when no git process is running, then fast-forwards (`git pull --ff-only`). It never rebases automatically.
- **Network identity.** The instance joins the tailnet as its own node with a preauth key carrying `tag:hermes` (ADR-041), through a userspace tailscale sidecar. It never uses ace2's node identity, which is the admin's and matches every allow rule. The existing `tag:hermes` ACL rows were written for a NaN pod. The destination set for ace2 starts closed and is enumerated in the implementation spec as jobs need it; today's jobs reach only the internet (NaN, GitHub, Slack, Google Drive).
- **Channel.** Slack `#agent-fleet`, per the ADR-044 addendum that retired the Telegram single sink.

### D3. Credentials are per service and delivered by IaC

`hermes-kubelab` holds only its own scoped, revocable tokens (C15). Its current jobs need four:

- a GitHub token scoped to the vault repository;
- an inference key (D7);
- a Slack bot token;
- a read-only Google Drive OAuth credential.

The set starts closed, as ADR-041 D3 does for network destinations. A token for another service (a Gitea bot token, a Grafana read-only service account, a `toolkit-mcp` client under ADR-067 D6) is added when a job needs it, not before.

The operator mints them, they live in SOPS, and the Ansible role renders them into the instance's environment at provision time. The agent never decrypts anything ([#1272](https://github.com/mlorentedev/kubelab/issues/1272) covers unattended delivery on the dev node).

### D4. Vault: own clone, own zone, git as the bus

`hermes-kubelab` keeps its own clone of the vault, reads everything, and writes only inside its own zone (`80_agents/hermes-kubelab/`), seeded from the portable parts of `80_agents/hermes-nan/` (cron jobs, guardrails, backup policy). A pre-commit hook enforces that, as it did on NaN. This is the ADR-022 inbox pattern. It refines ADR-043's "Hermes read-only on the vault" to "read-only outside its own zone"; multi-writer git stays closed (C14).

The shared writable `/opt/vault`, which #1933 proposed for all agents and Open WebUI, is **rejected**. Interactive coding agents keep their own checkouts, and a handoff becomes visible to Hermes on its next pull. That is git's latency, not a network hop.

### D5. Open WebUI on ace2, with Hermes as a backend

Open WebUI runs in the D1 stack. Its backends are:

- the Hermes API (`:8642`), so chatting with Hermes is chatting with the agent and its tools;
- NaN's models directly, for plain chat.

Its database is SQLite in WAL mode on a persistent volume. Users sign in through its own OIDC client on prod Authelia (ADR-062 human class), which is always-on, and reach it directly on ace2 over the tailnet. It is deliberately **not** put behind the `dev.kubelab.live` route: that route is served by staging Traefik on ace1, so it would make the chat depend on a second on-demand host, which is the reason O2 was rejected. It would also add ForwardAuth on top of OIDC.

Knowledge, until the ADR-043 plane exists:

- **Native RAG** is enabled **only** for ad-hoc uploads and Google Drive documents. It uses NaN's `qwen3-embedding` (`RAG_EMBEDDING_ENGINE=openai`) and `rerank` (`RAG_EXTERNAL_RERANKER_URL`), so no embedding model loads locally.
- **The vault** is reached through a read-only MCP tool. It is not indexed by Open WebUI.
- **When [#299](https://github.com/mlorentedev/kubelab/issues/299), [#395](https://github.com/mlorentedev/kubelab/issues/395) and [#396](https://github.com/mlorentedev/kubelab/issues/396) land**, vault knowledge moves to `/v1/knowledge/search` as ADR-043 decided. There is still one index for the vault.

The vector store is ours, never NaN's (C12). The index is derived, so replacing the embedding provider costs a full re-embed, not data.

One measurement belongs to the implementation spec: pgvector's HNSW and IVFFlat indexes accept at most 2000 dimensions (`vector`) or 4000 (`halfvec`), and `qwen3-embedding` returns 4096. Whether NaN honours a `dimensions` parameter decides between a reduced dimension, exact search without an index, or another embedding model.

### D6. Google Drive through MCP, never a mount

Google Drive is reached through an MCP server with a read-only OAuth scope. It is not a FUSE mount or a PVC. Open WebUI speaks only Streamable-HTTP MCP and Drive servers are stdio, so the stack carries a stdio-to-HTTP bridge (`mcpo` class). The same bridge serves the read-only vault tool in D5.

### D7. The inference key

Today the only NaN key is the one PR-Agent uses. Sharing it carries two risks. The 60 RPM global limit is per key and would be shared, and that is the smaller risk. The larger one: an agent with a shell would hold a CI reviewer's credential, so a leak from `hermes-kubelab` forces a PR-Agent rotation, and the key would live in two stores.

So:

1. **The operator checks in the NaN console whether a member can mint a second key.** If yes, `hermes-kubelab` gets its own key, registered in kubelab's SOPS `SECRET_CATALOG`, and the problem ends there.
2. If not, the shared key is used with routing discipline:
   - cron and delegation jobs on unmetered models (`qwen3.6`, `gemma4`);
   - low concurrency;
   - OpenRouter as the fallback on 429.

   The key gets exactly one named home, and both consumers are delivered from it. Which store that is gets decided in its own ticket, because PR-Agent's key lives today in the dotfiles secret registry, and a kubelab role reading another repository's registry is a coupling no ADR sanctions.

### D8. Backup

`hermes-kubelab`'s state (its home directory and `state.db`) and Open WebUI's volume are added to `backup.sources` for ace2. That way `node_backup` ships them to R2 with restic (BACKUP-044), and no agent-side backup mechanism is built.

### Cost (ADR-063 D4)

| Line | Rate × quantity |
|---|---|
| ace2 electricity, now powered for longer stretches | accepted by the operator on 2026-09-30; draw not measured |
| Inference | the operator's current NaN plan; the tier is to be confirmed in the console (the vault records Free/Base limits). Crons on unmetered models; chat draws from per-model monthly quotas |
| R2 storage for the new backup sources | within the 10 GB free allowance (ADR-049) |
| New hosts or plans | none |

## Consequences

**Positive**

- Hermes gets a home that costs nothing new.
- The chat UI and the agent are one surface: Open WebUI talks to the agent, not around it.
- ADR-058 D3's autonomous-agent gate is met with upstream features rather than a bespoke jail.
- The vault stays single-writer per zone.
- The knowledge plane of ADR-043 keeps one index.

**Negative**

- The chat is unavailable while ace2 is off.
- ace2 now concentrates the dev environment, an agent and a chat UI with history, so it is a bigger asset to harden.
- Rootless containers and a userspace tailscale sidecar are new operational surfaces.
- Until #396 exists, the vault is reachable from chat only through MCP.

**Neutral**

- Implementation starts with [#1300](https://github.com/mlorentedev/kubelab/issues/1300). The `dev_node` role reports changes on every pass, so a new role on ace2 cannot prove `changed=0` until that is fixed.
- #1933 becomes "implement ADR-068".
- The questions in #239 are answered by O1 plus O4's trigger.
- #588 to #591 were written for a NaN pod and need new dispositions.

## Triggers to reopen

- **O4, the coexistence path:** NaN V2 agents are available and a 24/7 chat matters. A NaN instance is added as a second Hermes, not moved to.
- **O2, then the VPS:** Open WebUI becomes the primary operator console (ADR-043's trigger), after a RAM check on the VPS.
- **An always-on agent:** a job appears that someone must be able to call at any hour. It goes to an always-on host under C8, not to ace2.
- **A second key cannot be minted and the shared key's 60 RPM is exhausted** by both consumers in the same window: buy capacity or move the agent's inference elsewhere.

## References

- Issue: [#1933](https://github.com/mlorentedev/kubelab/issues/1933) (AI-009)
- Vault: `10_projects/kubelab/30-architecture/agent-host-reference-audit.md`; `session-protocol.md` (C1 to C15); `80_agents/hermes-nan/` (cronjobs, guardrails, context)
- [ADR-022](adr-022-openclaw-agent-deployment.md) (OpenClaw, superseded; inbox pattern), [ADR-028](adr-028-operational-topology.md), [ADR-041](adr-041-agent-fleet-vpn-segmentation.md), [ADR-043](adr-043-unified-knowledge-memory-plane.md), [ADR-044](adr-044-unified-notification-routing-fabric.md), [ADR-058](adr-058-ace2-dev-node.md), [ADR-060](adr-060-strands-agents-reference-only.md), [ADR-062](adr-062-platform-identity-model.md), [ADR-063](adr-063-hub-cloud-provider-migration.md) D4, [ADR-067](adr-067-product-contract-and-agent-access.md)
- Hermes Agent docs: `website/docs/user-guide/docker.md`, `features/cron.md`, `guides/secure-hermes-on-a-work-machine.md`, `user-guide/messaging/open-webui.md` (github.com/nousresearch/hermes-agent)
- Open WebUI env reference: `RAG_EMBEDDING_ENGINE`, `RAG_OPENAI_API_BASE_URL`, `RAG_EXTERNAL_RERANKER_URL`, `VECTOR_DB`
