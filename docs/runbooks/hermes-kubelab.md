---
id: hermes-kubelab
type: runbook
status: active
created: "2026-10-07"
owner: manu
---

# Operate the agent stack on ace2 (Open WebUI and hermes-kubelab)

> ace2 hosts the operator's agent tooling (ADR-068): Open WebUI, and the
> `hermes-kubelab` gateway with its tailscale sidecar. Everything here goes
> through `make provision NODE=ace2 ENV=prod TAGS=agent_stack` (role
> `agent_stack`, spec `specs/AI-009-hermes-ace2/`). ace2 is on-demand: when it
> is off, both services are off, and nothing pages.

## What runs where

| Piece | Runs as | Started by | Data |
|---|---|---|---|
| Open WebUI | system Docker | `agent-stack-webui.service` (waits for the Tailscale address) | volume `open-webui-data` |
| hermes-kubelab gateway | uid `hermes-kubelab`, rootless Docker | the user's daemon (`loginctl enable-linger`), `restart: unless-stopped` | `/var/lib/hermes-kubelab/data` |
| tailscale sidecar (`tag:hermes`) | same rootless daemon, userspace mode | same | `/var/lib/hermes-kubelab/tailscale` (node key) |
| tailnet and private-network refusal for the agent's uid (new connections only, #2161) | root | `agent-stack-egress.service`, `RequiredBy=user@<uid>` | `/opt/agent-stack/agent-egress.nft` |
| bridge wait before the agent's manager | root | `agent-stack-hermes-bind.service`, `WantedBy=user@<uid>` | none |
| vault sync (ADR-068 D4, amended) | uid `hermes-kubelab`, token from systemd | `hermes-kubelab-vault-sync.timer`: 2 min after boot, then every 15 min | clone `/var/lib/hermes-kubelab/vault`; token `/opt/agent-stack/vault-token` (root, 0600) |
| vault mirror (spec AI-009 AC9) | root, token from systemd, the agent's home inaccessible | `agent-stack-vault-mirror.timer`, at the sync's interval | `/opt/agent-stack/vault-mirror` (`git/` history, `tree/` notes) |
| MCP bridge (mcpo, the vault read-only) | system Docker, uid 65534, read-only root, no published port | Open WebUI's Compose project | none; mounts `vault-mirror/tree` read-only, key in `/opt/agent-stack/mcp-bridge.env` (0600) |

