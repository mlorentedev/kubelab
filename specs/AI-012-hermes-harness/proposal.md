---
id: "AI-012-hermes-harness"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-10-10"
issue: "mlorentedev/kubelab#1933"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "Operator decision 2026-10-10: port the retired hermes-nan harness into hermes-kubelab now; it supersedes AI-009 AC6, so AI-009 can archive (16 active, limit 10, 2026-10-10)"
---

# AI-012: the hermes-kubelab harness

## Why

<!-- from issue #1933: AI-009: Centralized Agentic & Knowledge Hub on ace2 (Hermes, Open WebUI, Vault & GDrive MCP) -->

AI-009 gave `hermes-kubelab` a runtime: a confined sandbox, approvals, Slack, the vault clone and backups. It did not give it a harness. As of 2026-10-10 the gateway runs:
- the image's default `SOUL.md`;
- no cron job (`cron/jobs.json` does not exist);
- empty memory;
- none of the hardening and performance keys `hermes-nan` ran with.

`hermes-nan` will never run again, and its harness lives only as files in `80_agents/hermes-nan/` and `00_meta/agents/scripts/`, applied by scripts that no longer run. This spec ports every capability of that harness that still has a purpose, as IaC of the `agent_stack` role. It retires the rest in writing.

## What

After this spec, `make provision NODE=ace2 ENV=prod` also produces the following. A second run reports `changed=0`, and `CHECK=1` reports `failed=0`.

1. **Config parity.** `hermes-config.yaml.j2` sets every key of `80_agents/hermes-nan/config-desired.yaml` that still applies, each with a test:
   - `model.context_length`;
   - `security.*` (`redact_secrets`, and tirith if the image ships it), `privacy.redact_pii`;
   - `skills.guard_agent_created`, `display.file_mutation_verifier`;
   - `agent.{max_turns,api_max_retries,reasoning_effort}`;
   - `compression.*`, `tool_output.*`, `tool_loop_guardrails`;
   - `sessions.retention_days`, `checkpoints.enabled`, `code_execution.*`;
   - the delegation limits.

   `approvals` and `terminal` keep AI-009's values, not NaN's (`approvals.mode: off`, `terminal.backend: local`).
2. **A fallback model.** `fallback_providers` names Anthropic's Haiku, the latest pinned in `common.yaml`. It is used when NaN fails (for example, a 429). The key is a new `SECRET_CATALOG` entry. Spend is capped at 20 USD per month by the provider: a dedicated workspace with a spend limit, created by the operator (runbook, step by step). No cap enforced by the agent counts.
3. **Identity.**
   - `SOUL.md` is rendered by the role and mounted read-only over the data directory's copy, like `config.yaml`, so the agent cannot rewrite its persona.
   - The persona's public part (role, style, operating principles, language rules, adapted from `hermes-nan/SOUL.md` and `AGENTS.md`) lives in the role.
   - The private part (the operator profile from `hermes-nan/USER.md`) is joined to the persona on the node, from the root-owned vault mirror, at provision time, without passing through the controller. It never enters the public repository.
4. **Declared jobs, reconciled by name.**
   - The jobs are declared in `common.yaml`: name, schedule, mode (agent or script), model, delivery and skills.
   - A role task reconciles the gateway's jobs against that declaration through `hermes cron`: it creates missing jobs, replaces changed ones and removes declared-then-dropped ones. It never touches a job it did not create. It is idempotent and `CHECK=1`-safe.
   - Every job delivers to `slack:<home_channel>` and runs on the unmetered model unless it declares otherwise.
   - Every agent job's commands are checked with `hermes approvals test --env-type local` before it is declared (lesson-540).
