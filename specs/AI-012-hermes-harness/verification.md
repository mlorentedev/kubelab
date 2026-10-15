---
tags: [spec, verification, templates]
created: "2026-10-10"
---

# Verification - AI-012-hermes-harness

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] AC1 -> PR 1 (`feat/ai012-config-parity`). Tests in `tests/test_hermes_config.py`:
  - `test_every_ported_key_renders_with_its_declared_value`, one case per leaf of `agent_config`;
  - `test_the_ported_keys_cannot_reach_what_the_role_decides`;
  - `test_a_role_owned_key_in_the_ssot_does_not_override_the_role`;
  - `test_every_provision_asks_the_running_scanner_for_both_verdicts`.

  `_config()` now loads with a loader that refuses duplicate keys, because `safe_load` keeps the last of two silently.
- [ ] AC2: blocked upstream. The code is in draft #2204. Hermes swaps to the fallback when NaN refuses it, then sends the console's `sk-ant-usr` key as an OAuth token, which the API refuses (lesson-557, upstream NousResearch/hermes-agent#133856). ace2 runs without a fallback until Hermes classifies the key correctly.
- [ ] AC3 to AC11: pending.

### AC1, live on ace2, 2026-10-10

- The provision from the branch gave `changed=3`: the config, the gateway restart and the sandbox sweep. A second run gave `changed=0`.
- Hermes's own `load_config()` inside the gateway reads the ported values back, for example:
  - `security.tirith_fail_open False`, `privacy.redact_pii True`;
  - `agent.max_turns 120`, `model.context_length 1000000`;
  - `compression.threshold 0.25`, `sessions.retention_days 180`;
  - `tool_loop_guardrails.hard_stop_after.same_tool_failure 12`.
- The scanner resolves to `$HERMES_HOME/bin/tirith` (PATH, then that directory). `check_command_security` gives:
  - `ls -la /vault`: `allow`;
  - a homograph URL: `block`;
  - a pipe to `sh`: `block`.
- With `TIRITH_BIN=/nonexistent`, `ls -la /vault` gives `block`, with the summary `tirith spawn failed (fail-closed)`. So the provision's probe tells a working scanner from a missing one.
- `hermes approvals test` does not model the scanner: the same homograph reads `allow` there. That is why the probe calls the scanner directly.

### AC1, keys left out

| `config-desired.yaml` key | Reason |
|---|---|
| `approvals.mode: off` | ADR-068 D2: approvals are manual and fail closed. `off` is how hermes-nan ran with no approvals at all |
| `terminal.backend: local` | ADR-068 D2: every command runs in the docker sandbox, never on ace2 |
| `updates.pre_update_backup`, `updates.backup_keep` | They guard `hermes update`, which a container does not run. The image is pinned in `common.yaml` and changes through a PR. The data directory is in restic (AI-009 PR 6) |
| `delegation.model` | Already rendered from `models.unmetered` (ADR-068 D7) |
| `fallback_providers` | PR 2, Anthropic Haiku in place of OpenRouter |
| `mcp_servers.brightdata` | PR 7 |

Retired 2026-10-15: v0.22 removed the scanner, so the two limits below describe v2026.9.24 only.

Two limits remained, and neither was in AC1's scope:
- The scanner binary lives in the data directory, which the gateway's process can write. The sandbox, where commands run, does not mount that directory.
- The scanner's circuit breaker fails open after repeated crashes, whatever `tirith_fail_open` says (`tools/tirith_security.py`, issue #41400 upstream).

### AC2, live on ace2, 2026-10-15 (Hermes v0.22.1)

- `make provision NODE=ace2 ENV=prod TAGS=agent_stack`: `changed=8`, then `changed=0`. `hermes gateway status`: running, supervised by s6, no boot-guard refusal. The config migration still logs `Read-only file system` for the mounted `config.yaml` and continues, as it did on every start of v2026.9.24 (`backups/config/*.pre-docker-migrate.*` go back to 2026-10-10).
- The runbook's old step 3 no longer forces a failure. In v0.22 `hermes chat` is a client of the gateway ("inbound message: platform=local" in the gateway's log), so neither `-e NAN_API_KEY=...` nor `--api-key` reaches the model call: both turns answered on NaN (`provider=custom`). The failure is forced in a throwaway gateway instead: the image run on the agent's daemon with the live env file, `NAN_API_KEY` invalid, Slack and the API off, and its own `HERMES_HOME` (so no live state is touched).
- Result, from that throwaway gateway: NaN answers `401 Invalid API key`, then `Fallback activated: deepseek-v4-flash -> claude-haiku-5-5 (anthropic)`, `API call #1: model=claude-haiku-5-5 provider=anthropic ... id=msg_...`, the CLI prints `Model fallback: ... authentication failed; using claude-haiku-5-5 via anthropic.` and the answer `pong`.
- API key, not OAuth: `_is_oauth_token("sk-ant-usr-x")` is `False` and `anthropic_route_is_oauth(...)` is `False` in the pinned image. On v2026.9.24 the same call answered `400 credit balance is too low` (the OAuth identity), on v0.22.1 it succeeds. The Console usage of the `hermes-kubelab` workspace is the operator's confirmation.
- The live gateway's `auth.json` still carries `ANTHROPIC_API_KEY` as `exhausted` (400, 2026-10-11). Hermes' longest cooldown is one hour (`EXHAUSTED_TTL_*`), so it has expired; it is not a block.
- AC1's scanner is retired, not ported: v0.22 removed it (see the decision below).

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