Open WebUI is reached at `https://chat.kubelab.live`, with OIDC against prod
Authelia (ADR-068, amendment 2026-10-08). Prod Traefik terminates TLS and
forwards over the tailnet to `ace2:3080`, and refuses the password form at
`/api/v1/auths/signin`. Break-glass reaches it at ace2's tailnet IP, the address
in the route's EndpointSlice. Open WebUI admits that IP, `ace2.kubelab.internal`
and the public name as origins, and no other (#2202). The gateway's API listens on
`172.30.250.1:8642`, the gateway of Open WebUI's bridge `br-open-webui`
(`networking.nodes.ace2.webui_bridge`), and ufw admits that bridge's subnet
alone. Open WebUI lists Hermes as its second backend, after NaN, visible to
admins only. Without Open WebUI the API falls back to `127.0.0.1:8642`.

At boot, `agent-stack-hermes-bind.service` holds the agent's user manager
until the bridge has its address (`WantedBy=user@<uid>`, so a missing bridge
delays the agent by up to 120 s and no more). To check the firewall by hand:
`sudo ufw status | grep 8642` shows the one allow rule, and a refused attempt
from another network logs `[UFW BLOCK] ... DPT=8642` in `journalctl -k`
(lesson-542). Every provision runs both probes.

## Models

- **Primary**: NaN (`models.unmetered` in `common.yaml`), which delegation is
  pinned to as well.
- **Fallback**: Anthropic Haiku (`models.fallback` in `common.yaml`), on the key
  of the Console workspace `hermes-kubelab` (non-Default, 20 USD monthly
  limit), in `prod.enc.yaml` as
  `apps.services.ai.hermes_kubelab.anthropic_api_key`. An unpinned session
  moves to it when NaN answers 429 after retries, 5xx, 401/403 or 404;
  scheduled and delegated work is pinned to NaN and does not. The console
  issues keys prefixed `sk-ant-usr`; Hermes sent them as OAuth tokens until
  v0.22 (lesson-557, NousResearch/hermes-agent#133856), so the pin must not go
  back below it. Spec AI-012 AC2.
- **Create the workspace and key** (once, in the Anthropic Console; the
  Default workspace takes no spend limit and cannot be renamed, so each service
  gets a workspace of its own):
  1. Settings > Workspaces > Create workspace, named `hermes-kubelab`.
  2. Select it, open Spend limits, set 20 USD a month. A workspace limit can be
     lower than the organization's, never higher.
  3. Settings > API keys > Create key, in that workspace.
  4. Store it without printing it:
     with the key in a variable of your shell (pasted at a hidden prompt, never
     on the command line), `toolkit secrets set
     apps.services.ai.hermes_kubelab.anthropic_api_key --env prod --from-env
     VAR`, then `make provision NODE=ace2 ENV=prod TAGS=agent_stack`.
  5. Read `anthropic-workspace-id` off one response made with that key (it
     must be this workspace's id, not the Default's), and keep the Usage page
     filtered on the workspace as the signal that the cap is working.
- **Prove it still works** (after an image bump, or a rotated key). In v0.22
  `hermes chat` is a client of the gateway, so a per-launch `NAN_API_KEY` or
  `--api-key` never reaches the model call and the turn answers on NaN
  (lesson-574). Fail NaN in a throwaway gateway instead, with its own
  `HERMES_HOME` and Slack and the API off, so no live state or channel is
  touched. On ace2, as the agent's user against its rootless daemon:
  1. `docker run -d --rm --name hermes-fallback-probe --dns 1.1.1.1 --env-file
     /var/lib/hermes-kubelab/hermes.env -e NAN_API_KEY=sk-deliberately-invalid
     -e SLACK_BOT_TOKEN= -e SLACK_APP_TOKEN= -e SLACK_ALLOWED_USERS= -e
     API_SERVER_ENABLED=false -e HERMES_HOME=/opt/probe-home -v
     /var/lib/hermes-kubelab/hermes-config.yaml:/opt/probe-home/config.yaml:ro
     <the pinned image> gateway run`, then wait about 45 s.
  2. `docker exec -u hermes hermes-fallback-probe hermes chat -q "Reply with
     the single word: pong"`. Expect `Model fallback: ... authentication
     failed; using claude-haiku-5-5 via anthropic.` and the answer `pong`.
  3. `docker rm -f hermes-fallback-probe`.
  To prove it against the live pool state too, copy `auth.json` (and the rendered
  config) into a scratch directory owned by the container's `hermes` uid and mount
  that as `HERMES_HOME`; delete the copy afterwards. Codifying this is AI-018 (#2299).
  A `400 credit balance is too low` instead of `pong` means the key is being
  sent as OAuth again.
- **No command scanner.** v0.22 removed the bundled tirith scanner. What
  remains is the sandbox with no network (`terminal.docker_network: false`) and
  Hermes's own approval patterns. Do not re-add `security.tirith_*`: upgrading
  deletes them.

## Start, or converge after any change

```bash
make provision NODE=ace2 ENV=prod TAGS=agent_stack
```

A second run must report `changed=0`. The role verifies, on every run:
Open WebUI answers on the Tailscale address, the break-glass account is the
seeded admin, the agent's uid cannot open a tailnet connection (the VPS and
ace2's own published port), the gateway answers, and the sidecar reports
`Running` with `tag:hermes`. Any of these failing fails the play.

It also verifies the MCP bridge from inside Open WebUI's container, with the
key Open WebUI holds: 401 without the key, no write tool in its spec, a
non-empty `/vault` listing, and `server:vault` in the break-glass admin's tool
list.

The bridge's image is built here, not in CI, from
`roles/agent_stack/files/mcp-bridge/`. A merged Dependabot PR on that
directory (mcpo's digest, or the filesystem server's lockfile) changes nothing
on ace2 until the next provision, which rebuilds it; an unchanged context is a
cached build and reports no change.

`CHECK=1` runs it in check mode and changes nothing.

## Stop

- **Open WebUI**: `sudo systemctl stop agent-stack-webui.service`. A provision
  starts it again.
- **hermes-kubelab, everything the agent runs**: `sudo systemctl stop
  agent-stack-egress.service`. The agent's user manager requires that unit, so
  systemd stops `user@<uid>.service` with it, and the rootless daemon and every
  container on it go down. This is the kill switch: it removes the agent and
  the rule that confines it together, never one without the other. The vault
  sync runs as the same uid from a system unit, so it is bound to the rule too
  (lesson-552). The service has `Requisite=`, so it refuses to start without
  the rule, and `PartOf=`, so a run in flight stops with it. The timer has
  `PartOf=` too. A run stopped this way counts as success
  (`SuccessExitStatus=SIGTERM`), so the kill does not page. Measured
  2026-10-10: after the stop, no process of the uid was left at 180 s.
  Lingering did not restart the user manager in ~15 min. The timer, the rule
  and the manager were all `inactive`, and nothing paged. The agent's zone
  writes from before the stop wait until the restart, and then push.
- **Start again after a kill**: `make provision NODE=ace2 ENV=prod
  TAGS=agent_stack`. It loads the rule, starts the user manager and enables
  the sync timer again (measured: `changed=3`, then `changed=0`).

## The vault zone

The agent writes files; it never commits. Its sandbox sees the vault clone
read-only at `/vault` and only `/vault/80_agents/hermes-kubelab/` writable.
`hermes-kubelab-vault-sync.service` commits that zone as `hermes-kubelab` and
pushes it. A failed run pages through `kubelab-notify@`.

- **Is it syncing?** `journalctl -u hermes-kubelab-vault-sync -n 20` on ace2,
  and `git -C ~/Projects/knowledge log --author=hermes-kubelab -3` on any
  checkout after a pull.
- **Run it now**: `sudo systemctl start hermes-kubelab-vault-sync.service`.
- **It failed.** The journal names the reason, and none is fixed by retrying:
  - *changes outside the zone in the clone*, or *unpushed commits touch paths
    outside*: something other than the sandbox wrote to the clone. Read the
    paths it lists before touching anything.
  - *cannot fast-forward*: someone else changed a file under the zone that the
    agent also changed. The zone has one writer by design (C14); move the other
    change out of the zone, then run the sync.
  - *push refused*: the token. See "Rotate".
  An exit 75 is not a failure: the remote moved during the push, and the next
  run commits on the new tip.
- **Memories**: the zone's `memories/` is mounted over the gateway's, so what the agent remembers is committed by the same sync. The gateway's lock files and temporaries (`*.lock`, `.mem_*`) are `0600` as a subuid the sync user cannot read; the sync's root-owned ignore file (`vault-ignore` next to the script) leaves them out. If a sync fails on `Permission denied` under `memories/`, that file is the first place to look.
- **Before seeding a job into the zone**, check each command it runs:
  `docker exec -u hermes hermes-kubelab hermes approvals test --env-type local
  -- <cmd>`, as the agent's user against its daemon. With the vault mounted,
  `ask-approval` means a scheduled job is refused under `cron_mode: deny`
  (lesson-540). There is no command scanner to ask since v0.22 (above).

## Scheduled jobs

Jobs are declared in `apps.services.ai.hermes_kubelab.cron` (`common.yaml`) and reconciled by `make provision NODE=ace2 ENV=prod TAGS=agent_stack` (`CHECK=1` shows the diff). The gateway is not restarted: it reads `cron/jobs.json` on every tick.

- **Ownership**: the role owns jobs whose name starts with `kubelab:`. A job created by hand under another name is never edited or removed. A job dropped from the declaration is removed; one changed in the declaration is edited in place, so its id and history stay.
- **Modes**: `agent` runs a turn from `prompt`; `script` runs a file from `files/hermes-scripts/` and delivers its stdout. An `agent` job may also name a `script`: the output is injected into the turn, and a last line of `{"wakeAgent": false}` (or no output) skips the turn and its cost.
- **Scripts** ship from the role into a directory mounted read-only over `<data>/scripts/`. They run in the gateway, which sees `HERMES_HOME` and not `/vault`.
- **Delivery** defaults to `slack:<home_channel>`, failures included.
- **Run one now**: `hermes cron run <id>` inside the gateway, as the `hermes` user; it fires at the next tick, within a minute. `hermes cron list` prints text only; read `cron/jobs.json` for status.
- **The digest** (`kubelab:digest`, a script job) reports the gateway, the sidecar, the sandbox count, the disk and the month's usage per model and provider. A stopped container or an unreachable Docker is its first line; it never prints nothing, because a no-agent job with empty stdout sends nothing.
- **A job's commands** are checked against the approvals under `cron_mode: deny`: test them with `hermes approvals test --env-type local` before declaring the job.

## Persona

`SOUL.md` is the role's, mounted read-only over the data directory's copy, so the agent cannot rewrite who it is. The public part is `templates/hermes-soul.md.j2`. The operator's private profile is `80_agents/operator/hermes-kubelab/profile.md` in the vault: the provision copies it from the root-owned mirror on the node (frontmatter stripped), joins it after the public part with `assemble`, and never prints it (`diff: false`). Without the file the persona is the public part alone.

- **Change the public text**: edit the template, `CHECK=1`, provision. A changed `SOUL.md` recreates the gateway, because a rename leaves a single-file bind mount on the old file.
- **Change the profile**: edit it in the vault, wait for `vault-mirror.timer`, provision.
- **Check it live**: an edit of `SOUL.md` from inside the gateway fails (read-only), and the next session's context starts with the role's file.

## Managed skills

`apps.services.ai.hermes_kubelab.skills` names the vault skills (`00_meta/skills/<name>/`) the agent is given. The provision copies each from the root-owned vault mirror into `/var/lib/hermes-kubelab/hermes-skills` and mounts it read-only at `/managed-skills`, which `skills.external_dirs` points at: the agent can use a managed skill and cannot change it.

- **Add one**: append its name, `make provision NODE=ace2 ENV=prod TAGS=agent_stack` (`CHECK=1` first). The mirror must already hold it, so merge the skill into the vault and wait for `vault-mirror.timer`; a missing `SKILL.md` fails the provision.
- **Not a built-in's name**: a built-in outranks an external skill, so `systematic-debugging` and `test-driven-development` would be installed and never read (lesson-580). `hermes skills list` in the gateway shows the built-ins.
- **Remove one**: drop the name; the provision deletes its directory.

## Repository docs mirror

`agent-stack-docs-mirror.timer` (hourly) keeps the repository's `docs/` readable, read-only, in two places: `/docs` in the agent's sandbox and `/docs` in Open WebUI's MCP bridge (the `vault` tool server now lists both). The remote is public, so the refresh carries no credential.

- **Two root-owned checkouts of one bare repository**: `/opt/agent-stack/docs-mirror/tree/docs` (the bridge) and `/var/lib/hermes-kubelab/docs-mirror/docs` (the sandbox, in the agent's home because its rootless daemon must read it). Root owns both, so the agent reads the docs and cannot edit them. The settings are `apps.services.ai.hermes_kubelab.docs_mirror` in `common.yaml`.
- **Refresh now**: `sudo systemctl start agent-stack-docs-mirror.service` on ace2, then `journalctl -u agent-stack-docs-mirror -n 20`. A run that fails to fetch keeps the last trees and pages. One that fails between the two checkouts (a full disk) leaves them disagreeing until the next successful run, an hour later.
- **The docs are always mounted into the sandbox**, even without the vault token. That turns Hermes's command guards on for the docker backend, which only makes the sandbox stricter.
- Anything written into a tree is discarded at the next run; a file deleted upstream leaves the tree.

## Curator analyzer

`hermes-kubelab-curator-analyze.timer` (Mondays 16:00 local) runs the recurrence analyzer as the agent's user. It reads the agent's own vault clone and the public `docs/lessons/` of the repositories, and writes `80_agents/hermes-kubelab/curator/candidates.json`; the vault sync commits it. Nothing is promoted: the judge and the emitter (see "Curator judge and proposals") read the file.

- Run now: `sudo systemctl start hermes-kubelab-curator-analyze.service` on ace2, then `journalctl -u hermes-kubelab-curator-analyze -n 20`.
- Exit 3 is the fetch guard: a repository whose lessons could not be listed fails the run rather than writing a thin candidate list.
- An empty `candidates.json` after a clean run means no recurrence; a missing file means the unit never ran.

## Curator judge and proposals

Two jobs follow the analyzer on Mondays (UTC): `kubelab:curator-judge` at 14:20 and `kubelab:curator-emit` at 14:50. The judge is an agent turn with `deliver: local`, so nothing goes to Slack. Its pre-run script (`curator-judge-input.py`) trims `curator/candidates.json` to each candidate's id and excerpts; Hermes injects that output into the prompt (cut at 8000 characters) and the model answers with JSON verdicts. The emitter (`emit-proposals.py`, a no-agent job) reads the judge's latest run record and writes one draft per `RECURRENCE` to `proposals/<id>.md`; the vault sync commits it. The operator disposes of the drafts.

- **The gateway mounts** `curator/` read-only and `proposals/` writable (`HERMES_VAULT_ZONE` names the zone's path inside it). The job scripts run in the gateway, which sees nothing else of the zone. `proposals/` is `01777`: the gateway's user writes, the sync user reads.
- **Model output is data.** An id that is not ten hex digits, a label other than `RECURRENCE`, or an id the analyzer did not produce is ignored. A draft is created, never replaced, so a re-run is safe and a draft being triaged is never overwritten. The evidence comes from `candidates.json` by id, never from the run record.
- **The run is found by its title**, `# Cron Job: kubelab:curator-judge`, and its response is the record's last section. Not by a phrase in the prompt: the prompt holds the injected script output (lesson-582).
- **Run both now**: `hermes cron run <id>` for the judge, wait for it to end, then the emitter (ids in `cron/jobs.json`). Read `cron/output/<job id>/` for the record.
- **Nothing printed means nothing sent**: a week without a new recurrence is silent by design. `last_status: ok` with no new file in `proposals/` is that case, not a failure.
- **Reading the drafts**: each carries the judge's label, placement, confidence, one-line root cause and the evidence. The suggested tier is a hint; a human confirms. The disposing skill (`dispose-proposals`, dotfiles) is a separate change.

## Re-register the sidecar

Needed when the sidecar reports anything but `Running` (for example after its
Headscale node was deleted or expired).

1. A provision mints a new single-use, one-hour key under the `agents` user
   whenever `tailscale status` in the sidecar does not say `Running`, so in most
   cases step 3 alone is enough. The key is written to
   `/var/lib/hermes-kubelab/hermes-tailscale.env`, consumed at login, and the
   file is emptied and the sidecar recreated in the same run.
2. If the node must be replaced, not just logged in again, the operator removes
   the old node on Headscale (`headscale nodes list`, then `nodes delete -i
   <id>`) and the state directory on ace2. This is a deliberate, destructive
   step and the role never does it.
3. `make provision NODE=ace2 ENV=prod TAGS=agent_stack`.
4. Confirm with `headscale nodes list`: the node is listed under
   `tagged-devices` with `tag:hermes`.

*Not yet measured live*: the registering run with its same-run recreate, and
the re-login of a sidecar that reports `NeedsLogin` (spec `verification.md`,
PR 3b-2).

## Slack

The gateway connects to Slack in Socket Mode as `@hermeskubelab`, with no
inbound port. Both tokens come from prod's vault
(`apps.services.ai.hermes_kubelab.slack_{bot,app}_token`). The allowlist and
the home channel come from `apps.services.ai.hermes_kubelab.slack` in
`common.yaml`. With either token missing, or with `allowed_users` empty, the
role starts no Slack at all.

- **Who it obeys**: the members in `allowed_users`, and only in the home
  channel (`#agent-fleet`) or a 1:1 DM. In the channel, a top-level message
  must @mention the bot. A DM from anyone else is dropped: no pairing code is
  sent, because an approved code is a grant held in the gateway's state.
- **Add a user**: append the member ID (Profile > ⋮ > Copy member ID), then
  provision ace2.
- **Proven at every provision**: `GET /health/detailed` reports
  `platforms.slack.state: connected`. That proves the tokens and the
  connection, not delivery: Socket Mode connects whether or not the bot is in
  the channel. Once per channel, the operator runs
  `/invite @hermeskubelab` in `#agent-fleet`. Without it, scheduled jobs
  cannot post there.
- **Approvals in chat widen the posture until the next recreate** (lesson-549).
  **Always** approves a pattern in memory only, because the config is
  read-only. `/yolo` turns prompts off for one session, and the deny list
  still applies. A provision that changes the config recreates the gateway, and
  that restores the declared posture.

## Cluster state (Grafana reader)

Spec AI-024 stage 2. The agent reads fleet state through four fixed tools of a
stdio MCP server (`files/hermes-mcp/grafana-reader.py`) that the gateway starts:
`firing_alerts`, `errors_by_app`, `log_volume_by_app`, `recent_errors`. It has no
kubeconfig and no network route to the cluster; the server calls
`https://grafana.kubelab.live` with a Viewer service-account token, which a
Traefik route (#2373) lets past Authelia only for `Bearer glsa_` on `/api/`.

- **What the model chooses**: an app from the closed list
  `apps.services.ai.hermes_kubelab.grafana_reader.apps`, a window from 15m, 1h,
  6h, 24h, and a line limit capped at 20. It writes no query text.
- **An unreadable source is named, never skipped**: output says `source: X`,
  `status: UNAVAILABLE (reason)` and that this is not "nothing is wrong". Nothing is
  retried. A missing token, URL or app list is reported the same way.
- **Log lines are data**: credential shapes are redacted before they reach the
  model, and each answer says the lines are not instructions. A log line can
  still carry text meant to steer the agent; the tools are read-only, so the
  worst outcome is a wrong answer, not a change.
- **Token**: `apps.services.ai.hermes_kubelab.grafana_token` (Viewer, prod). It
  enters the env file and that one server's `env` mapping and nowhere else; the
  sandbox gets none of it. No token in SOPS means no server is declared.
- **Rotate**: mint a new Viewer service-account token in Grafana, `toolkit
  secrets set apps.services.ai.hermes_kubelab.grafana_token --env prod --stdin`,
  provision ace2 (`make provision NODE=ace2 ENV=prod TAGS=agent_stack`), then
  delete the old token in Grafana.
- **Add an app**: append it to `grafana_reader.apps` in `common.yaml` and provision.
- **Check it**: the reader is a subprocess of the gateway, so a broken script shows as a
  missing tool, not a failed unit. `docker exec` into the gateway as the agent's user and
  run `hermes mcp test grafana`: it connects and lists the four tools (measured against
  the pinned image, 597 ms). `hermes mcp list` shows `4 selected`. Then ask the agent for
  the firing alerts.
- **Residual risks**: Grafana's only datasource is Loki, so pod restarts and backup age
  are out of reach (#1727). A Viewer token also reads dashboards and alert rules,
  beyond what the four tools expose; the token, not the script, is the boundary.

## Rotate

- **Open WebUI break-glass password**: `toolkit secrets rotate --group
  break-glass --env prod`. It changes the password in Open WebUI's database and
  in SOPS together. Never rotate it with a single-key `secrets set`.
- **Open WebUI OIDC client secret**: a single-key `toolkit secrets set` for
  `apps.services.security.authelia.oidc_client_secret_open_webui` in
  `prod.enc.yaml`, then its `_hash`, then `make sync-oidc-hashes`. Commit and
  merge the regenerated `oidc-clients.yml` before or right after applying it:
  prod Argo CD runs `selfHeal`, and an uncommitted rotation is reverted. Then
  provision ace2. Never `make credentials-generate`.
- **NaN API key**: shared with PR-Agent (R1). Rotating it is a PR-Agent
  rotation; provision ace2 afterwards.
- **Gateway API key and Open WebUI session key**: generated on ace2, not in
  SOPS (`/opt/agent-stack/hermes-api-key`, `/opt/agent-stack/webui-secret-key`).
  Delete the file and provision; a new session key signs every Open WebUI user
  out.
- **Sidecar node key**: see "Re-register the sidecar".
- **Slack tokens** (`slack_bot_token`, `slack_app_token`, prod): reissue the
  token in the Slack app (OAuth & Permissions for the bot token, Basic
  Information > App-Level Tokens for the app token), `toolkit secrets set ...
  --stdin`, provision ace2 (the env file changes, so the gateway is recreated,
  and the probe proves the connection), then revoke the old app token.
- **Vault token** (`apps.services.ai.hermes_kubelab.github_token`, prod): mint a
  fine-grained token for `mlorentedev/knowledge` (Contents: read and write),
  `toolkit secrets set ... --stdin`, provision ace2 (it rewrites
  `/opt/agent-stack/vault-token` and runs the sync once, which proves the new
  token by pushing), then revoke the old one on GitHub.

## When Authelia is down

`make break-glass SVC=open-webui ENV=prod` reaches Open WebUI on ace2's own
tailnet address, derived from the route's EndpointSlice, with the local
`breakglass` account. The public name refuses that password. See
[break-glass](break-glass.md).

## Access review

`make auth-review ENV=prod` reads each Open WebUI account's live role and
compares it with the declared groups; `APPLY=1` corrects drift.

## Backup and restore

ace2 ships to its own bucket, `kubelab-backup-ace2`, with its own token and restic
password. The token pair is `backup.r2.nodes.ace2.*` in `prod.enc.yaml`. The
password is `backup.nodes.ace2.restic_password` in `common.enc.yaml`, so read it
with `SECRETS_ENV=common`, not `prod`. It was in its own bucket from the first snapshot, so it never had a copy in
the shared one (AI-009 AC7, #2115). The sources are declared in
`backup.sources.ace2`:

- **open_webui**: the `open-webui-data` volume. `webui.db` and
  `vector_db/chroma.sqlite3` are snapshotted with `sqlite3 .backup`. `cache/`
  (the embedding and whisper models, 1.07 GB of 1.1 GB) is left out at tier 3.
- **hermes**: `/var/lib/hermes-kubelab/data`, with its six databases snapshotted
  the same way. `bin/` and `home/.cache` are left out at tier 3. The rendered env
  files sit outside this path and are rebuilt from SOPS, so they are never in a
  snapshot.

Read-only checks, in this order:

- **Is it shipping?** `make watcher-run NAME=r2-backup-watcher ENV=prod` names ace2
  with its pinned repository and the age of its newest snapshot. ace2 is an
  on-demand node, so a stale snapshot while the node is off is expected.
- **Is the heartbeat arriving?** Each ship posts to the `ops-backup-node-ace2`
  push monitor in Uptime Kuma.
- **Ship now:** `make backup-node NODE=ace2 ENV=prod`.

**Check that a restore works:** `make backup-drill-node NODE=ace2 ENV=prod`. It
restores the newest snapshot from ace2's own repository into a scratch directory
on this machine. It passes only if each source restored files, every database
listed above answers `ok` to `PRAGMA integrity_check`, and every excluded path is
absent. It prints names, counts and timings, and removes the restore on every
exit path. First run, 2026-10-08, snapshot `dfcd8b1c`: both sources whole,
hermes 387 files (4.1 MB) with its six databases, open_webui 2 files (0.9 MB)
with its two, `bin`, `home/.cache` and `cache` absent. It restored in 6 s,
10 s end to end.

**To put the data back**, follow "Restoring — normal case" in
[offsite-backup-restore.md](offsite-backup-restore.md), with ace2's own
credentials and the repository from
`infra/k8s/base/services/r2-backup-watcher/targets.txt`. Run the drill first,
and stop the service that owns the data before you replace it (see
[Stop](#stop)). Expect the models in `cache/` to download again on the first
query after the restore. Losing the sidecar's state costs only a re-registration
(see [Re-register the sidecar](#re-register-the-sidecar)). Putting the data back
over a live node has not been done yet.