5. **The jobs ported from NaN:**
   - **Daily session record:** writes `80_agents/hermes-kubelab/sessions/<date>-auto.md` when something happened. Pushed by the vault sync.
   - **Memory capture:** the agent's `memories/` reach the zone.
   - **Daily health and consumption digest:**
     - gateway, sandbox, disk, sync and backup state;
     - month-to-date tokens per model from `state.db`;
     - the fallback's spend.
   - **Curator recurrence judge and proposal emitter:** weekly. The analyzer and emitter need the vault, so they run as host units of the agent's user, never as gateway `--script` jobs, because no-agent scripts run in the gateway container, which does not see the vault. Proposals land in `80_agents/hermes-kubelab/proposals/`.
   - **Research jobs:** the daily market briefing, the weekly competitive monitor and the monthly deep analysis (`hermes-nan/runbooks/model-orchestration.md`). Their prompts are private, so they are read from the operator-owned vault directory like the profile. They need the BrightData MCP, whose token is a `SECRET_CATALOG` entry.
   - **Alert and log triage (AI-011, #2080):** hourly while ace2 is up, and once at power-on (`cron.catch_up_missed`). The bot reads the alert channels declared in `common.yaml`, and Loki and Grafana through a read-only service account token. It posts a digest with one proposed ticket per real defect, and opens none.
6. **Skills.**
   - The manifest of `hermes-nan/skills-manifest.yaml` becomes a declaration in `common.yaml`.
   - Each skill comes from `00_meta/skills/<name>/SKILL.md` in the root-owned vault mirror.
   - A declared skill with no `SKILL.md` fails the provision.
   - The agent cannot change a managed skill. Skills it creates itself are its own, and are captured to the zone.
7. **The repository, readable.** A second root-owned, read-only mirror holds the kubelab repository's `docs/`, so the agent and Open WebUI can read ADRs, runbooks and lessons as well as the vault.

## Placement rule (the decision this spec rests on)

**Whatever governs the agent cannot live where the agent writes.** The zone `80_agents/hermes-kubelab/` is read-write for the agent, so it holds the agent's output only:
- sessions;
- captured memory and self-made skills;
- proposals;
- lessons.

Everything that constrains the agent has one of two homes:
- **The role**, which is public and reviewed by PR: config keys, the deny list, job declarations, the skill manifest, the public persona.
- **An operator-owned vault directory outside the zone**, which is private: the operator profile and the research prompts. It reaches the node only through the root-owned mirror.

This supersedes AI-009 AC6 as written, which seeded `cronjobs` into the zone. ADR-068 is amended at this spec's archive.

## Out of scope

Each of these was part of `hermes-nan` and is retired with a reason in `verification.md`:
- `apply-from-vault.sh` and `capture-to-vault.sh` (the role and the sync replace them);
- the boot script, auto-heal daemon, sshd, the offline pull and the age backup (NaN-platform behaviour, or covered by `make provision` and restic to R2);
- the Hive MCP (the sandbox reads the vault directly);
- the Telegram delivery;
- the vault-curator referee (`CHECK=1` and the provision's read-backs are the drift check).

Also out of scope:
- Indexing the vault in Open WebUI (ADR-068 D5 still holds).

## Risks / open questions

- **R1, operator, BLOCKING for the fallback PR: the Anthropic key.** A workspace dedicated to `hermes-kubelab` with a 20 USD monthly spend limit, and a key scoped to it. The runbook gives the clicks.
- **R2, operator, BLOCKING for the research PR: the BrightData token**, and the operator-owned directory's name. It is a sibling of the zone, never inside it.
- **R3, operator, BLOCKING for the triage PR: the alert channels.** Their names; the agent derives the IDs and the invite list.
- **R4: does the BrightData MCP run in the gateway image?** It is a Node package. If the pinned image has no Node, the options are a derived image built on ace2, pinned by digest like the MCP bridge, or the MCP behind mcpo. Measured before that PR.
- **R5: do `fallback_providers` with Anthropic work in v2026.9.24?** Proven by consequence. With NaN made unreachable for the agent's uid, a turn completes on Haiku, and the spend shows in the workspace.
- **R6: does the running gateway pick up `hermes cron` changes without a restart?** This decides whether the reconciler restarts the gateway.

## Acceptance criteria

- [ ] AC1. Every applicable key of `config-desired.yaml` is rendered and tested. Each key left out has a reason in `verification.md`.
- [ ] AC2. A turn completes on the Anthropic fallback when NaN is unreachable. The key is in `SECRET_CATALOG`, and the 20 USD cap is set in the provider.
- [ ] AC3. The gateway's `SOUL.md` is the role's, and an edit to it from inside the gateway fails. The operator profile appears in the rendered file on the node and nowhere in the repository.
- [ ] AC4. The declared jobs and the gateway's jobs match by name. A second provision reports `changed=0`. Removing a declaration removes the job, and a job the role did not create survives.
- [ ] AC5. Live: a scheduled job's commit lands under the zone, closing AI-009 AC6's live row. A digest reaches `#agent-fleet`.
- [ ] AC6. Live: the curator judge runs, and a RECURRENCE verdict becomes a file under `proposals/`. The `dispose-proposals` skill reads `hermes-kubelab/proposals/`.
- [ ] AC7. Live: the research jobs run with BrightData and deliver to Slack.
- [ ] AC8. AI-011's four criteria (#2080): a test alert reaches the digest with its log context; catch-up at power-on; the token is read-only, proven by a refused write; no credential reaches the digest or the vault.
- [ ] AC9. A declared skill is installed from the mirror. A missing `SKILL.md` fails the provision, and the agent cannot edit a managed skill.
- [ ] AC10. The agent and Open WebUI can read the repository's `docs/` read-only.
- [ ] AC11. `80_agents/hermes-nan/_index.md` points to this spec, and every NaN artifact is marked ported, superseded or retired.

## References

- Epic: #1933. AI-011 (#2080) is delivered here.
- [ADR-068](../../docs/adr/adr-068-ace2-operator-agent-tooling.md); AI-009 (`specs/AI-009-hermes-ace2/`).
- NaN harness: vault `80_agents/hermes-nan/` and `00_meta/agents/scripts/`. Inventory of 2026-10-10 in `verification.md`.
- lesson-540 (`--env-type local`), lesson-549 (approval widening), lesson-552 (the kill switch).
