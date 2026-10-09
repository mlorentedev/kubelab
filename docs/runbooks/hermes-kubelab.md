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
| tailnet refusal for the agent's uid | root | `agent-stack-egress.service`, `RequiredBy=user@<uid>` | `/opt/agent-stack/agent-egress.nft` |
| bridge wait before the agent's manager | root | `agent-stack-hermes-bind.service`, `WantedBy=user@<uid>` | none |
| vault sync (ADR-068 D4, amended) | uid `hermes-kubelab`, token from systemd | `hermes-kubelab-vault-sync.timer`: 2 min after boot, then every 15 min | clone `/var/lib/hermes-kubelab/vault`; token `/opt/agent-stack/vault-token` (root, 0600) |

Open WebUI is reached only at `http://ace2.kubelab.internal:3080` over the
tailnet, with OIDC against prod Authelia. The gateway's API listens on
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

## Start, or converge after any change

```bash
make provision NODE=ace2 ENV=prod TAGS=agent_stack
```

A second run must report `changed=0`. The role verifies, on every run:
Open WebUI answers on the Tailscale address, the break-glass account is the
seeded admin, the agent's uid cannot open a tailnet connection (the VPS and
ace2's own published port), the gateway answers, and the sidecar reports
`Running` with `tag:hermes`. Any of these failing fails the play.

`CHECK=1` runs it in check mode and changes nothing.

## Stop

- **Open WebUI**: `sudo systemctl stop agent-stack-webui.service`. A provision
  starts it again.
- **hermes-kubelab, everything the agent runs**: `sudo systemctl stop
  agent-stack-egress.service`. The agent's user manager requires that unit, so
  systemd stops `user@<uid>.service` with it, and the rootless daemon and every
  container on it go down. This is the kill switch: it removes the agent and
  the rule that confines it together, never one without the other. *Not yet
  measured live*: whether lingering starts the user manager again before the
  next provision.

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
- **Before seeding a job into the zone**, check each command it runs:
  `docker exec -u hermes hermes-kubelab hermes approvals test --env-type local
  -- <cmd>`, as the agent's user against its daemon. With the vault mounted,
  `ask-approval` means a scheduled job is refused under `cron_mode: deny`
  (lesson-540).

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