- 2026-10-10, operator: a new spec rather than widening AI-009. Research jobs are included. The fallback is Anthropic Haiku, capped at 20 USD per month in the provider. Triage runs hourly.
- 2026-10-10, the placement rule (`proposal.md`). It supersedes AI-009 AC6's seeding of `cronjobs` into the zone, and amends ADR-068 at archive.
- 2026-10-10, measured in the pinned image (v2026.9.24):
  - `SOUL.md` is seeded by `docker/stage2-hook.sh` (`seed_one`), so the gateway runs the image's persona today.
  - No-agent cron scripts run in the gateway container from `$HERMES_HOME/scripts/` (`cron/scheduler_script.py`). `.sh` runs via bash, everything else via Python.
  - `hermes cron create` takes `--name`, `--deliver platform:chat_id`, `--skill`, `--script`, `--no-agent`, `--model` and `--workdir`.
  - `ANTHROPIC_API_KEY` is a recognised provider key.
  - `cron/jobs.json` and `memories/` are absent or empty.
- 2026-10-10, operator, names: `agent_config` for the ported keys, `anthropic_api_key` and `brightdata_api_token` in prod's vault, and `80_agents/operator/hermes-kubelab/` for the operator's private directory. The owner goes in the parent directory, so one path rule (`80_agents/operator/` is the operator's, and the agent's zone never covers it) holds for every agent, where a `-operator` suffix would need a rule per agent.
- 2026-10-10, AC2 is parked, not worked around. The only route Hermes leaves to `x-api-key` on this key is a `base_url` outside `anthropic.com`, which means adding a proxy to work around one function.
- 2026-10-15, operator: move the pin to v0.22.1 (published the day before, against the "a few days old" rule) and accept the loss of the tirith scanner, which v0.22 removes without a replacement. What stands in its place is the sandbox with no network (`docker_network: false`, read back as `net=none` on the live container), plus the two new content checks that run through the approval flow when the vault is mounted. The scanner's own circuit breaker already failed open, so it was never a reliable fail-closed control.

## NaN harness disposition (AC11)

Inventory of `80_agents/hermes-nan/` and `00_meta/agents/scripts/`, 2026-10-10.

| NaN artifact | Disposition |
|---|---|
| `config-desired.yaml` | Ported, PR 1. `approvals` and `terminal` keep AI-009's values. `mcp_servers.brightdata` goes to PR 7 |
| `fallback_providers` (OpenRouter) | Replaced by Anthropic Haiku, PR 2 |
| `SOUL.md`, `AGENTS.md` | Ported as the role's persona, PR 3 |
| `USER.md`, `memory/` | Profile: operator directory, PR 3. Memory: captured from the runtime, PR 4 |
| `cronjobs.yaml`: session record, health report, consumption digest | Ported, PR 4 |
| `cronjobs.yaml`: curator judge and emitter, `curator/`, `proposals/`, `curator-*.py`, `emit-proposals.py` | Ported, PR 6 |
| `runbooks/model-orchestration.md` research templates, BrightData MCP | Ported, PR 7 |
| `skills-manifest.yaml`, `skills/` | Ported, PR 5. `verification-before-completion` and `audit` have no `SKILL.md` under `00_meta/skills/`, which is resolved there |
| `guardrails-denylist.yaml` | Already ported (AI-009) |
| `cronjobs.yaml`: apply, capture, vault curation; `apply-from-vault.sh`, `capture-to-vault.sh`, `vault-curator.sh`, `validate.sh`, `model-policy-check.sh`, `redact-config-secrets.py`, `config-backup.yaml` | Superseded. The role is the apply. The vault sync and memory capture are the capture. `CHECK=1`, the provision's read-backs and the template test of `cron.model` are the referee |
| `cronjobs.yaml`: service watchdog; `hermes-startup.sh`, `auto-heal-daemon.sh`, `bootstrap.sh`, `bootstrap-contract.md`, `full-recovery.md` | Superseded by `restart: unless-stopped`, the sidecar, `make provision` and the provision's probes |
| `cronjobs.yaml`: encrypted state backup; `backup.yaml`, `backup-state.sh`, `operator/`, `ssh/`, `fire-drill.md`, `restore-from-vault.sh` | Superseded by restic to R2 (AI-009 PR 6) and `make backup-drill-node` |
| `vault-pull-daemon.sh`, `vault-pull.sh`, git hooks | Superseded by the vault sync and the root-owned hook (AI-009 PR 4) |
| Hive MCP (`mcp-hive.md`) | Retired. The sandbox reads `/vault` directly |
| Telegram delivery, `discord-gateway-setup.md` | Retired. Slack is the channel |
| `context.md`, `servers.md`, `nan-cloud.md` §3, `env-variables.md`, `skills.md`, `memory.md`, `decisions/`, `postmortems/`, `lessons/`, `research/`, `sessions/` | History. They stay in place as the record of the NaN instance |

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/AI-012-hermes-harness/` -> `specs/archive/AI-012-hermes-harness/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
