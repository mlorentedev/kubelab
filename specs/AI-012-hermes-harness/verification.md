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
- The live gateway's `auth.json` still carries `ANTHROPIC_API_KEY` as `exhausted` (400, 2026-10-11, from the OAuth-era bug). Measured, not inferred: the same throwaway gateway rerun with a copy of that `auth.json` (the `exhausted` entry present) still prints `Fallback activated: deepseek-v4-flash -> claude-haiku-5-5 (anthropic)` and answers `pong`. The probe opened no Slack connection (empty `SLACK_*` reads as unset) and the live gateway stayed connected (`Socket Mode connected` since 02:49Z, no later Slack line).
- AC1's scanner is retired, not ported: v0.22 removed it (see the decision below).

### R6, live on ace2, 2026-10-15 (Hermes v0.22.1)

Does the running gateway pick up `hermes cron` changes without a restart? **Yes.**
- A throwaway Ansible playbook (not committed) ran as the agent's user against its daemon, with the gateway left running. Before: `hermes cron status` reported the gateway as the scheduler host (ticker heartbeat 48 s old), and `cron/jobs.json` did not exist.
- `hermes cron create --name r6-probe --deliver local --repeat 1 1m "..."` through `docker exec -u hermes`. 67 s later the job had run: `last_run_at` 07:08:27, `last_status: ok`, `hermes cron runs` showed it `completed`. No recreate, no restart. The probe job was removed afterwards.
- Source agrees: `get_due_jobs` calls `load_jobs()` from disk on every tick (`cron/jobs.py`). So the reconciler never restarts the gateway.
- `hermes cron list` prints text with a scheduler warning, so the reconciler reads `cron/jobs.json` (structured) and writes through `hermes cron create|edit|remove` (the CLI holds the store's lock). Writes run as `-u hermes`, or the files land owned by root.

What each process sees, same run:
- The gateway container has no `/vault` (`ls: cannot access '/vault'`, rc 2). A `--no-agent` script therefore cannot read or write the zone.
- No sandbox was running, so the sandbox's view of `HERMES_HOME` is not measured here; it is measured with the session record's live proof.

### The job reconciler, live on ace2, 2026-10-15

- `make provision NODE=ace2 ENV=prod TAGS=agent_stack CHECK=1`: `changed=1` (the job to create). First real run `changed=2`, second `changed=0`.
- Jobs are owned by the name prefix `kubelab:` (operator's choice). A job without it is never edited, resumed or removed, and two owned jobs with one name fail the plan.
- `edit` rather than `remove` + `create`: the id and the run history survive. It states every managed field, a cleared one with its empty value, and the mode (`--agent` or `--no-agent`) because `edit` keeps the old one otherwise.
- Locally, against the real CLI in the pinned image, every op ran with a foreign job preserved.

### The session record, live on ace2, 2026-10-15

- First run, with no context feed: the job answered `[SILENT]`. The agent cannot list its own sessions (its tools see the vault; `state.db` is in `HERMES_HOME`), so asking it whether there was activity cannot work.
- Fix: an agent job may carry a pre-run `script`. Its stdout is injected into the turn (cut at 8000 characters), and a last line of `{"wakeAgent": false}` skips the turn, the delivery and the spend. `session-activity.py` reads `state.db` read-only, drops automated sessions (`cron`, `subagent`, `tool`, `recovered`, `kanban`), redacts credentials and keeps to 7000 characters.
- The scripts directory is mounted read-only over `<data>/scripts/` (like `config.yaml`): what governs the agent is not where the agent writes. The image's start hook tolerated the mount.
- Run on the real Slack conversation of the night before: `last_status: ok`, the agent wrote `sessions/2026-10-15-auto.md`, and the next sync committed it as `hermes-kubelab` (`81037703`). The sandbox's write was not blocked by `cron_mode: deny`, and the injection scanner did not stop the transcript.
- Provision with the new mount: `CHECK=1` `changed=4`, first run `changed=6` (the Compose project re-rendered, so the gateway was recreated once for the mount, then the job edited), second run `changed=0`.
- The file already existed from the first run, so the agent kept two front matters. The prompt now says to replace an existing file with one record; the re-provision of that edit: `CHECK=1` `changed=1`, first run `changed=2` (the diff report and the edit), second run `changed=0`.
- `hermes cron edit --script ""` clears the stored script (checked in the pinned image: a job with a context script, edited to drop it, re-plans to nothing and reads `script: null`), so an agent job can lose its script without the planner editing it forever.

### The digest and the memory capture, live on ace2, 2026-10-15

- Digest: `kubelab:digest` (14:05 UTC daily, 08:05 in Denver, `mode: script`) ran on `hermes cron run` with `last_status: ok` and reached `#agent-fleet` as a `Cronjob Response`: gateway and sidecar uptime, one sandbox, 181 GB free, month-to-date calls and tokens per model and provider, and the Anthropic fallback line (0.00 USD). A first version summed `COALESCE(actual, estimated)` and printed 0.00 for everything, because Hermes writes `actual_cost_usd = 0.0` until a provider reconciles it; the sum is now the larger of the two.
- Memory capture, the operator's decision: mount the zone's `memories/` over the gateway's, instead of copying it at sync time. The reason is a permission fact measured on ace2: `data/` is `0700` owned by the gateway's subuid (534287), so the host user that runs the sync cannot read it, and a copy step would need a new privilege for the user that holds the vault token. The mount needs none; the directory is created `0777` by the role, because the gateway's user is not the clone's owner.
- It broke the sync once. Hermes creates `MEMORY.md.lock` and `.mem_*` temporaries `0600` as the subuid; git fails the whole `add` on one unreadable file, and `hermes-kubelab-vault-sync` stopped committing the zone, session record included (the unit failed). Fix: a root-owned ignore file passed as `core.excludesFile`, anchored to `<zone>/memories/` so an untracked file elsewhere in the clone still counts as a change outside the zone. Exclude pathspecs were tried first and git 2.43 stages nothing at all with them, exit 0 (the same `add -n` listed the files from an interactive shell and listed none under the unit's environment, repeatedly), which is why the first fix looked applied and was not.
- Live: after the fix, one forced sync committed `memories/MEMORY.md` and `USER.md` as `hermes-kubelab` (`38182a63`) and pushed; the lock files stay untracked and the unit is not failed.
- Provision: first run `changed=2`, second run `changed=0`.

### The session record's write, live on ace2, 2026-10-16 (#2321)

- The two scheduled runs of 2026-10-15 posted a file-mutation warning each: `write_file` refused `/vault/80_agents/hermes-kubelab/sessions/...` as outside `HERMES_WRITE_SAFE_ROOT` (the image sets `/opt/data`), and the record was written anyway through the shell. The variable is an `os.pathsep`-separated list (`agent/file_safety.py`, read in the pinned image), so the gateway now sets `<data>:<mount>/<zone>`. That widens nothing the agent could not already write: the sandbox mounts the zone writable and the rest of the vault read-only, and the shell fallback proved it. The operator approved this on 2026-10-15, after the advisor corrected an earlier recommendation to change the prompt (the only tool the policy allowed could not reach the zone).
- Live: after the provision, `hermes cron run` on `kubelab:session-record` ended `ok` and its `#agent-fleet` message carried no warning; the next sync committed the file (`eb3fe171`). Provision: `CHECK=1` changed=5, first run changed=1, second run changed=0 (that run was against master's role, which lacks #2322, and failed the sync on the lock files; the branch is stacked on #2322, and the converge on the stacked tree was changed=3, then 0).

### The managed skills, live on ace2, 2026-10-16 (AC9)

- `apps.services.ai.hermes_kubelab.skills` lists `insights`. The role copies each `<name>/` from the vault mirror (`00_meta/skills/`) into `/var/lib/hermes-kubelab/hermes-skills`, root-owned, mounted `:ro` at `/managed-skills`, and the gateway's `skills.external_dirs` names it. A declared skill the mirror lacks fails the provision; one dropped from the declaration is removed from the node.
- Finding: the dry run's read-back showed `systematic-debugging` already ships as a built-in, which outranks an external skill, so the manifest leaves it (and `test-driven-development`) out (lesson-579).
- Provision: dry run `changed=2`, first run `changed=6`, second run `changed=0`. The run reads the skills back through the gateway (`hermes skills list` lists `insights` with the source `external`; a built-in of the same name fails it) and a `touch` in `/managed-skills` as the gateway's user must fail.
- Tests: `tests/test_hermes_skills.py` 13 pass; the `:ro` flag removed from the mount goes red under `make mutate`.

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

- 2026-10-10, operator: a new spec rather than widening AI-009. Research jobs are included. The fallback is Anthropic Haiku, capped at 20 USD per month in the provider. Triage runs hourly.
- 2026-10-14, operator, read in the Console: the `hermes-kubelab` workspace has a 20 USD monthly spend limit. The Anthropic spend is split by workspace, not shared: `ci` (PR-Agent) 60 USD, `hermes-kubelab` 20 USD, organization 80 USD, so neither can starve the other and the sum equals the organization's cap. PR-Agent's old key still sits in the Default workspace until its secret is switched to the `ci` key.
- 2026-10-10, the placement rule (`proposal.md`). It supersedes AI-009 AC6's seeding of `cronjobs` into the zone, and amends ADR-068 at archive.
- 2026-10-10, measured in the pinned image (v2026.9.24):
  - `SOUL.md` is seeded by `docker/stage2-hook.sh` (`seed_one`), so the gateway runs the image's persona today.
  - No-agent cron scripts run in the gateway container from `$HERMES_HOME/scripts/` (`cron/scheduler_script.py`). `.sh` runs via bash, everything else via Python.
  - `hermes cron create` takes `--name`, `--deliver platform:chat_id`, `--skill`, `--script`, `--no-agent`, `--model` and `--workdir`.
  - `ANTHROPIC_API_KEY` is a recognised provider key.
  - `cron/jobs.json` and `memories/` are absent or empty.
- 2026-10-10, operator, names: `agent_config` for the ported keys, `anthropic_api_key` and `brightdata_api_token` in prod's vault, and `80_agents/operator/hermes-kubelab/` for the operator's private directory. The owner goes in the parent directory, so one path rule (`80_agents/operator/` is the operator's, and the agent's zone never covers it) holds for every agent, where a `-operator` suffix would need a rule per agent.
- 2026-10-15, operator: jobs are owned by the name prefix `kubelab:`; the digest covers what the gateway sees (docker.sock, its data directory, `state.db`); memory capture is done by the host sync copying `memories/` into the zone. PR 4 split into 4a (reconciler, session record) and 4b (memory capture, digest).
- 2026-10-15, operator, superseding the line above on memory capture: mount the zone's `memories/` over the gateway's instead of copying, because the host sync user cannot read the gateway's data directory.
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
